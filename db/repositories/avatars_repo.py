import time
from uuid import uuid4
from sqlalchemy import and_, exists, or_, select, update

from db.avatar_models import ChatAvatar
from db.account_operation_models import AccountOperation
from db.repositories.personal_repo import lock_owner
from db.repositories.account_locks import lock_account, unique_account
from utils.crypto_store import encrypt_text, message_fingerprint


class AvatarsRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def observe(self, owner_id, account_id, peers, *, source="userbot", require_account=False):
        """Use photos already present in updates/dialogs; never fetch profiles here."""
        photos = {}
        for peer in peers:
            user_id, photo = getattr(peer, "id", None), getattr(peer, "photo", None)
            file_id = getattr(photo, "small_file_id", None)
            unique = getattr(photo, "small_photo_unique_id", None) or getattr(photo, "small_file_unique_id", None)
            if type(user_id) is int and user_id > 0 and isinstance(file_id, str):
                photos[user_id] = (file_id, message_fingerprint(f"avatar:{unique or file_id}"))
        if not photos:
            return
        async with self._session_factory()() as session, session.begin():
            await lock_account(session, account_id)
            if require_account:
                account = await unique_account(session, account_id)
                if account is None or account.admin_id != owner_id or not account.is_active:
                    return
            if await lock_owner(session, owner_id) is None:
                return  # Avatars are never stored using legacy encryption.
            if await session.scalar(select(exists().where(AccountOperation.active_account_id == account_id,
                    AccountOperation.status.in_({"preparing", "activating", "deleting", "removing_session"})))):
                return
            existing = {row.user_id: row for row in await session.scalars(select(ChatAvatar).where(
                ChatAvatar.owner_id == owner_id, ChatAvatar.account_user_id == account_id,
                ChatAvatar.user_id.in_(photos)))}
            for user_id, (file_id, photo_key) in photos.items():
                row = existing.get(user_id)
                if row is None:
                    row = ChatAvatar(owner_id=owner_id, account_user_id=account_id, user_id=user_id, photo_key=photo_key)
                    session.add(row)
                elif row.photo_key == photo_key and row.status == "stored":
                    continue
                elif row.photo_key != photo_key:
                    from db.repositories.account_operations_repo import queue_blob_cleanup
                    await queue_blob_cleanup(session, owner_id, row.blob_key)
                    row.blob_key, row.status = None, "pending"
                    row.lease_token, row.lease_until = None, 0
                    row.next_attempt_at = 0
                    row.state_version += 1
                row.photo_key, row.source, row.file_id = photo_key, source, encrypt_text(file_id)
                row.updated_at = int(time.time())

    async def claim(self):
        now = int(time.time())
        available = or_(and_(ChatAvatar.status == "pending", ChatAvatar.next_attempt_at <= now),
                        and_(ChatAvatar.status == "downloading", ChatAvatar.lease_until <= now))
        changing = exists().where(AccountOperation.active_account_id == ChatAvatar.account_user_id,
            AccountOperation.status.in_({"preparing", "activating", "deleting", "removing_session"}))
        async with self._session_factory()() as session, session.begin():
            item = await session.scalar(select(ChatAvatar).where(available, ~changing).order_by(
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
