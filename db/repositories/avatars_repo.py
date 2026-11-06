import time
from uuid import uuid4
from sqlalchemy import and_, exists, or_, select, update

from db.avatar_models import AvatarHistoryScan, ChatAvatar
from db.account_operation_models import AccountOperation
from db.chat_policy_models import ArchiveChatPolicy
from db.repositories.personal_repo import lock_owner
from db.repositories.account_locks import lock_account, unique_account
from utils.crypto_store import encrypt_text, message_fingerprint
from utils.archive_policy import IGNORED_CHAT_IDS, chat_kind


class AvatarsRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    @staticmethod
    async def _allowed(session, owner_id, account_id, require_account):
        await lock_account(session, account_id)
        if require_account:
            account = await unique_account(session, account_id)
            if account is None or account.admin_id != owner_id or not account.is_active:
                return False
        if await lock_owner(session, owner_id) is None:
            return False
        return not await session.scalar(select(exists().where(AccountOperation.active_account_id == account_id,
            AccountOperation.status.in_({"preparing", "activating", "deleting", "removing_session"}))))

    async def observe(self, owner_id, account_id, peers, *, source="userbot", require_account=False, authoritative=False):
        """Use photos already present in updates/dialogs; never fetch profiles here."""
        photos = {}
        for peer in peers:
            user_id, photo = getattr(peer, "id", None), getattr(peer, "photo", None)
            if user_id in IGNORED_CHAT_IDS or chat_kind(peer) in {"bot", "channel"}:
                continue
            file_id = getattr(photo, "small_file_id", None)
            unique = getattr(photo, "small_photo_unique_id", None) or getattr(photo, "small_file_unique_id", None)
            if type(user_id) is int and user_id > 0 and isinstance(file_id, str):
                photos[user_id] = (file_id, message_fingerprint(f"avatar:{unique or file_id}"))
            elif authoritative and type(user_id) is int and user_id > 0 and photo is None:
                photos[user_id] = (None, "absent")
        if not photos:
            return
        async with self._session_factory()() as session, session.begin():
            if not await self._allowed(session, owner_id, account_id, require_account):
                return
            existing = {row.user_id: row for row in await session.scalars(select(ChatAvatar).where(
                ChatAvatar.owner_id == owner_id, ChatAvatar.account_user_id == account_id,
                ChatAvatar.user_id.in_(photos), ChatAvatar.ended_at.is_(None)))}
            for user_id, (file_id, photo_key) in photos.items():
                row = existing.get(user_id)
                now = time.time_ns() // 1000
                if row is not None and row.photo_key == photo_key and row.status in {"stored", "absent"}:
                    continue
                if row is not None and row.photo_key != photo_key:
                    row.ended_at = max(now, row.first_seen_at)
                    row.state_version += 1
                    await session.flush()  # Free the single-current-occurrence index before inserting.
                    row = None
                if row is None:
                    row = ChatAvatar(owner_id=owner_id, account_user_id=account_id, user_id=user_id,
                                     photo_key=photo_key, first_seen_at=now)
                    session.add(row)
                    # Reusing bytes is safe; the occurrence remains a separate record.
                    cached = await session.scalar(select(ChatAvatar).where(ChatAvatar.owner_id == owner_id,
                        ChatAvatar.photo_key == photo_key, ChatAvatar.status == "stored").limit(1)) if file_id else None
                    if cached is not None:
                        row.blob_key, row.status = cached.blob_key, "stored"
                row.source = source
                if file_id and row.status == "unavailable":
                    row.status, row.next_attempt_at = "pending", 0
                    row.state_version += 1
                row.file_id = encrypt_text(file_id) if file_id and row.status != "stored" else None
                if file_id is None:
                    row.status = "absent"
                row.updated_at = int(time.time())

    async def claim_history(self, owner_id, account_id, chat, *, require_account=True):
        if chat.id in IGNORED_CHAT_IDS or chat_kind(chat) != "private":
            return None
        photo = getattr(chat, "photo", None)
        unique = getattr(photo, "small_photo_unique_id", None) or getattr(photo, "small_file_id", None)
        head = message_fingerprint(f"avatar:{unique}") if unique else "absent"
        now = int(time.time())
        async with self._session_factory()() as session, session.begin():
            if not await self._allowed(session, owner_id, account_id, require_account):
                return None
            row = await session.get(AvatarHistoryScan, (owner_id, account_id, chat.id), with_for_update=True)
            if row is None:
                row = AvatarHistoryScan(owner_id=owner_id, account_user_id=account_id, user_id=chat.id, head_key=head)
                session.add(row)
            elif row.next_attempt_at > now and row.lease_token is not None:
                return None
            elif row.head_key != head:
                row.head_key, row.next_limit, row.next_attempt_at = head, 20, 0
            if row.next_attempt_at > now:
                return None
            row.lease_token, row.next_attempt_at = uuid4(), now + 120
            await session.flush()
            return row

    async def finish_history(self, progress, photos, *, observed_count, delay=None):
        now = int(time.time())
        async with self._session_factory()() as session, session.begin():
            if not await self._allowed(session, progress.owner_id, progress.account_user_id, True):
                return
            row = await session.get(AvatarHistoryScan, (progress.owner_id, progress.account_user_id, progress.user_id),
                                    with_for_update=True)
            if row is None or row.lease_token != progress.lease_token:
                return
            existing = set(await session.scalars(select(ChatAvatar.photo_key).where(
                ChatAvatar.owner_id == row.owner_id, ChatAvatar.account_user_id == row.account_user_id,
                ChatAvatar.user_id == row.user_id)))
            for photo in photos:
                unique = getattr(photo, "small_photo_unique_id", None) or getattr(photo, "small_file_id", None)
                file_id = getattr(photo, "small_file_id", None)
                if not unique or not file_id:
                    continue
                key = message_fingerprint(f"avatar:{unique}")
                if key in existing:
                    continue
                observed = time.time_ns() // 1000
                item = ChatAvatar(owner_id=row.owner_id, account_user_id=row.account_user_id,
                    user_id=row.user_id, photo_key=key, file_id=encrypt_text(file_id), source="userbot",
                    first_seen_at=observed, ended_at=observed, updated_at=now)
                cached = await session.scalar(select(ChatAvatar).where(ChatAvatar.owner_id == row.owner_id,
                    ChatAvatar.photo_key == key, ChatAvatar.status == "stored").limit(1))
                if cached is not None:
                    item.blob_key, item.status, item.file_id = cached.blob_key, "stored", None
                session.add(item)
                existing.add(key)
            row.lease_token = None
            if delay is not None:
                row.next_attempt_at = now + max(30, delay)
            elif observed_count >= row.next_limit:
                row.next_limit += 20
                row.next_attempt_at = now + 20 * 60
            else:
                row.next_attempt_at = now + 24 * 60 * 60

    async def claim(self, *, account_id=None, owner_id=None):
        now = int(time.time())
        available = or_(and_(ChatAvatar.status == "pending", ChatAvatar.next_attempt_at <= now),
                        and_(ChatAvatar.status == "downloading", ChatAvatar.lease_until <= now))
        changing = exists().where(AccountOperation.active_account_id == ChatAvatar.account_user_id,
            AccountOperation.status.in_({"preparing", "activating", "deleting", "removing_session"}))
        async with self._session_factory()() as session, session.begin():
            query = select(ChatAvatar).where(available, ~changing,
                ChatAvatar.user_id.not_in(IGNORED_CHAT_IDS), ~exists().where(
                    ArchiveChatPolicy.account_user_id == ChatAvatar.account_user_id,
                    ArchiveChatPolicy.chat_id == ChatAvatar.user_id, ArchiveChatPolicy.kind != "private"))
            if account_id is not None:
                query = query.where(ChatAvatar.account_user_id == account_id)
            if owner_id is not None:
                query = query.where(ChatAvatar.owner_id == owner_id)
            item = await session.scalar(query.order_by(
                ChatAvatar.next_attempt_at, ChatAvatar.uuid).limit(1))
            if item is None or await lock_owner(session, item.owner_id) is None:
                return None
            result = await session.execute(update(ChatAvatar).where(ChatAvatar.uuid == item.uuid,
                ChatAvatar.owner_id == item.owner_id, available, ~changing).values(
                status="downloading", lease_token=uuid4(), lease_until=now + 660,
                state_version=ChatAvatar.state_version + 1).returning(ChatAvatar).execution_options(populate_existing=True))
            return result.scalar_one_or_none()

    async def finish(self, item, *, blob_key=None, delay=0):
        async with self._session_factory()() as session, session.begin():
            await lock_owner(session, item.owner_id)
            row = await session.scalar(select(ChatAvatar).where(ChatAvatar.uuid == item.uuid,
                ChatAvatar.owner_id == item.owner_id, ChatAvatar.lease_token == item.lease_token).with_for_update())
            if row is None:
                if blob_key:
                    from db.repositories.account_operations_repo import queue_blob_cleanup
                    await queue_blob_cleanup(session, item.owner_id, blob_key)
                return
            row.lease_token, row.lease_until = None, 0
            row.state_version += 1
            if blob_key:
                row.blob_key, row.status, row.file_id = blob_key, "stored", None
            else:
                row.status, row.next_attempt_at = "pending", int(time.time()) + max(30, delay)
