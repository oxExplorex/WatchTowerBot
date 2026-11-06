import time

from sqlalchemy import case, exists, or_, select, union, update

from db.chat_policy_models import ArchiveChatPolicy
from db.avatar_models import ChatAvatar
from db.message_models import StoredMessage
from db.models import DumpChatUser, HistoryUser
from db.repositories.account_locks import lock_account, unique_account
from db.repositories.base import conflict_insert
from utils.archive_policy import IGNORED_CHAT_IDS, chat_kind


async def observe_policies(session, account_user_id, observations):
    unique = {chat_id: kind for chat_id, kind in observations if chat_id not in IGNORED_CHAT_IDS}
    values = [dict(account_user_id=account_user_id, chat_id=chat_id, kind=kind) for chat_id, kind in unique.items()]
    forbidden = {chat_id for chat_id, kind in unique.items() if kind in {"bot", "channel", "group", "supergroup"}}
    known = set(await session.scalars(select(ArchiveChatPolicy.chat_id).where(
        ArchiveChatPolicy.account_user_id == account_user_id, ArchiveChatPolicy.chat_id.in_(forbidden),
        ArchiveChatPolicy.kind.in_({"bot", "channel", "group", "supergroup"})))) if forbidden else set()
    for offset in range(0, len(values), 100):
        insert = conflict_insert(session, ArchiveChatPolicy).values(values[offset:offset + 100])
        await session.execute(insert.on_conflict_do_update(index_elements=["account_user_id", "chat_id"], set_={
            # A Bot API private-chat object cannot turn a known Telegram bot into a human.
            "kind": case((ArchiveChatPolicy.kind == "bot", "bot"), else_=insert.excluded.kind), "retry_at": 0}))
    return bool(forbidden - known)


class ChatPolicyRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def observe(self, account_user_id, chats):
        observations = [(chat.id, chat_kind(chat)) for chat in chats
                        if getattr(chat, "id", None) is not None]
        async with self._session_factory()() as session, session.begin():
            changed = await observe_policies(session, account_user_id, observations)
        if changed:
            await self._purge()

    async def excluded_ids(self, account_user_id):
        async with self._session_factory()() as session:
            return set(await session.scalars(select(ArchiveChatPolicy.chat_id).where(
                ArchiveChatPolicy.account_user_id == account_user_id, ArchiveChatPolicy.kind != "private")))

    async def remember(self, account_user_id, chat_id, kind):
        async with self._session_factory()() as session, session.begin():
            changed = await observe_policies(session, account_user_id, [(chat_id, kind)])
        if changed:
            await self._purge()

    async def _purge(self):
        from db.repositories.ignored_chats_repo import purge_ignored_chats

        await purge_ignored_chats(self._session_factory)

    async def claim_unknown(self, account, *, limit=50):
        """Claim legacy positive IDs; absence from Telegram's dialogs proves no type."""
        now = int(time.time())
        async with self._session_factory()() as session, session.begin():
            await lock_account(session, account.user_id)
            current = await unique_account(session, account.user_id)
            if current is None or not current.is_active or current.admin_id != account.admin_id:
                return []
            candidates = union(
                select(StoredMessage.chat_id.label("chat_id")).where(StoredMessage.account_user_id == account.user_id),
                select(DumpChatUser.chat_id).where(DumpChatUser.admin_id == account.user_id),
                select(ChatAvatar.user_id).where(ChatAvatar.account_user_id == account.user_id),
                select(HistoryUser.chat_id).where(or_(HistoryUser.account_user_id == account.user_id,
                    HistoryUser.account_user_id.is_(None) & (HistoryUser.admin_id == account.admin_id)))).subquery()
            known = exists().where(ArchiveChatPolicy.account_user_id == account.user_id,
                ArchiveChatPolicy.chat_id == candidates.c.chat_id,
                or_(ArchiveChatPolicy.kind != "unresolved", ArchiveChatPolicy.retry_at > now))
            peers = list(await session.scalars(select(candidates.c.chat_id).where(
                candidates.c.chat_id > 0, candidates.c.chat_id.not_in(IGNORED_CHAT_IDS), ~known)
                .order_by(candidates.c.chat_id).limit(limit)))
            if peers:
                insert = conflict_insert(session, ArchiveChatPolicy).values([
                    dict(account_user_id=account.user_id, chat_id=peer, kind="unresolved", retry_at=now + 120)
                    for peer in peers])
                await session.execute(insert.on_conflict_do_update(index_elements=["account_user_id", "chat_id"],
                    set_={"retry_at": now + 120}, where=ArchiveChatPolicy.kind == "unresolved"))
            return peers

    async def defer_unknown(self, account_id, peers, delay=3600):
        async with self._session_factory()() as session, session.begin():
            await session.execute(update(ArchiveChatPolicy).where(ArchiveChatPolicy.account_user_id == account_id,
                ArchiveChatPolicy.chat_id.in_(peers), ArchiveChatPolicy.kind == "unresolved"
            ).values(retry_at=int(time.time()) + max(120, delay)))
