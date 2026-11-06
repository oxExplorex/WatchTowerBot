"""Restart-safe removal of forbidden archive data; shared blobs use the GC queue."""
from sqlalchemy import delete, or_, select

from db.account_operation_models import AccountOperation, TransferAttachment, TransferRevision
from db.avatar_models import AvatarHistoryScan, ChatAvatar
from db.chat_policy_models import ArchiveChatPolicy
from db.history_models import HistoryChat, HistoryRange
from db.media_models import MessageAttachment
from db.message_models import MessageReceipt, MessageRevision, PendingMessageDeletion, StoredMessage
from db.models import DumpChatUser, HistoryUser, User, UsernameHistory
from db.repositories.account_locks import lock_account
from db.repositories.account_operations_repo import queue_blob_cleanup
from db.repositories.personal_repo import lock_owner
from utils.archive_policy import IGNORED_CHAT_IDS


def excluded_chat(column):
    # Negative IDs identify groups/channels. A positive ID is deleted only after
    # Telegram has identified it as a bot, never by its name or username suffix.
    classified = select(ArchiveChatPolicy.chat_id).where(
        ArchiveChatPolicy.kind.in_({"bot", "group", "supergroup", "channel"}))
    return or_(column <= 0, column.in_(IGNORED_CHAT_IDS), column.in_(classified))


async def purge_ignored_chats(session_factory):
    removed = 0
    while True:
        async with session_factory()() as session, session.begin():
            messages = list(await session.scalars(select(StoredMessage).where(
                or_(excluded_chat(StoredMessage.chat_id), StoredMessage.channel_namespace))
                .order_by(StoredMessage.uuid).limit(500)))
            if not messages:
                break
            for account_id in sorted({row.account_user_id for row in messages}):
                await lock_account(session, account_id)
            for owner_id in sorted({row.owner_id for row in messages}):
                await lock_owner(session, owner_id)
            identities = [row.uuid for row in messages]
            revisions = select(MessageRevision.uuid).where(MessageRevision.message_uuid.in_(identities))
            attachments = select(MessageAttachment.uuid).where(MessageAttachment.revision_uuid.in_(revisions))
            for owner, blob in await session.execute(select(MessageAttachment.owner_id, MessageAttachment.blob_key)
                    .where(MessageAttachment.uuid.in_(attachments))):
                await queue_blob_cleanup(session, owner, blob)
            for owner, blob in await session.execute(select(AccountOperation.actor_id, TransferAttachment.blob_key)
                    .join(TransferAttachment, TransferAttachment.operation_uuid == AccountOperation.uuid)
                    .where(TransferAttachment.attachment_uuid.in_(attachments))):
                await queue_blob_cleanup(session, owner, blob)
            await session.execute(delete(TransferAttachment).where(TransferAttachment.attachment_uuid.in_(attachments)))
            await session.execute(delete(TransferRevision).where(TransferRevision.revision_uuid.in_(revisions)))
            await session.execute(delete(PendingMessageDeletion).where(PendingMessageDeletion.resolved_message_uuid.in_(identities)))
            await session.execute(delete(MessageReceipt).where(MessageReceipt.message_uuid.in_(identities)))
            await session.execute(delete(MessageAttachment).where(MessageAttachment.revision_uuid.in_(revisions)))
            await session.execute(delete(MessageRevision).where(MessageRevision.message_uuid.in_(identities)))
            await session.execute(delete(StoredMessage).where(StoredMessage.uuid.in_(identities)))
            removed += len(messages)
    async with session_factory()() as session, session.begin():
        avatars = select(ChatAvatar.uuid).where(excluded_chat(ChatAvatar.user_id))
        for owner, blob in await session.execute(select(ChatAvatar.owner_id, ChatAvatar.blob_key).where(
                ChatAvatar.uuid.in_(avatars))):
            await queue_blob_cleanup(session, owner, blob)
        for owner, blob in await session.execute(select(AccountOperation.actor_id, TransferAttachment.blob_key)
                .join(TransferAttachment, TransferAttachment.operation_uuid == AccountOperation.uuid)
                .where(TransferAttachment.attachment_uuid.in_(avatars))):
            await queue_blob_cleanup(session, owner, blob)
        await session.execute(delete(TransferAttachment).where(TransferAttachment.attachment_uuid.in_(avatars)))
        await session.execute(delete(ChatAvatar).where(excluded_chat(ChatAvatar.user_id)))
        await session.execute(delete(AvatarHistoryScan).where(excluded_chat(AvatarHistoryScan.user_id)))
        await session.execute(delete(HistoryRange).where(excluded_chat(HistoryRange.chat_id)))
        await session.execute(delete(HistoryChat).where(excluded_chat(HistoryChat.chat_id)))
        await session.execute(delete(DumpChatUser).where(excluded_chat(DumpChatUser.chat_id)))
        await session.execute(delete(HistoryUser).where(or_(excluded_chat(HistoryUser.chat_id),
            HistoryUser.chat_id.is_(None) & excluded_chat(HistoryUser.user_id))))
        await session.execute(delete(UsernameHistory).where(excluded_chat(UsernameHistory.user_id)))
        await session.execute(delete(User).where(excluded_chat(User.user_id)))
        # Keep minimal bot/type tombstones to reject later partial updates.
        await session.execute(delete(ArchiveChatPolicy).where(ArchiveChatPolicy.chat_id.in_(IGNORED_CHAT_IDS)))
    return removed
