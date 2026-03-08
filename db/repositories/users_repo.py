from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import User
from db.repositories.base import BaseRepository


class UsersRepository(BaseRepository):
    def __init__(
        self,
        session_scope: Callable,
        admin_id_list: list[int],
        autocommit: bool = True,
    ):
        super().__init__(session_scope, autocommit=autocommit)
        self._admin_id_list = set(int(x) for x in admin_id_list)

    def _admin_role(self, user_id: int) -> str | None:
        return "admin" if int(user_id) in self._admin_id_list else None

    async def _fetch_user(self, session: AsyncSession, user_id: int) -> User | None:
        result = await session.execute(select(User).where(col(User.user_id) == int(user_id)))
        return result.scalars().first()

    async def get_user(self, user_id: int, session: AsyncSession | None = None) -> User | None:
        async with self._session(session) as lease:
            return await self._fetch_user(lease.session, user_id)

    async def update_user(
        self,
        user_id: int,
        username: str | None,
        full_name: str | None,
        session: AsyncSession | None = None,
    ) -> None:
        async with self._session(session) as lease:
            user = await self._fetch_user(lease.session, user_id)
            roles = self._admin_role(user_id)

            if not user:
                user = User(user_id=int(user_id), roles=roles, timezone_offset=3)
                lease.session.add(user)

            if user.roles != roles or user.username != username or user.full_name != full_name:
                user.username = username
                user.full_name = full_name
                user.roles = roles

            if user.timezone_offset is None:
                user.timezone_offset = 3

            await self._commit(lease.session, lease.owns_session)

    async def delete_user(self, user_id: int, session: AsyncSession | None = None) -> None:
        async with self._session(session) as lease:
            user = await self._fetch_user(lease.session, user_id)
            if user:
                await lease.session.delete(user)
                await self._commit(lease.session, lease.owns_session)

    async def get_admins(self, session: AsyncSession | None = None) -> list[User]:
        async with self._session(session) as lease:
            result = await lease.session.execute(select(User).where(col(User.roles) == "admin"))
            return result.scalars().all()

