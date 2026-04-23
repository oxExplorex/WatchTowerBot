from __future__ import annotations

import time
from collections.abc import Callable

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import User, UsernameHistory
from db.repositories.base import BaseRepository
from utils.crypto_store import blind_index, decrypt_text, encrypt_text, is_encrypted


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

    def _hydrate_user(self, user: User | None) -> User | None:
        if not user:
            return None
        user.username = decrypt_text(user.username)
        user.full_name = decrypt_text(user.full_name)
        return user

    async def get_user(self, user_id: int, session: AsyncSession | None = None) -> User | None:
        async with self._session(session) as lease:
            user = await self._fetch_user(lease.session, user_id)
            return self._hydrate_user(user)

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

            old_username = decrypt_text(user.username)
            old_full_name = decrypt_text(user.full_name)
            username_idx = blind_index(username)
            needs_username_reencrypt = bool(username) and (
                not is_encrypted(user.username) or user.username_hash != username_idx
            )
            needs_full_name_reencrypt = bool(full_name) and not is_encrypted(user.full_name)
            if (
                user.roles != roles
                or old_username != username
                or old_full_name != full_name
                or needs_username_reencrypt
                or needs_full_name_reencrypt
            ):
                user.username = encrypt_text(username)
                user.full_name = encrypt_text(full_name)
                user.username_hash = username_idx
                user.roles = roles

            normalized_username = (username or "").strip().lstrip("@").lower()
            normalized_old_username = (old_username or "").strip().lstrip("@").lower()
            if normalized_username and normalized_username != normalized_old_username:
                history_idx = blind_index(normalized_username)
                history_payload = {
                    "user_id": int(user_id),
                    "username": encrypt_text(normalized_username),
                    "username_hash": history_idx,
                    "date": int(time.time()),
                }

                bind = lease.session.get_bind()
                dialect_name = bind.dialect.name if bind is not None else ""

                if history_idx and dialect_name == "postgresql":
                    # Conflict-safe insert for concurrent update_user calls.
                    stmt = pg_insert(UsernameHistory).values(**history_payload)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "username_hash"])
                    await lease.session.execute(stmt)
                else:
                    conditions = [func.lower(col(UsernameHistory.username)) == normalized_username]
                    if history_idx:
                        conditions.append(col(UsernameHistory.username_hash) == history_idx)
                    existing = await lease.session.execute(
                        select(UsernameHistory).where(
                            col(UsernameHistory.user_id) == int(user_id),
                            or_(*conditions),
                        )
                    )
                    if not existing.scalars().first():
                        lease.session.add(
                            UsernameHistory(
                                **history_payload,
                            )
                        )

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
            return [self._hydrate_user(item) for item in result.scalars().all()]

    async def get_all_users(self, session: AsyncSession | None = None) -> list[User]:
        async with self._session(session) as lease:
            result = await lease.session.execute(select(User))
            return [self._hydrate_user(item) for item in result.scalars().all()]

    async def backfill_username_history_encryption(self, session: AsyncSession | None = None) -> int:
        async with self._session(session) as lease:
            result = await lease.session.execute(select(UsernameHistory))
            items = result.scalars().all()
            touched = 0
            for item in items:
                value = decrypt_text(item.username)
                idx = blind_index(value)
                should_encrypt = bool(value) and not is_encrypted(item.username)
                should_index = bool(value) and item.username_hash != idx
                if not should_encrypt and not should_index:
                    continue
                item.username = encrypt_text(value)
                item.username_hash = idx
                touched += 1

            if touched:
                await self._commit(lease.session, lease.owns_session)
            return touched

    async def find_user_ids_by_username(
        self,
        username: str,
        session: AsyncSession | None = None,
    ) -> list[int]:
        normalized = (username or "").strip().lstrip("@").lower()
        if not normalized:
            return []
        idx = blind_index(normalized)

        async with self._session(session) as lease:
            user_conditions = [func.lower(col(User.username)) == normalized]
            history_conditions = [func.lower(col(UsernameHistory.username)) == normalized]
            if idx:
                user_conditions.append(col(User.username_hash) == idx)
                history_conditions.append(col(UsernameHistory.username_hash) == idx)

            user_rows = await lease.session.execute(
                select(User.user_id).where(or_(*user_conditions))
            )
            history_rows = await lease.session.execute(
                select(UsernameHistory.user_id).where(or_(*history_conditions))
            )

            values: set[int] = set()
            for item in user_rows:
                if item[0] is not None:
                    values.add(int(item[0]))
            for item in history_rows:
                if item[0] is not None:
                    values.add(int(item[0]))
            return sorted(values)

