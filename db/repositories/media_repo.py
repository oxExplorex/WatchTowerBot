import json
import time
from uuid import uuid4

from sqlalchemy import and_, case, or_, select, update

from db.media_models import MessageAttachment
from db.repositories.base import conflict_insert
from db.repositories.personal_repo import lock_owner
from core.personal_crypto import context, seal_text
from utils.crypto_store import decrypt_text, encrypt_text, message_fingerprint


async def enqueue_attachments(session, revision_uuid, payload, *, owner_id, account_user_id, source):
    for position, media in enumerate(payload.get("media", [])):
        if not media.get("file_id"):
            continue
        locator = {"source": source, "account_user_id": account_user_id,
                   "file_id": media["file_id"], "kind": media["kind"]}
        identity = media.get("file_unique_id") or f"{source}:{account_user_id}:{media['file_id']}"
        file_key = message_fingerprint(f"attachment:{owner_id}:{media['kind']}:{identity}")
        insert = conflict_insert(session, MessageAttachment).values(
            revision_uuid=revision_uuid, position=position, owner_id=owner_id,
            file_key=file_key, sources=encrypt_text(json.dumps([locator])), expected_size=media.get("file_size"))
        await session.execute(insert.on_conflict_do_nothing(index_elements=["revision_uuid", "position"]))
        row = await session.scalar(select(MessageAttachment).filter_by(
            revision_uuid=revision_uuid, position=position).with_for_update())
        if row.sources_encryption_version == 2:
            # Stored content no longer needs download credentials in readable form.
            continue
        locators = json.loads(decrypt_text(row.sources))
        if locator not in locators:
            locators.append(locator)
            # IDs can expire; keep only a bounded set of recent alternatives.
            row.sources = encrypt_text(json.dumps(locators[-8:]))
            if row.status == "failed":
                row.status, row.attempts, row.next_attempt_at = "pending", 0, 0


class MediaRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def claim(self, lease_seconds=660):
        now = int(time.time())
        eligible = or_(and_(MessageAttachment.status == "pending", MessageAttachment.next_attempt_at <= now),
                       and_(MessageAttachment.status == "downloading", MessageAttachment.lease_until <= now))
        async with self._session_factory()() as session, session.begin():
            identity = await session.scalar(select(MessageAttachment.uuid).where(eligible).order_by(
                MessageAttachment.next_attempt_at, MessageAttachment.uuid).limit(1))
            if identity is None:
                return None
            result = await session.execute(update(MessageAttachment).where(
                MessageAttachment.uuid == identity, eligible).values(
                status="downloading", lease_token=uuid4(), lease_until=now + lease_seconds).returning(MessageAttachment))
            return result.scalar_one_or_none()

    async def find_stored(self, item):
        async with self._session_factory()() as session:
            return await session.scalar(select(MessageAttachment).where(
                MessageAttachment.owner_id == item.owner_id, MessageAttachment.file_key == item.file_key,
                MessageAttachment.status == "stored").limit(1))

    async def get_public_key(self, owner_id):
        from db.personal_models import OwnerArchiveKey

        async with self._session_factory()() as session:
            key = await session.get(OwnerArchiveKey, owner_id)
            return key.public_key if key else None

    async def finish(self, item, *, blob_key=None, stored_size=None, error=None, delay=0, permanent=False,
                     encryption_version=1):
        values = dict(lease_token=None, lease_until=0)
        if blob_key is not None:
            values.update(status="stored", blob_key=blob_key, stored_size=stored_size, last_error=None,
                          encryption_version=encryption_version)
        else:
            attempts = item.attempts + (0 if delay else 1)
            changed = MessageAttachment.sources != item.sources
            # A new alternative may arrive while an older download is failing.
            # Do not exhaust its retries before it has ever been tried.
            values.update(status=case((changed, "pending"), else_="failed" if permanent or attempts >= 3 else "pending"),
                          attempts=case((changed, 0), else_=attempts), last_error=error,
                          next_attempt_at=case((changed, 0), else_=int(time.time()) + (delay or 30 * 2 ** attempts)))
        async with self._session_factory()() as session, session.begin():
            key = await lock_owner(session, item.owner_id)
            current = await session.scalar(select(MessageAttachment).where(
                MessageAttachment.uuid == item.uuid, MessageAttachment.lease_token == item.lease_token).with_for_update())
            if current is None:
                return
            if key is not None and blob_key is None:
                # Cancellation between file publication and DB commit may leave
                # an orphan legacy blob, which the migration also needs to visit.
                key.migration_state, key.last_error = "pending", None
            if blob_key is not None and key is not None:
                if current.sources_encryption_version == 1:
                    values.update(sources=seal_text(key.public_key, decrypt_text(current.sources),
                                                   context(item.owner_id, f"sources:{item.uuid}")),
                                  sources_encryption_version=2)
                if encryption_version == 1:
                    # A download begun before setup may finish afterwards. Ensure
                    # even a previously completed migration will visit its blob.
                    key.migration_state, key.last_error = "pending", None
            await session.execute(update(MessageAttachment).where(
                MessageAttachment.uuid == item.uuid, MessageAttachment.lease_token == item.lease_token).values(**values))
