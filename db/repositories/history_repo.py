import time

from sqlalchemy import case, delete, exists, func, select, update

from db.account_operation_models import AccountOperation
from db.history_models import HistoryChat, HistoryRange, HistoryRun, TelegramCooldown
from db.message_models import MessageRevision, StoredMessage
from db.models import Account, DumpChatUser
from db.personal_models import OwnerArchiveKey
from db.repositories.account_locks import lock_account, unique_account
from db.repositories.base import conflict_insert
from services.history_windows import merge_ranges
from utils.archive_policy import IGNORED_CHAT_IDS
from db.chat_policy_models import ArchiveChatPolicy

HISTORY_INTERVAL = 20 * 60
HISTORY_CHAT_LIMIT = 10
HISTORY_PAGE_SIZE = 200


class HistoryRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    @staticmethod
    async def _active(session, account_uuid):
        account = await session.get(Account, account_uuid)
        if account is None or not account.is_active or not account.admin_id or not account.user_id:
            return None
        await lock_account(session, account.user_id)
        current = await unique_account(session, account.user_id)
        if current is None or current.uuid != account_uuid or not current.is_active:
            return None
        if await session.get(OwnerArchiveKey, current.admin_id) is None:
            return None
        if await session.scalar(select(exists().where(
                AccountOperation.active_account_id == current.user_id,
                AccountOperation.status.in_({"preparing", "activating", "deleting", "removing_session"})))):
            return None
        return current

    async def blocked_until(self, account_user_id):
        async with self._session_factory()() as session:
            row = await session.get(TelegramCooldown, account_user_id)
            return row.blocked_until if row else 0

    async def defer(self, account_user_id, seconds):
        until = int(time.time()) + max(1, int(seconds))
        async with self._session_factory()() as session, session.begin():
            insert = conflict_insert(session, TelegramCooldown).values(account_user_id=account_user_id, blocked_until=until)
            await session.execute(insert.on_conflict_do_update(index_elements=["account_user_id"], set_={
                "blocked_until": case((TelegramCooldown.blocked_until > until, TelegramCooldown.blocked_until), else_=until)}))

    async def media_slot(self, account_user_id, interval=30):
        now = int(time.time())
        async with self._session_factory()() as session, session.begin():
            await session.execute(conflict_insert(session, TelegramCooldown).values(account_user_id=account_user_id)
                                  .on_conflict_do_nothing(index_elements=["account_user_id"]))
            result = await session.execute(update(TelegramCooldown).where(
                TelegramCooldown.account_user_id == account_user_id,
                TelegramCooldown.blocked_until <= now, TelegramCooldown.media_next_at <= now
            ).values(media_next_at=now + interval).returning(TelegramCooldown.account_user_id))
            if result.scalar_one_or_none() is not None:
                return 0
            row = await session.get(TelegramCooldown, account_user_id)
            return max(1, row.blocked_until - now, row.media_next_at - now)

    async def claim(self, account_uuid, *, now=None):
        now = int(time.time()) if now is None else now
        async with self._session_factory()() as session, session.begin():
            account = await self._active(session, account_uuid)
            if account is None:
                return None
            cooldown = await session.get(TelegramCooldown, account.user_id)
            if cooldown and cooldown.blocked_until > now:
                return None
            await session.execute(conflict_insert(session, HistoryRun).values(
                account_uuid=account.uuid, account_user_id=account.user_id
            ).on_conflict_do_nothing(index_elements=["account_uuid"]))
            claimed = await session.execute(update(HistoryRun).where(
                HistoryRun.account_uuid == account.uuid, HistoryRun.next_run_at <= now
            ).values(next_run_at=now + HISTORY_INTERVAL).returning(HistoryRun.account_uuid))
            return account if claimed.scalar_one_or_none() is not None else None

    async def seed(self, account, bot_id):
        from core.logging import bot_logger

        async with self._session_factory()() as session, session.begin():
            heads = dict((await session.execute(select(StoredMessage.chat_id, func.max(StoredMessage.message_id)).where(
                StoredMessage.owner_id == account.admin_id, StoredMessage.account_user_id == account.user_id,
                StoredMessage.chat_id > 0, StoredMessage.chat_id != bot_id,
                StoredMessage.chat_id.not_in(IGNORED_CHAT_IDS)
            ).group_by(StoredMessage.chat_id))).all())
            dump_chats = set(await session.scalars(select(DumpChatUser.chat_id).where(
                DumpChatUser.admin_id == account.user_id, DumpChatUser.chat_id > 0, DumpChatUser.chat_id != bot_id,
                DumpChatUser.chat_id.not_in(IGNORED_CHAT_IDS))))
            excluded = set(await session.scalars(select(ArchiveChatPolicy.chat_id).where(
                ArchiveChatPolicy.account_user_id == account.user_id, ArchiveChatPolicy.kind != "private")))
            chats = (dump_chats | heads.keys()) - excluded
            bot_logger.debug("History seed: account_uuid=%s owner_id=%s account_user_id=%s dump_admin_id=%s dump_chats=%s stored_chats=%s",
                account.uuid, account.admin_id, account.user_id, account.user_id, len(dump_chats), len(heads))
            await self._observe(session, account.uuid, {chat: heads.get(chat, 0) for chat in chats}, source="seed")

    @staticmethod
    async def _observe(session, account_uuid, heads, *, source):
        from core.logging import bot_logger

        items = [(chat, top) for chat, top in heads.items() if chat not in IGNORED_CHAT_IDS]
        for offset in range(0, len(items), 100):
            values = [dict(account_uuid=account_uuid, chat_id=chat, known_top_id=top)
                      for chat, top in items[offset:offset + 100]]
            if not values:
                continue
            insert = conflict_insert(session, HistoryChat).values(values)
            await session.execute(insert.on_conflict_do_update(index_elements=["account_uuid", "chat_id"], set_={
                "known_top_id": case((HistoryChat.known_top_id > insert.excluded.known_top_id, HistoryChat.known_top_id),
                                     else_=insert.excluded.known_top_id)}))
        bot_logger.debug("History targets: account_uuid=%s source=%s chats=%s", account_uuid, source, len(items))

    async def observe_heads(self, account_uuid, heads):
        async with self._session_factory()() as session, session.begin():
            await self._observe(session, account_uuid, heads, source="dialogs")

    async def due_chats(self, account_uuid, *, now=None):
        now = int(time.time()) if now is None else now
        async with self._session_factory()() as session:
            # Keep old/unvisited chats ahead of recent ones; shuffle equal scan
            # intervals so neither Telegram recency nor numeric IDs select the batch.
            last_attempt_interval = HistoryChat.last_attempt_at // HISTORY_INTERVAL
            return list(await session.scalars(select(HistoryChat).where(
                HistoryChat.account_uuid == account_uuid, HistoryChat.excluded == False, HistoryChat.retry_at <= now,
                HistoryChat.chat_id.not_in(IGNORED_CHAT_IDS), ~exists().where(
                    ArchiveChatPolicy.account_user_id == select(HistoryRun.account_user_id).where(
                        HistoryRun.account_uuid == account_uuid).scalar_subquery(),
                    ArchiveChatPolicy.chat_id == HistoryChat.chat_id, ArchiveChatPolicy.kind != "private")
            ).order_by(last_attempt_interval, func.random()).limit(HISTORY_CHAT_LIMIT)))

    async def ranges(self, account_uuid, chat_id):
        async with self._session_factory()() as session:
            return list((await session.execute(select(HistoryRange.low_id, HistoryRange.high_id).where(
                HistoryRange.account_uuid == account_uuid, HistoryRange.chat_id == chat_id))).all())

    async def attempt(self, progress, *, error=None, delay=0, excluded=False):
        now = int(time.time())
        async with self._session_factory()() as session, session.begin():
            await session.execute(update(HistoryChat).where(
                HistoryChat.account_uuid == progress.account_uuid, HistoryChat.chat_id == progress.chat_id
            ).values(last_attempt_at=now, retry_at=now + delay, last_error=error, excluded=excluded))

    async def checkpoint(self, progress, window, raw_ids, saved_ids, started_at):
        if len(raw_ids) > HISTORY_PAGE_SIZE or len(raw_ids) != len(set(raw_ids)) or not set(saved_ids) <= set(raw_ids):
            raise ValueError("Invalid history page identities")
        if any(identity < window.low_id or (window.high_id is not None and identity > window.high_id) for identity in raw_ids):
            raise ValueError("History page exceeds window")
        now = int(time.time())
        async with self._session_factory()() as session, session.begin():
            account = await self._active(session, progress.account_uuid)
            if account is None:
                return False
            row = await session.get(HistoryChat, (progress.account_uuid, progress.chat_id), with_for_update=True)
            if row is None:
                return False
            upper = window.high_id if window.high_id is not None else max(raw_ids, default=row.known_top_id)
            lower = min(raw_ids) if raw_ids else window.low_id
            if raw_ids:
                row.known_top_id = max(row.known_top_id, max(raw_ids))
            if window.low_id == 1 and (not raw_ids or min(raw_ids) == 1):
                row.reached_start = True
            if saved_ids:
                row.oldest_message_id = min(min(saved_ids), row.oldest_message_id or min(saved_ids))
            if upper >= lower:
                ranges = list((await session.execute(select(HistoryRange.low_id, HistoryRange.high_id).where(
                    HistoryRange.account_uuid == row.account_uuid, HistoryRange.chat_id == row.chat_id))).all())
                ranges = merge_ranges([*ranges, (lower, upper)])
                await session.execute(delete(HistoryRange).where(
                    HistoryRange.account_uuid == row.account_uuid, HistoryRange.chat_id == row.chat_id))
                session.add_all([HistoryRange(account_uuid=row.account_uuid, chat_id=row.chat_id, low_id=low, high_id=high)
                                 for low, high in ranges])
                # Only previously observed messages in this exact chat qualify.
                # IDs never observed here may belong to completely different DMs.
                changed_during_fetch = exists(select(MessageRevision.uuid).where(
                    MessageRevision.message_uuid == StoredMessage.uuid, MessageRevision.observed_at >= started_at))
                await session.execute(update(StoredMessage).where(
                    StoredMessage.owner_id == account.admin_id, StoredMessage.account_user_id == account.user_id,
                    StoredMessage.chat_id == row.chat_id, StoredMessage.message_id.between(lower, upper),
                    StoredMessage.message_id.not_in(saved_ids), StoredMessage.first_seen_at < started_at,
                    StoredMessage.is_deleted == False, ~changed_during_fetch
                ).values(history_missing_at=now))
            row.turn += 1
            row.last_attempt_at, row.last_error, row.retry_at = now, None, 0
            if window.high_id is None:
                row.last_head_at = now
            return True
