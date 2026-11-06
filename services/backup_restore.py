"""Validate a complete backup before an additive, owner-locked DB transaction."""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import time
from uuid import UUID

from sqlalchemy import func, select

from core.backup_format import BackupReader, BLOB_FRAME, InvalidBackup, JSON_FRAME
from core.backup_media import restore_blob
from core.backup_parts import PartsReader
from core.personal_crypto import context, open_text, seal_text, unlock_private_key
from core.thread_tools import run_blocking
from db.media_models import MessageAttachment
from db.message_models import MessageReceipt, MessageRevision, StoredMessage
from db.models import HistoryUser, User
from db.personal_models import OwnerArchiveKey
from db.repositories.messages_repo import comparable_payload, personal_fingerprint
from db.repositories.personal_repo import lock_owner
from utils.crypto_store import blind_index, encrypt_text, message_fingerprint

MODELS = {"messages": StoredMessage, "revisions": MessageRevision, "receipts": MessageReceipt,
          "attachments": MessageAttachment, "events": HistoryUser}
MAX_METADATA = 256 * 1024 * 1024


def _copy(row, **changes):
    # Pydantic model_copy also copies SQLAlchemy's instance state; construct a fresh ORM object.
    return type(row).model_validate(row.model_dump() | changes)


@dataclass
class PreparedBackup:
    bundle: dict
    private_key: object
    rows: list = field(default_factory=list)
    names: list = field(default_factory=list)
    blobs: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)


def prepare_backup(paths, root, owner_id, secret):
    """Only authenticated ciphertext blobs are staged on disk; metadata stays in RAM."""
    stream = PartsReader(paths)
    blob, active, remaining, digest, metadata = None, None, 0, None, 0
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        reader = BackupReader(stream, owner_id, secret)
        result = PreparedBackup(reader.bundle, reader.private_key)
        info_seen = False
        for kind, content in reader:
            if result.summary:
                raise InvalidBackup("Data after summary")
            if kind == BLOB_FRAME:
                if blob is None or not content or len(content) > remaining:
                    raise InvalidBackup("Invalid media chunk")
                blob.write(content)
                remaining -= len(content)
                digest.update(content)
                continue
            if kind != JSON_FRAME:
                raise InvalidBackup("Unknown record")
            metadata += len(content)
            if metadata > MAX_METADATA:
                raise InvalidBackup("Backup metadata exceeds limit")
            record = json.loads(content)
            record_type = record["type"]
            if blob is not None:
                if record_type != "blob_end" or remaining or record.get("sha256") != digest.hexdigest():
                    raise InvalidBackup("Incomplete media")
                blob.close()
                blob = None
                continue
            if not info_seen:
                if record_type != "info" or record.get("scope") != "private":
                    raise InvalidBackup("Missing archive information")
                info_seen = True
            elif record_type == "row":
                table, data = record["table"], record["data"]
                model = MODELS.get(table)
                if model is None or set(data) != set(model.model_fields):
                    raise InvalidBackup("Unsupported archive row")
                row = model.model_validate(data)
                if table in {"messages", "attachments"} and row.owner_id != owner_id:
                    raise InvalidBackup("Foreign archive row")
                if table == "events" and (row.admin_id != owner_id or not row.chat_id or row.chat_id <= 0):
                    raise InvalidBackup("Foreign history event")
                if table == "messages" and (row.chat_id <= 0 or row.channel_namespace or row.message_id <= 0
                                             or row.account_user_id <= 0):
                    raise InvalidBackup("Not a personal conversation")
                result.rows.append((table, row))
            elif record_type == "name":
                if (type(record.get("user_id")) is not int or record["user_id"] <= 0
                        or any(value is not None and (not isinstance(value, str) or len(value) > 512)
                               for value in (record.get("username"), record.get("full_name")))):
                    raise InvalidBackup("Invalid peer information")
                result.names.append(record)
            elif record_type == "coverage":
                pass  # Viewer metadata, never assert that a restored live account was fully scanned.
            elif record_type == "blob":
                key, size = record["key"], record["size"]
                if (not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                        or type(size) is not int or not 1 <= size <= 256 * 1024 * 1024 or key in result.blobs):
                    raise InvalidBackup("Invalid media identity")
                active = root / f"{key}.wtm"
                blob = active.open("xb")
                result.blobs[key] = active
                remaining, digest = size, hashlib.sha256()
            elif record_type == "summary":
                result.summary = record
            else:
                raise InvalidBackup("Unknown record type")
        if blob is not None or not info_seen or not result.summary:
            raise InvalidBackup("Incomplete archive")
        identities = set()
        expected_blobs = set()
        for table, row in result.rows:
            identity = (table, row.uuid)
            if identity in identities:
                raise InvalidBackup("Duplicate archive row")
            identities.add(identity)
            if table == "attachments" and row.status == "stored":
                expected_blobs.add(row.blob_key)
        if expected_blobs != set(result.blobs):
            raise InvalidBackup("Media list does not match archive")
        return result
    except InvalidBackup:
        raise
    except Exception:
        raise InvalidBackup("Invalid backup data") from None
    finally:
        if blob is not None:
            blob.close()
        stream.close()


async def restore_backup(prepared, owner_id, secret, *, session_factory, store, current_secret=None):
    """Existing messages/flags win; missing immutable revisions and files are added."""
    async with session_factory()() as session:
        current = await session.get(OwnerArchiveKey, owner_id)
    if current is None:
        public, private = prepared.bundle["public_key"], prepared.private_key
    else:
        public = current.public_key
        private = await run_blocking(unlock_private_key, owner_id, current, current_secret or secret)
    incoming_messages = {row.uuid: row for table, row in prepared.rows if table == "messages"}
    revisions, sources = {}, {}
    for table, row in prepared.rows:
        if table == "revisions":
            if row.encryption_version != 2 or row.message_uuid not in incoming_messages:
                raise InvalidBackup("Invalid revision reference")
            payload = json.loads(await run_blocking(open_text, prepared.private_key, row.payload,
                                                    context(owner_id, f"revision:{row.uuid}")))
            if not isinstance(payload, dict) or not isinstance(payload.get("media", []), list):
                raise InvalidBackup("Invalid message payload")
            revisions[row.uuid] = payload
            row.payload = await run_blocking(seal_text, public, json.dumps(payload, ensure_ascii=False),
                                            context(owner_id, f"revision:{row.uuid}"))
            row.fingerprint = personal_fingerprint(owner_id, comparable_payload(payload))
        elif table == "attachments":
            if row.sources_encryption_version != 2:
                raise InvalidBackup("Invalid media sources")
            value = json.loads(await run_blocking(open_text, prepared.private_key, row.sources,
                                                 context(owner_id, f"sources:{row.uuid}")))
            if not isinstance(value, list):
                raise InvalidBackup("Invalid media sources")
            sources[row.uuid] = value
    blobs = {}
    try:
        for old_key, path in prepared.blobs.items():
            blobs[old_key] = await run_blocking(restore_blob, path, owner_id, prepared.private_key, public, store)
            # Immutable deduplication may find a damaged blob or one under another
            # personal key. Never publish a DB reference that the current key cannot read.
            await run_blocking(store.read, owner_id, blobs[old_key][0], private_key=private)
        counts = {"messages": 0, "revisions": 0, "attachments": 0}
        async with session_factory()() as session, session.begin():
            locked = await lock_owner(session, owner_id)
            if (current is None and locked is not None) or (current is not None and (
                    locked is None or locked.public_key != public)):
                raise InvalidBackup("Archive key changed during import")
            if locked is None:
                session.add(OwnerArchiveKey(owner_id=owner_id, created_at=int(time.time()),
                                           migration_state="complete", **prepared.bundle))
                await session.flush()
            message_map, new_messages = {}, {}
            for source_uuid, incoming in incoming_messages.items():
                identity = {name: getattr(incoming, name) for name in ("owner_id", "account_user_id", "chat_id", "message_id")}
                existing = await session.scalar(select(StoredMessage).filter_by(**identity))
                if existing is None:
                    if await session.get(StoredMessage, source_uuid) is not None:
                        raise InvalidBackup("Message UUID conflict")
                    existing = _copy(incoming, latest_revision_uuid=None)
                    session.add(existing)
                    await session.flush()
                    new_messages[source_uuid] = existing
                    counts["messages"] += 1
                message_map[source_uuid] = existing.uuid
            for table, row in prepared.rows:
                if table != "revisions":
                    continue
                target = message_map[row.message_uuid]
                existing = await session.get(MessageRevision, row.uuid)
                if existing is not None:
                    if existing.message_uuid != target:
                        raise InvalidBackup("Revision UUID conflict")
                    continue
                number = await session.scalar(select(func.max(MessageRevision.revision_no)).where(
                    MessageRevision.message_uuid == target))
                session.add(_copy(row, message_uuid=target, revision_no=(number or 0) + 1))
                await session.flush()
                counts["revisions"] += 1
            for source_uuid, row in new_messages.items():
                latest = incoming_messages[source_uuid].latest_revision_uuid
                if latest is not None:
                    revision = await session.get(MessageRevision, latest)
                    if revision is None or revision.message_uuid != row.uuid:
                        raise InvalidBackup("Invalid latest revision")
                    row.latest_revision_uuid = latest
            for table, row in prepared.rows:
                if table == "attachments":
                    if row.revision_uuid not in revisions or row.position < 0:
                        raise InvalidBackup("Invalid attachment reference")
                    existing = await session.scalar(select(MessageAttachment).filter_by(
                        revision_uuid=row.revision_uuid, position=row.position))
                    if existing is not None:
                        if existing.owner_id != owner_id:
                            raise InvalidBackup("Foreign attachment")
                        if row.status == "stored" and (existing.status != "stored" or not existing.blob_key
                                or not store.path(owner_id, existing.blob_key).is_file()):
                            if row.blob_key not in blobs:
                                raise InvalidBackup("Missing archived media")
                            existing.blob_key, existing.stored_size = blobs[row.blob_key]
                            existing.status, existing.encryption_version, existing.sources_encryption_version = "stored", 2, 2
                            existing.sources = await run_blocking(seal_text, public, json.dumps(sources[row.uuid]),
                                                                 context(owner_id, f"sources:{existing.uuid}"))
                            existing.lease_token, existing.lease_until, existing.last_error = None, 0, None
                            existing.state_version += 1
                            counts["attachments"] += 1
                        continue
                    if await session.get(MessageAttachment, row.uuid) is not None:
                        raise InvalidBackup("Attachment UUID conflict")
                    value = sources[row.uuid]
                    if row.status == "stored":
                        if row.blob_key not in blobs:
                            raise InvalidBackup("Missing archived media")
                        row.blob_key, row.stored_size = blobs[row.blob_key]
                        row.sources = await run_blocking(seal_text, public, json.dumps(value),
                                                        context(owner_id, f"sources:{row.uuid}"))
                    else:
                        row.status, row.attempts, row.next_attempt_at = "pending", 0, 0
                        row.blob_key = row.stored_size = None
                        row.sources, row.sources_encryption_version = encrypt_text(json.dumps(value)), 1
                    row.lease_token, row.lease_until = None, 0
                    row.encryption_version = 2
                    row.file_key = message_fingerprint(f"restored:{owner_id}:{row.file_key}")
                    session.add(row)
                    counts["attachments"] += 1
                elif table == "receipts":
                    target = message_map.get(row.message_uuid)
                    if target is None or (row.revision_uuid is not None and row.revision_uuid not in revisions):
                        raise InvalidBackup("Invalid receipt reference")
                    if await session.get(MessageReceipt, row.uuid) is None and await session.scalar(select(MessageReceipt).filter_by(
                            message_uuid=target, source=row.source, event_key=row.event_key)) is None:
                        session.add(_copy(row, message_uuid=target))
                elif table == "events":
                    existing = await session.get(HistoryUser, row.uuid)
                    if existing is None:
                        session.add(row)
                    elif existing.admin_id != owner_id:
                        raise InvalidBackup("History UUID conflict")
            for name in prepared.names:
                if await session.scalar(select(User).where(User.user_id == name["user_id"])) is None:
                    session.add(User(user_id=name["user_id"], username=encrypt_text(name["username"]) if name["username"] else None,
                        full_name=encrypt_text(name["full_name"]) if name["full_name"] else None,
                        username_hash=blind_index(name["username"]) if name["username"] else None))
            await session.flush()
        return counts
    except BaseException:
        # Publication is immutable. Cleanup checks references, including concurrent live downloads.
        if blobs:
            from db.repositories.account_operations_repo import queue_blob_cleanup
            async with session_factory()() as session, session.begin():
                for key, _ in blobs.values():
                    await queue_blob_cleanup(session, owner_id, key)
        raise
