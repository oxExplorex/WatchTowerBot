from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.repositories.accounts_repo import AccountsRepository
from db.repositories.settings_repo import SettingsRepository
from db.repositories.users_repo import UsersRepository


class UnitOfWork:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        admin_id_list: list[int],
        normalize_timezone_offset,
    ):
        self._session_factory = session_factory
        self._admin_id_list = admin_id_list
        self._normalize_timezone_offset = normalize_timezone_offset
        self._session_cm = None
        self.session: AsyncSession | None = None

        self.accounts: AccountsRepository | None = None
        self.settings: SettingsRepository | None = None
        self.users: UsersRepository | None = None

    @asynccontextmanager
    async def _shared_session_scope(self) -> AsyncIterator[AsyncSession]:
        if self.session is None:
            raise RuntimeError("UnitOfWork session is not initialized")
        yield self.session

    async def __aenter__(self) -> "UnitOfWork":
        self._session_cm = self._session_factory()
        self.session = await self._session_cm.__aenter__()

        self.accounts = AccountsRepository(self._shared_session_scope, autocommit=False)
        self.settings = SettingsRepository(
            self._shared_session_scope,
            admin_id_list=self._admin_id_list,
            normalize_timezone_offset=self._normalize_timezone_offset,
            autocommit=False,
        )
        self.users = UsersRepository(self._shared_session_scope, self._admin_id_list, autocommit=False)
        return self

    async def commit(self) -> None:
        if self.session is not None:
            await self.session.commit()

    async def rollback(self) -> None:
        if self.session is not None:
            await self.session.rollback()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if exc_type is None:
                await self.commit()
            else:
                await self.rollback()
        finally:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(exc_type, exc, tb)
            self._session_cm = None
            self.session = None
