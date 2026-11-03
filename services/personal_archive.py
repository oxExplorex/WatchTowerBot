"""Resumable re-encryption. Existing envelopes survive any failed transaction."""
import asyncio
import json
import os
import re
from uuid import uuid4

from sqlalchemy import select, update

from core.personal_crypto import context, seal_text
from db.media_models import MessageAttachment
from db.message_models import MessageReceipt, MessageRevision, StoredMessage
from db.personal_models import OwnerArchiveKey
from db.repositories.messages_repo import comparable_payload, personal_fingerprint
from db.repositories.personal_repo import PersonalKeyRepository, lock_owner
from utils.crypto_store import decrypt_text


def media_store():
    from core.media_store import MediaStore

    return MediaStore(max_file_bytes=int(os.getenv("MEDIA_MAX_FILE_MB", "100")) * 1024**2,
                      max_total_bytes=int(os.getenv("MEDIA_MAX_TOTAL_MB", "5120")) * 1024**2)


async def _migrate_file(store, owner_id, blob_key, public_key):
    task = asyncio.create_task(asyncio.to_thread(store.migrate_blob, owner_id, blob_key, public_key))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # Do not leave a filesystem mutation running after its owner lock is freed.
        await asyncio.gather(task, return_exceptions=True)
        raise


async def migrate_batch(session_factory, owner_id, store, *, batch_size=100):
    if not 1 <= batch_size <= 1000:
        raise ValueError("Invalid migration batch size")
    async with session_factory()() as session, session.begin():
        key = await lock_owner(session, owner_id)
        if key is None:
            return True
        revisions = list((await session.scalars(select(MessageRevision).join(StoredMessage).where(
            StoredMessage.owner_id == owner_id, MessageRevision.encryption_version == 1).order_by(
            MessageRevision.uuid).limit(batch_size))).all())
        for revision in revisions:
            plaintext = decrypt_text(revision.payload)
            payload = json.loads(plaintext)
            revision.payload = seal_text(key.public_key, plaintext, context(owner_id, f"revision:{revision.uuid}"))
            revision.fingerprint = personal_fingerprint(owner_id, comparable_payload(payload))
            revision.encryption_version = 2
            receipts = (await session.scalars(select(MessageReceipt).where(MessageReceipt.revision_uuid == revision.uuid))).all()
            for receipt in receipts:
                if re.fullmatch(r"[0-9a-f]{64}:\d+", receipt.event_key):
                    # Old fallback IDs were env-keyed hashes of the plaintext.
                    receipt.event_key = f"legacy:{uuid4().hex}"
        key.migrated_revisions += len(revisions)
        # One bounded file per transaction; never load the archive into RAM.
        attachment = await session.scalar(select(MessageAttachment).where(
            MessageAttachment.owner_id == owner_id, MessageAttachment.status == "stored",
            MessageAttachment.encryption_version == 1).order_by(MessageAttachment.uuid).limit(1))
        if attachment is not None:
            await _migrate_file(store, owner_id, attachment.blob_key, key.public_key)
            # Several revisions may point to the same immutable physical blob.
            await session.execute(update(MessageAttachment).where(
                MessageAttachment.owner_id == owner_id, MessageAttachment.blob_key == attachment.blob_key,
                MessageAttachment.encryption_version == 1).values(encryption_version=2))
            key.migrated_files += 1
        else:
            orphan = await asyncio.to_thread(store.legacy_blob, owner_id)
            if orphan is not None:
                await _migrate_file(store, owner_id, orphan, key.public_key)
                key.migrated_files += 1
        locators = (await session.scalars(select(MessageAttachment).where(
            MessageAttachment.owner_id == owner_id, MessageAttachment.status == "stored",
            MessageAttachment.sources_encryption_version == 1).order_by(MessageAttachment.uuid).limit(batch_size))).all()
        for item in locators:
            item.sources = seal_text(key.public_key, decrypt_text(item.sources), context(owner_id, f"sources:{item.uuid}"))
            item.sources_encryption_version = 2
        await session.flush()
        remaining_revision = await session.scalar(select(MessageRevision.uuid).join(StoredMessage).where(
            StoredMessage.owner_id == owner_id, MessageRevision.encryption_version == 1).limit(1))
        remaining_file = await session.scalar(select(MessageAttachment.uuid).where(
            MessageAttachment.owner_id == owner_id, MessageAttachment.status == "stored",
            (MessageAttachment.encryption_version == 1) | (MessageAttachment.sources_encryption_version == 1)).limit(1))
        complete = remaining_revision is None and remaining_file is None
        if complete:
            complete = await asyncio.to_thread(store.legacy_blob, owner_id) is None
        key.migration_state, key.last_error = ("complete" if complete else "pending"), None
        return complete


async def run_personal_archive_migration(bot):
    from core.logging import bot_logger
    from db.session import get_session_factory

    repository = PersonalKeyRepository(get_session_factory)
    store = media_store()
    notified = set()
    while True:
        try:
            for owner_id in await repository.owners():
                try:
                    complete = await migrate_batch(get_session_factory, owner_id, store)
                    if complete:
                        notified.discard(owner_id)
                except Exception as exc:
                    bot_logger.warning("Personal archive migration deferred: owner=%s error=%s", owner_id, type(exc).__name__)
                    async with get_session_factory()() as session, session.begin():
                        await lock_owner(session, owner_id)
                        await session.execute(update(OwnerArchiveKey).where(OwnerArchiveKey.owner_id == owner_id).values(
                            migration_state="error", last_error=type(exc).__name__))
                    if owner_id not in notified:
                        notified.add(owner_id)
                        try:
                            await bot.send_message(owner_id, "Перенос старого архива приостановлен из-за ошибки. "
                                                   "Старые данные сохранены, бот повторит попытку автоматически.")
                        except Exception:
                            pass
                await asyncio.sleep(0)
        except Exception as exc:
            bot_logger.warning("Personal archive queue unavailable: %s", type(exc).__name__)
        await asyncio.sleep(5)
