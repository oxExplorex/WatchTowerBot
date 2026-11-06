"""Owner-scoped logical snapshot; operational credentials are never exported."""
import hashlib
import time

from sqlalchemy import select, text, union

from core.backup_format import BackupWriter, BLOB_FRAME, InvalidBackup, MAX_FRAME
from core.backup_parts import PartsWriter
from core.media_store import PERSONAL_MAGIC
from core.personal_crypto import context, seal_text
from core.thread_tools import run_blocking
from db.media_models import MessageAttachment
from db.message_models import MessageReceipt, MessageRevision, StoredMessage
from db.models import Account, HistoryUser, User
from db.history_models import HistoryChat
from db.personal_models import OwnerArchiveKey
from utils.crypto_store import decrypt_text


def _blob(writer, path, key):
    with path.open("rb") as stream:
        if stream.read(4) != PERSONAL_MAGIC:
            raise InvalidBackup("Legacy media migration is not complete")
        stream.seek(0)
        size = path.stat().st_size
        writer.record({"type": "blob", "key": key, "size": size})
        digest = hashlib.sha256()
        while chunk := stream.read(MAX_FRAME - 1):
            digest.update(chunk)
            writer.write(BLOB_FRAME, chunk)
        writer.record({"type": "blob_end", "sha256": digest.hexdigest()})


async def create_backup(owner_id, root, identity, *, session_factory, store, account_user_id=None, chat_id=None):
    if (account_user_id is None) != (chat_id is None) or (chat_id is not None and (
            type(chat_id) is not int or type(account_user_id) is not int or chat_id <= 0 or account_user_id <= 0)):
        raise InvalidBackup("Invalid chat scope")
    parts = PartsWriter(root, identity)
    counts = {name: 0 for name in ("messages", "revisions", "attachments", "events", "media", "pending")}
    try:
        async with session_factory()() as session, session.begin():
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            elif dialect == "sqlite":
                await session.execute(text("BEGIN"))
            key = await session.get(OwnerArchiveKey, owner_id)
            if key is None:
                raise InvalidBackup("Personal secret setup required")
            writer = await run_blocking(BackupWriter, parts, owner_id, key)
            await run_blocking(writer.record, {"type": "info", "created_at": int(time.time()), "scope": "private"})
            scope = (StoredMessage.owner_id == owner_id, StoredMessage.chat_id > 0,
                     StoredMessage.channel_namespace == False)
            event_scope = [HistoryUser.admin_id == owner_id, HistoryUser.chat_id > 0]
            coverage_scope = [Account.admin_id == owner_id, HistoryChat.chat_id > 0]
            if chat_id is not None:
                scope += (StoredMessage.account_user_id == account_user_id, StoredMessage.chat_id == chat_id)
                event_scope += [HistoryUser.account_user_id == account_user_id, HistoryUser.chat_id == chat_id]
                coverage_scope += [Account.user_id == account_user_id, HistoryChat.chat_id == chat_id]
            message_ids = select(StoredMessage.uuid).where(*scope)
            revision_ids = select(MessageRevision.uuid).where(MessageRevision.message_uuid.in_(message_ids))
            queries = [
                ("messages", select(StoredMessage).where(*scope).order_by(StoredMessage.uuid)),
                ("revisions", select(MessageRevision).where(MessageRevision.message_uuid.in_(message_ids))
                    .order_by(MessageRevision.message_uuid, MessageRevision.revision_no)),
                ("receipts", select(MessageReceipt).where(MessageReceipt.message_uuid.in_(message_ids))),
                ("events", select(HistoryUser).where(*event_scope)),
                ("attachments", select(MessageAttachment).where(MessageAttachment.owner_id == owner_id,
                     MessageAttachment.revision_uuid.in_(revision_ids))),
            ]
            blobs = set()
            for table, query in queries:
                result = await session.stream_scalars(query.execution_options(yield_per=100))
                async for row in result:
                    data = row.model_dump(mode="json")
                    if table == "revisions" and row.encryption_version == 1:
                        data["payload"] = await run_blocking(seal_text, key.public_key, decrypt_text(row.payload),
                                                            context(owner_id, f"revision:{row.uuid}"))
                        data["encryption_version"] = 2
                    if table == "attachments":
                        if row.sources_encryption_version == 1:
                            data["sources"] = await run_blocking(seal_text, key.public_key, decrypt_text(row.sources),
                                                               context(owner_id, f"sources:{row.uuid}"))
                            data["sources_encryption_version"] = 2
                        if row.status == "stored":
                            if not row.blob_key:
                                raise InvalidBackup("Stored media has no blob")
                            blobs.add(row.blob_key)
                        else:
                            counts["pending"] += 1
                        data.update(lease_token=None, lease_until=0)
                    await run_blocking(writer.record, {"type": "row", "table": table, "data": data})
                    if table in counts:
                        counts[table] += 1
            peer_ids = union(select(StoredMessage.chat_id).where(*scope), select(StoredMessage.sender_id).where(*scope),
                             select(StoredMessage.account_user_id).where(*scope))
            users = await session.stream_scalars(select(User).where(User.user_id.in_(peer_ids)).execution_options(yield_per=100))
            async for user in users:
                await run_blocking(writer.record, {"type": "name", "user_id": user.user_id,
                    "username": decrypt_text(user.username) if user.username else None,
                    "full_name": decrypt_text(user.full_name) if user.full_name else None})
            coverage = await session.execute(select(Account.user_id, HistoryChat).join(
                HistoryChat, HistoryChat.account_uuid == Account.uuid).where(*coverage_scope))
            for account_id, progress in coverage:
                await run_blocking(writer.record, {"type": "coverage", "account_user_id": account_id,
                    "chat_id": progress.chat_id, "reached_start": progress.reached_start,
                    "oldest_message_id": progress.oldest_message_id, "known_top_id": progress.known_top_id})
            for blob_key in sorted(blobs):
                await run_blocking(_blob, writer, store.path(owner_id, blob_key), blob_key)
                counts["media"] += 1
            await run_blocking(writer.record, {"type": "summary", **counts})
            await run_blocking(writer.finish)
        return await run_blocking(parts.finish), counts
    finally:
        await run_blocking(parts.close)
