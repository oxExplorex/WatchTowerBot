from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import Account, AccountHealth, DumpChatUser, TelegramApp
from db.repositories.base import BaseRepository, SessionLease


def _to_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class AccountsRepository(BaseRepository):
    def __init__(self, session_scope: Callable, autocommit: bool = True):
        super().__init__(session_scope, autocommit=autocommit)

    async def _save(self, lease: SessionLease, entity: Any, refresh: bool = False) -> None:
        lease.session.add(entity)
        await self._commit(lease.session, lease.owns_session)
        if refresh and lease.owns_session:
            await lease.session.refresh(entity)

    async def get_app_tg_user_id(
        self,
        user_id: int,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> tuple[list[TelegramApp], int]:
        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(TelegramApp).where(col(TelegramApp.user_id) == user_id).offset(offset).limit(5)
            )
            count_result = await lease.session.execute(
                select(func.count()).select_from(TelegramApp).where(col(TelegramApp.user_id) == user_id)
            )
            return result.scalars().all(), int(count_result.scalar() or 0)

    async def get_app_tg_uuid(
        self,
        uuid: Any,
        user_id: int,
        session: AsyncSession | None = None,
    ) -> TelegramApp | None:
        uuid_value = _to_uuid(uuid)
        if uuid_value is None:
            return None

        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(TelegramApp).where(col(TelegramApp.uuid) == uuid_value, col(TelegramApp.user_id) == user_id)
            )
            return result.scalars().first()

    async def get_app_tg_uuid_aio(self, uuid: Any, session: AsyncSession | None = None) -> TelegramApp | None:
        uuid_value = _to_uuid(uuid)
        if uuid_value is None:
            return None

        async with self._session(session) as lease:
            result = await lease.session.execute(select(TelegramApp).where(col(TelegramApp.uuid) == uuid_value))
            return result.scalars().first()

    async def get_accounts_count_by_app_tg_uuid(
        self,
        app_tg_uuid: Any,
        session: AsyncSession | None = None,
    ) -> int:
        uuid_value = _to_uuid(app_tg_uuid)
        if uuid_value is None:
            return 0

        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(func.count()).select_from(Account).where(col(Account.app_tg) == uuid_value)
            )
            return int(result.scalar() or 0)

    async def del_app_tg_uuid(self, uuid: Any, user_id: int, session: AsyncSession | None = None) -> bool:
        uuid_value = _to_uuid(uuid)
        if uuid_value is None:
            return False

        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(TelegramApp).where(col(TelegramApp.uuid) == uuid_value, col(TelegramApp.user_id) == user_id)
            )
            temp = result.scalars().first()
            if not temp:
                return False

            await lease.session.delete(temp)
            await self._commit(lease.session, lease.owns_session)
            return True

    async def get_app_tg_to_params_all(
        self,
        user_id: int,
        app_id: int,
        api_hash: str,
        session: AsyncSession | None = None,
    ) -> TelegramApp | None:
        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(TelegramApp).where(
                    col(TelegramApp.user_id) == user_id,
                    col(TelegramApp.app_id) == app_id,
                    col(TelegramApp.api_hash) == api_hash,
                )
            )
            return result.scalars().first()

    async def create_app_tg(
        self,
        user_id: int,
        app_id: int,
        api_hash: str,
        tag_name: str | None,
        session: AsyncSession | None = None,
    ) -> None:
        async with self._session(session) as lease:
            await self._save(
                lease,
                TelegramApp(
                    user_id=int(user_id),
                    app_id=int(app_id),
                    api_hash=api_hash,
                    tag_name=tag_name,
                ),
            )

    async def get_account_user_id(
        self,
        admin_id: int,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> tuple[list[Account], int]:
        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(Account).where(col(Account.admin_id) == admin_id).offset(offset).limit(5)
            )
            count_result = await lease.session.execute(
                select(func.count()).select_from(Account).where(col(Account.admin_id) == admin_id)
            )
            return result.scalars().all(), int(count_result.scalar() or 0)

    async def get_account_all(
        self,
        active_only: bool = False,
        session: AsyncSession | None = None,
    ) -> list[Account]:
        async with self._session(session) as lease:
            query = select(Account)
            if active_only:
                query = query.where(col(Account.is_active) == 1)
            result = await lease.session.execute(query)
            return result.scalars().all()

    async def get_account_tg_to_user_id(
        self,
        user_id: int,
        admin_id: int | None = None,
        session: AsyncSession | None = None,
    ) -> Account | None:
        async with self._session(session) as lease:
            query = select(Account).where(col(Account.user_id) == user_id)
            if admin_id is not None:
                query = query.where(col(Account.admin_id) == admin_id)

            result = await lease.session.execute(query)
            return result.scalars().first()

    async def get_account_uuid(self, uuid: Any, admin_id: int, session: AsyncSession | None = None) -> Account | None:
        uuid_value = _to_uuid(uuid)
        if uuid_value is None:
            return None

        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(Account).where(col(Account.uuid) == uuid_value, col(Account.admin_id) == admin_id)
            )
            return result.scalars().first()

    async def del_account_uuid(self, uuid: Any, admin_id: int, session: AsyncSession | None = None) -> bool:
        uuid_value = _to_uuid(uuid)
        if uuid_value is None:
            return False

        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(Account).where(col(Account.uuid) == uuid_value, col(Account.admin_id) == admin_id)
            )
            temp = result.scalars().first()
            if not temp:
                return False

            await lease.session.delete(temp)
            await self._commit(lease.session, lease.owns_session)
            return True

    async def update_account_uuid(
        self,
        uuid: Any,
        admin_id: int,
        session: AsyncSession | None = None,
        **fields: Any,
    ) -> Account | None:
        uuid_value = _to_uuid(uuid)
        if uuid_value is None:
            return None

        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(Account).where(col(Account.uuid) == uuid_value, col(Account.admin_id) == admin_id)
            )
            temp = result.scalars().first()
            if not temp:
                return None

            for key, value in fields.items():
                if hasattr(temp, key):
                    setattr(temp, key, value)

            await self._save(lease, temp, refresh=True)
            return temp

    async def create_account_tg(
        self,
        admin_id: int,
        user_id: int,
        app_tg: Any,
        number: str,
        session: AsyncSession | None = None,
    ) -> Account | None:
        app_tg_uuid = _to_uuid(app_tg)
        if app_tg_uuid is None:
            return None

        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(Account).where(col(Account.admin_id) == admin_id, col(Account.user_id) == user_id)
            )
            account = result.scalars().first()

            if account:
                account.app_tg = app_tg_uuid
                account.number = number
                account.is_active = 1
                if getattr(account, "alert_spoiler_media", None) is None:
                    account.alert_spoiler_media = 1
                await self._save(lease, account, refresh=True)
                return account

            account = Account(
                admin_id=admin_id,
                user_id=user_id,
                app_tg=app_tg_uuid,
                number=number,
                alert_del_chat_id=admin_id,
                alert_new_chat_id=admin_id,
                alert_bot=0,
                alert_spoiler_media=1,
                is_active=1,
            )
            await self._save(lease, account, refresh=True)
            return account

    async def get_dump_chat_admin_all(
        self,
        admin_id: int,
        session: AsyncSession | None = None,
    ) -> list[DumpChatUser]:
        async with self._session(session) as lease:
            result = await lease.session.execute(select(DumpChatUser).where(col(DumpChatUser.admin_id) == admin_id))
            return result.scalars().all()

    async def get_dump_chat_user(
        self,
        admin_id: int,
        chat_id: int,
        session: AsyncSession | None = None,
    ) -> DumpChatUser | None:
        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(DumpChatUser).where(
                    col(DumpChatUser.admin_id) == admin_id,
                    col(DumpChatUser.chat_id) == chat_id,
                )
            )
            return result.scalars().first()

    async def del_dump_chat_user(
        self,
        admin_id: int,
        chat_id: int,
        session: AsyncSession | None = None,
    ) -> bool:
        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(DumpChatUser).where(
                    col(DumpChatUser.admin_id) == admin_id,
                    col(DumpChatUser.chat_id) == chat_id,
                )
            )
            records = result.scalars().all()
            if not records:
                return False

            for item in records:
                await lease.session.delete(item)

            await self._commit(lease.session, lease.owns_session)
            return True

    async def create_dump_chat_user(
        self,
        admin_id: int,
        chat_id: int,
        session: AsyncSession | None = None,
    ) -> bool:
        async with self._session(session) as lease:
            exists = await lease.session.execute(
                select(DumpChatUser).where(
                    col(DumpChatUser.admin_id) == admin_id,
                    col(DumpChatUser.chat_id) == chat_id,
                )
            )
            if exists.scalars().first():
                return False

            await self._save(lease, DumpChatUser(admin_id=int(admin_id), chat_id=int(chat_id)))
            return True

    async def get_account_by_number(self, number: str, session: AsyncSession | None = None) -> Account | None:
        async with self._session(session) as lease:
            result = await lease.session.execute(select(Account).where(col(Account.number) == str(number)))
            return result.scalars().first()

    async def delete_account_by_number(
        self,
        number: str,
        session: AsyncSession | None = None,
    ) -> Account | None:
        async with self._session(session) as lease:
            result = await lease.session.execute(select(Account).where(col(Account.number) == str(number)))
            records = result.scalars().all()
            if not records:
                return None

            account = records[0]
            for item in records:
                await lease.session.delete(item)

            await self._commit(lease.session, lease.owns_session)
            return account

    async def delete_dump_chat_admin_all(self, admin_id: int, session: AsyncSession | None = None) -> int:
        async with self._session(session) as lease:
            result = await lease.session.execute(select(DumpChatUser).where(col(DumpChatUser.admin_id) == admin_id))
            records = result.scalars().all()
            if not records:
                return 0

            for item in records:
                await lease.session.delete(item)

            await self._commit(lease.session, lease.owns_session)
            return len(records)

    async def add_account_health_event(
        self,
        account_uuid: Any,
        admin_id: int | None,
        user_id: int | None,
        status: int,
        date: int | None = None,
        reason: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        account_uuid_value = _to_uuid(account_uuid)
        if account_uuid_value is None:
            return

        async with self._session(session) as lease:
            await self._save(
                lease,
                AccountHealth(
                    account_uuid=account_uuid_value,
                    admin_id=int(admin_id) if admin_id is not None else 0,
                    user_id=int(user_id) if user_id is not None else 0,
                    status=int(status),
                    date=int(date) if date is not None else int(time.time()),
                    reason=reason,
                ),
            )

    async def get_account_health_events(
        self,
        account_uuid: Any,
        since_ts: int,
        session: AsyncSession | None = None,
    ) -> list[AccountHealth]:
        account_uuid_value = _to_uuid(account_uuid)
        if account_uuid_value is None:
            return []

        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(AccountHealth).where(
                    col(AccountHealth.account_uuid) == account_uuid_value,
                    col(AccountHealth.date) >= int(since_ts),
                )
            )
            return result.scalars().all()

    async def get_admin_health_events(
        self,
        admin_id: int,
        since_ts: int,
        session: AsyncSession | None = None,
    ) -> list[AccountHealth]:
        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(AccountHealth).where(
                    col(AccountHealth.admin_id) == int(admin_id),
                    col(AccountHealth.date) >= int(since_ts),
                )
            )
            return result.scalars().all()

    async def get_accounts_overview(self, admin_id: int, session: AsyncSession | None = None) -> dict[str, int]:
        async with self._session(session) as lease:
            own_total_q = await lease.session.execute(
                select(func.count()).select_from(Account).where(col(Account.admin_id) == admin_id)
            )
            own_active_q = await lease.session.execute(
                select(func.count()).select_from(Account).where(col(Account.admin_id) == admin_id, col(Account.is_active) == 1)
            )
            all_total_q = await lease.session.execute(select(func.count()).select_from(Account))
            all_active_q = await lease.session.execute(select(func.count()).select_from(Account).where(col(Account.is_active) == 1))

            return {
                "own_total": int(own_total_q.scalar() or 0),
                "own_active": int(own_active_q.scalar() or 0),
                "all_total": int(all_total_q.scalar() or 0),
                "all_active": int(all_active_q.scalar() or 0),
            }

    async def get_all_health_events(
        self,
        since_ts: int,
        session: AsyncSession | None = None,
    ) -> list[AccountHealth]:
        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(AccountHealth).where(
                    col(AccountHealth.date) >= int(since_ts),
                )
            )
            return result.scalars().all()




