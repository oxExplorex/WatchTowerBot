"""Erase one owner's account archive inside the disconnection transaction."""
import time

from sqlalchemy import delete, exists, func, select, update

from db.history_models import HistoryChat, HistoryRange, HistoryRun, TelegramCooldown
from db.media_models import MessageAttachment
from db.message_models import MessageReceipt, MessageRevision, PendingMessageDeletion, StoredMessage
from db.models import Account, AccountHealth, DumpChatUser, HistoryUser
from db.repositories.personal_repo import lock_owner


async def erase_account_archive(session, operation):
    from db.repositories.account_operations_repo import queue_blob_cleanup

    owner, account = operation.owner_id, operation.account_user_id
    await lock_owner(session, owner)
    messages = select(StoredMessage.uuid).where(StoredMessage.owner_id == owner, StoredMessage.account_user_id == account)
    revisions = select(MessageRevision.uuid).where(MessageRevision.message_uuid.in_(messages))
    attachments = MessageAttachment.revision_uuid.in_(revisions)
    # A downloader writes files outside the DB transaction; wait for its lease.
    if await session.scalar(select(exists().where(attachments,
            MessageAttachment.status == "downloading", MessageAttachment.lease_until > int(time.time())))):
        return False
    chats = list(await session.scalars(
        select(StoredMessage.chat_id).where(StoredMessage.uuid.in_(messages)).union(
            select(HistoryUser.chat_id).where(HistoryUser.admin_id == owner, HistoryUser.account_user_id == account),
            select(HistoryChat.chat_id).where(HistoryChat.account_uuid == operation.account_uuid))))
    for blob in await session.scalars(select(MessageAttachment.blob_key).where(attachments)):
        await queue_blob_cleanup(session, owner, blob)
    await session.execute(delete(MessageAttachment).where(attachments))
    await session.execute(delete(MessageReceipt).where(MessageReceipt.message_uuid.in_(messages)))
    await session.execute(delete(PendingMessageDeletion).where(
        PendingMessageDeletion.owner_id == owner, PendingMessageDeletion.account_user_id == account))
    await session.execute(update(PendingMessageDeletion).where(
        PendingMessageDeletion.resolved_message_uuid.in_(messages)).values(resolved_message_uuid=None))
    await session.execute(delete(MessageRevision).where(MessageRevision.message_uuid.in_(messages)))
    await session.execute(delete(StoredMessage).where(StoredMessage.uuid.in_(messages)))
    await session.execute(delete(HistoryUser).where(HistoryUser.admin_id == owner, HistoryUser.account_user_id == account))
    await session.execute(delete(AccountHealth).where(AccountHealth.admin_id == owner, AccountHealth.user_id == account))
    for model in (HistoryRange, HistoryChat, HistoryRun):
        await session.execute(delete(model).where(model.account_uuid == operation.account_uuid))
    await session.execute(delete(TelegramCooldown).where(TelegramCooldown.account_user_id == account))
    # Membership rows are shared across an owner's accounts. Keep shared chats
    # and old events whose account cannot be identified rather than deleting them.
    for offset in range(0, len(chats), 500):
        await session.execute(delete(DumpChatUser).where(
            DumpChatUser.admin_id == owner, DumpChatUser.chat_id.in_(chats[offset:offset + 500]),
            ~exists().where(StoredMessage.owner_id == owner, StoredMessage.chat_id == DumpChatUser.chat_id),
            ~exists().where(HistoryUser.admin_id == owner,
                func.coalesce(HistoryUser.chat_id, HistoryUser.user_id) == DumpChatUser.chat_id),
            ~exists(select(HistoryChat.chat_id).join(Account, Account.uuid == HistoryChat.account_uuid).where(
                Account.admin_id == owner, Account.uuid != operation.account_uuid,
                HistoryChat.chat_id == DumpChatUser.chat_id))))
    return True
