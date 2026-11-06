"""Prepare encrypted copies in batches; publish ownership in one DB transaction."""
import json
import time

from sqlalchemy import and_, delete, exists, or_, select, update
from sqlalchemy.orm import aliased

from core.personal_crypto import context, open_text, seal_text
from core.thread_tools import run_blocking
from db.account_operation_models import AccountOperation, TransferAttachment, TransferRevision
from db.media_models import MessageAttachment
from db.avatar_models import ChatAvatar
from db.message_models import MessageReceipt, MessageRevision, PendingMessageDeletion, StoredMessage
from db.models import Account, AccountHealth, HistoryUser, TelegramApp
from db.personal_models import OwnerArchiveKey
from db.repositories.account_locks import lock_account, unique_account
from db.repositories.account_operations_repo import queue_blob_cleanup
from db.repositories.messages_repo import comparable_payload, personal_fingerprint
from db.repositories.personal_repo import lock_owner
from utils.crypto_store import decrypt_text, message_fingerprint


def revision_query(operation):
    return select(MessageRevision).join(StoredMessage).outerjoin(TransferRevision, and_(
        TransferRevision.revision_uuid == MessageRevision.uuid,
        TransferRevision.operation_uuid == operation.uuid)).where(
        StoredMessage.owner_id == operation.owner_id, StoredMessage.account_user_id == operation.account_user_id,
        or_(TransferRevision.revision_uuid.is_(None), TransferRevision.original_payload != MessageRevision.payload,
            TransferRevision.original_version != MessageRevision.encryption_version))


def attachment_query(operation):
    return select(MessageAttachment).join(MessageRevision).join(StoredMessage).outerjoin(TransferAttachment, and_(
        TransferAttachment.attachment_uuid == MessageAttachment.uuid,
        TransferAttachment.operation_uuid == operation.uuid)).where(
        StoredMessage.owner_id == operation.owner_id, StoredMessage.account_user_id == operation.account_user_id,
        or_(TransferAttachment.attachment_uuid.is_(None),
            TransferAttachment.original_state_version != MessageAttachment.state_version))


def avatar_query(operation):
    return select(ChatAvatar).outerjoin(TransferAttachment, and_(
        TransferAttachment.attachment_uuid == ChatAvatar.uuid,
        TransferAttachment.operation_uuid == operation.uuid)).where(
        ChatAvatar.owner_id == operation.owner_id, ChatAvatar.account_user_id == operation.account_user_id,
        or_(TransferAttachment.attachment_uuid.is_(None),
            TransferAttachment.original_state_version != ChatAvatar.state_version))


async def locked_transfer(session, operation_id, run_token):
    operation = await session.get(AccountOperation, operation_id)
    if operation is None:
        return None
    await lock_account(session, operation.account_user_id)
    await session.refresh(operation)
    if operation.status != "preparing" or operation.run_token != run_token:
        return None
    account = await unique_account(session, operation.account_user_id)
    profile = await session.get(TelegramApp, operation.target_app_uuid)
    if (account is None or account.uuid != operation.account_uuid or account.admin_id != operation.owner_id
            or profile is None or profile.user_id != operation.actor_id):
        raise PermissionError("Account ownership or API profile changed during transfer")
    for owner_id in sorted({operation.owner_id, operation.actor_id}):
        await lock_owner(session, owner_id)
    return operation


async def prepare_batch(session_factory, operation_id, run_token, private_key, store, *, batch_size=100):
    """Return True when a final publish may be attempted; originals remain intact."""
    async with session_factory()() as session, session.begin():
        operation = await locked_transfer(session, operation_id, run_token)
        if operation is None:
            return None
        target_key = await session.get(OwnerArchiveKey, operation.actor_id)
        if target_key is None:
            raise PermissionError("Destination personal key is missing")
        revisions = (await session.scalars(revision_query(operation).order_by(MessageRevision.uuid).limit(batch_size))).all()
        for revision in revisions:
            plain = (open_text(private_key, revision.payload, context(operation.owner_id, f"revision:{revision.uuid}"))
                     if revision.encryption_version == 2 else decrypt_text(revision.payload))
            if revision.encryption_version not in {1, 2}:
                raise ValueError("Unsupported archive encryption")
            payload = json.loads(plain)
            staged = TransferRevision(operation_uuid=operation.uuid, revision_uuid=revision.uuid,
                original_payload=revision.payload, original_version=revision.encryption_version,
                payload=seal_text(target_key.public_key, plain, context(operation.actor_id, f"revision:{revision.uuid}")),
                fingerprint=personal_fingerprint(operation.actor_id, comparable_payload(payload)))
            await session.merge(staged)
        attachment = await session.scalar(attachment_query(operation).order_by(MessageAttachment.uuid).limit(1))
        if attachment is not None:
            # A finish or an expired lease changes state_version and invalidates its stage.
            if attachment.status == "downloading" and (attachment.lease_until or 0) > int(time.time()):
                return False
            raw_sources = (open_text(private_key, attachment.sources,
                           context(operation.owner_id, f"sources:{attachment.uuid}"))
                           if attachment.sources_encryption_version == 2 else decrypt_text(attachment.sources))
            staged = TransferAttachment(operation_uuid=operation.uuid, attachment_uuid=attachment.uuid,
                original_snapshot=attachment.model_dump_json(), original_state_version=attachment.state_version,
                sources=attachment.sources, sources_encryption_version=attachment.sources_encryption_version,
                file_key=message_fingerprint(f"transferred:{operation.actor_id}:{attachment.file_key}"),
                encryption_version=attachment.encryption_version)
            if attachment.status == "stored":
                staged.blob_key, staged.stored_size = await run_blocking(store.transfer_blob,
                    operation.owner_id, operation.actor_id, attachment.blob_key, private_key, target_key.public_key)
                staged.encryption_version = 2
                staged.sources = seal_text(target_key.public_key, raw_sources,
                                           context(operation.actor_id, f"sources:{attachment.uuid}"))
                staged.sources_encryption_version = 2
            # Pending download locators must remain readable by the media worker.
            elif attachment.sources_encryption_version == 2:
                raise ValueError("Unavailable media has personally sealed download locators")
            await session.merge(staged)
        avatar = await session.scalar(avatar_query(operation).order_by(ChatAvatar.uuid).limit(1)) if attachment is None else None
        if avatar is not None:
            if avatar.status == "downloading" and avatar.lease_until > int(time.time()):
                return False
            staged = TransferAttachment(operation_uuid=operation.uuid, attachment_uuid=avatar.uuid,
                original_snapshot=avatar.model_dump_json(), original_state_version=avatar.state_version,
                sources=avatar.file_id or "", file_key=avatar.photo_key,
                encryption_version=2, sources_encryption_version=1)
            if avatar.status == "stored":
                staged.blob_key, staged.stored_size = await run_blocking(store.transfer_blob,
                    operation.owner_id, operation.actor_id, avatar.blob_key, private_key, target_key.public_key)
            await session.merge(staged)
        await session.flush()
        return not revisions and attachment is None and avatar is None


async def _merge_message_metadata(session, source, target):
    """A returning owner may already have metadata or an earlier archive of this ID."""
    from sqlalchemy import func

    offset = await session.scalar(select(func.coalesce(func.max(MessageRevision.revision_no), 0)).where(
        MessageRevision.message_uuid == target.uuid))
    await session.execute(update(MessageRevision).where(MessageRevision.message_uuid == source.uuid).values(
        message_uuid=target.uuid, revision_no=MessageRevision.revision_no + offset))
    existing = aliased(MessageReceipt)
    await session.execute(delete(MessageReceipt).where(MessageReceipt.message_uuid == source.uuid,
        exists(select(existing.uuid).where(existing.message_uuid == target.uuid,
            existing.source == MessageReceipt.source, existing.event_key == MessageReceipt.event_key))))
    await session.execute(update(MessageReceipt).where(MessageReceipt.message_uuid == source.uuid).values(message_uuid=target.uuid))
    await session.execute(update(PendingMessageDeletion).where(PendingMessageDeletion.resolved_message_uuid == source.uuid).values(
        resolved_message_uuid=target.uuid))
    target.first_seen_at = min(target.first_seen_at, source.first_seen_at)
    target.original_seen |= source.original_seen
    target.is_edited |= source.is_edited
    target.is_deleted |= source.is_deleted
    if source.deleted_observed_at:
        target.deleted_observed_at = min(target.deleted_observed_at or source.deleted_observed_at, source.deleted_observed_at)
    if source.latest_revision_uuid and (target.latest_version_at is None or
                                       (source.latest_version_at or 0) >= target.latest_version_at):
        target.latest_revision_uuid, target.latest_version_at = source.latest_revision_uuid, source.latest_version_at
    target.sent_at = target.sent_at if target.sent_at is not None else source.sent_at
    target.sender_id = target.sender_id if target.sender_id is not None else source.sender_id
    await session.delete(source)
    await session.flush()


async def publish(session_factory, operation_id, run_token):
    async with session_factory()() as session, session.begin():
        operation = await locked_transfer(session, operation_id, run_token)
        if operation is None:
            return None
        if (await session.scalar(revision_query(operation).limit(1))
                or await session.scalar(attachment_query(operation).limit(1))
                or await session.scalar(avatar_query(operation).limit(1))):
            return False
        source_ids = select(StoredMessage.uuid).where(StoredMessage.owner_id == operation.owner_id,
            StoredMessage.account_user_id == operation.account_user_id)
        source_revisions = select(MessageRevision.uuid).where(MessageRevision.message_uuid.in_(source_ids))
        if await session.scalar(select(exists().where(MessageAttachment.revision_uuid.in_(source_revisions),
                MessageAttachment.status == "downloading", MessageAttachment.lease_until > int(time.time())))):
            return False
        revision_stage = select(TransferRevision).where(TransferRevision.operation_uuid == operation.uuid).subquery()
        await session.execute(update(MessageRevision).where(MessageRevision.uuid.in_(select(revision_stage.c.revision_uuid))).values(
            payload=select(revision_stage.c.payload).where(revision_stage.c.revision_uuid == MessageRevision.uuid).scalar_subquery(),
            fingerprint=select(revision_stage.c.fingerprint).where(revision_stage.c.revision_uuid == MessageRevision.uuid).scalar_subquery(),
            encryption_version=2))
        # Each original blob may still be referenced by another account of this owner.
        for blob_key in await session.scalars(select(MessageAttachment.blob_key).where(
                MessageAttachment.revision_uuid.in_(source_revisions), MessageAttachment.blob_key.is_not(None)).distinct()):
            await queue_blob_cleanup(session, operation.owner_id, blob_key)
        stage = select(TransferAttachment).where(TransferAttachment.operation_uuid == operation.uuid).subquery()
        values = {field: select(getattr(stage.c, field)).where(stage.c.attachment_uuid == MessageAttachment.uuid).scalar_subquery()
                  for field in ("sources", "file_key", "blob_key", "stored_size", "encryption_version", "sources_encryption_version")}
        values.update(owner_id=operation.actor_id, lease_token=None, lease_until=0,
                      state_version=MessageAttachment.state_version + 1)
        await session.execute(update(MessageAttachment).where(MessageAttachment.uuid.in_(select(stage.c.attachment_uuid))).values(**values))
        await session.execute(update(MessageAttachment).where(MessageAttachment.uuid.in_(select(stage.c.attachment_uuid)),
            MessageAttachment.status == "downloading").values(status="pending"))
        for avatar in (await session.scalars(select(ChatAvatar).where(ChatAvatar.owner_id == operation.owner_id,
                ChatAvatar.account_user_id == operation.account_user_id))).all():
            staged = await session.get(TransferAttachment, (operation.uuid, avatar.uuid))
            destination = await session.scalar(select(ChatAvatar).where(ChatAvatar.owner_id == operation.actor_id,
                ChatAvatar.account_user_id == avatar.account_user_id, ChatAvatar.user_id == avatar.user_id))
            await queue_blob_cleanup(session, operation.owner_id, avatar.blob_key)
            if destination is not None:
                await queue_blob_cleanup(session, operation.actor_id, destination.blob_key)
                await session.delete(destination)
                await session.flush()
            avatar.owner_id, avatar.blob_key = operation.actor_id, staged.blob_key
            avatar.lease_token, avatar.lease_until = None, 0
            avatar.state_version += 1
            if avatar.status == "downloading":
                avatar.status = "pending"
        target = aliased(StoredMessage)
        while True:
            collisions = (await session.execute(select(StoredMessage, target).join(target, and_(
                target.owner_id == operation.actor_id, target.account_user_id == StoredMessage.account_user_id,
                target.chat_id == StoredMessage.chat_id, target.message_id == StoredMessage.message_id)).where(
                StoredMessage.owner_id == operation.owner_id, StoredMessage.account_user_id == operation.account_user_id).limit(100))).all()
            if not collisions:
                break
            for source, destination in collisions:
                await _merge_message_metadata(session, source, destination)
        await session.execute(update(StoredMessage).where(StoredMessage.owner_id == operation.owner_id,
            StoredMessage.account_user_id == operation.account_user_id).values(owner_id=operation.actor_id))
        # Pending deletions also outlive missing chats/messages; keep their observations.
        for pending in (await session.scalars(select(PendingMessageDeletion).where(
                PendingMessageDeletion.owner_id == operation.owner_id,
                PendingMessageDeletion.account_user_id == operation.account_user_id))).all():
            other = await session.scalar(select(PendingMessageDeletion).where(
                PendingMessageDeletion.owner_id == operation.actor_id, PendingMessageDeletion.account_user_id == operation.account_user_id,
                PendingMessageDeletion.message_id == pending.message_id))
            if other:
                other.observed_at = min(other.observed_at, pending.observed_at)
                other.resolved_message_uuid = other.resolved_message_uuid or pending.resolved_message_uuid
                await session.delete(pending)
            else:
                pending.owner_id = operation.actor_id
        account = await session.get(Account, operation.account_uuid)
        account.admin_id, account.app_tg = operation.actor_id, operation.target_app_uuid
        account.alert_new_chat_id = account.alert_del_chat_id = operation.actor_id
        account.alert_black_list_id = operation.actor_id
        await session.execute(update(HistoryUser).where(HistoryUser.admin_id == operation.owner_id,
            HistoryUser.account_user_id == operation.account_user_id).values(admin_id=operation.actor_id))
        await session.execute(update(AccountHealth).where(AccountHealth.account_uuid == account.uuid).values(admin_id=operation.actor_id))
        operation.status, operation.active_account_id = "activating", None
        operation.updated_at, operation.last_error = int(time.time()), None
        operation.owner_notified = operation.result_notified = False
        await session.execute(delete(TransferAttachment).where(TransferAttachment.operation_uuid == operation.uuid))
        await session.execute(delete(TransferRevision).where(TransferRevision.operation_uuid == operation.uuid))
        return True
