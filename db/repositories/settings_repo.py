from __future__ import annotations

import time
from typing import Any

import data.text as constant_text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from db.models import AccountHealth, User, VersionState
from db.repositories.base import BaseRepository, SessionLease


class SettingsRepository(BaseRepository):
    def __init__(
        self,
        session_scope,
        admin_id_list: list[int],
        normalize_timezone_offset,
        autocommit: bool = True,
    ):
        super().__init__(session_scope, autocommit=autocommit)
        self._admin_id_list = set(int(x) for x in admin_id_list)
        self._normalize_timezone_offset = normalize_timezone_offset

    def _admin_role(self, user_id: int) -> str | None:
        return "admin" if int(user_id) in self._admin_id_list else None

    async def _get_user(self, session: AsyncSession, user_id: int) -> User | None:
        result = await session.execute(select(User).where(col(User.user_id) == int(user_id)))
        return result.scalars().first()

    async def _get_or_create_user(self, session: AsyncSession, user_id: int) -> User:
        user = await self._get_user(session, user_id)
        if user:
            return user

        user = User(
            user_id=int(user_id),
            roles=self._admin_role(user_id),
            timezone_offset=3,
        )
        session.add(user)
        return user

    async def _persist_user(self, lease: SessionLease, user: User, refresh: bool = False) -> None:
        lease.session.add(user)
        await self._commit(lease.session, lease.owns_session)
        if refresh and lease.owns_session:
            await lease.session.refresh(user)

    @staticmethod
    def _proxy_config_from_user(user: User) -> dict[str, Any]:
        return {
            "proxy": (user.gemini_proxy or "").strip() or None,
            "enabled": int(getattr(user, "gemini_proxy_enabled", 0) or 0),
            "status": int(getattr(user, "gemini_proxy_status", 0) or 0),
            "checked_at": int(getattr(user, "gemini_proxy_checked_at", 0) or 0),
            "last_error": getattr(user, "gemini_proxy_last_error", None) or None,
        }

    async def get_version_state_cache(
        self,
        default_state: str = constant_text.VERSION_STATE_UNKNOWN,
        session: AsyncSession | None = None,
    ) -> tuple[str, int, str | None]:
        async with self._session(session) as lease:
            result = await lease.session.execute(select(VersionState).where(col(VersionState.id) == 1))
            row = result.scalars().first()
            if not row:
                return default_state, 0, None
            return (
                str(getattr(row, "state", default_state) or default_state),
                int(getattr(row, "checked_at", 0) or 0),
                getattr(row, "remote_version", None),
            )

    async def set_version_state_cache(
        self,
        local_version: str,
        remote_version: str | None,
        state: str,
        checked_at: int | None = None,
        session: AsyncSession | None = None,
    ) -> int:
        checked_at_value = int(checked_at if checked_at is not None else time.time())

        async with self._session(session) as lease:
            result = await lease.session.execute(select(VersionState).where(col(VersionState.id) == 1))
            row = result.scalars().first()
            if not row:
                row = VersionState(
                    id=1,
                    local_version=str(local_version),
                    remote_version=str(remote_version) if remote_version else None,
                    state=str(state),
                    checked_at=checked_at_value,
                )
            else:
                row.local_version = str(local_version)
                row.remote_version = str(remote_version) if remote_version else None
                row.state = str(state)
                row.checked_at = checked_at_value

            lease.session.add(row)
            await self._commit(lease.session, lease.owns_session)
            return checked_at_value

    async def get_user_timezone_offset(
        self,
        user_id: int,
        default: int = 3,
        session: AsyncSession | None = None,
    ) -> int:
        async with self._session(session) as lease:
            user = await self._get_user(lease.session, user_id)
            if not user:
                return self._normalize_timezone_offset(default, default)
            return self._normalize_timezone_offset(getattr(user, "timezone_offset", default), default)

    async def set_user_timezone_offset(
        self,
        user_id: int,
        offset: int,
        session: AsyncSession | None = None,
    ) -> int:
        value = self._normalize_timezone_offset(offset, 3)
        async with self._session(session) as lease:
            user = await self._get_or_create_user(lease.session, user_id)
            user.timezone_offset = value
            await self._persist_user(lease, user)
            return value

    async def get_user_auto_update_enabled(
        self,
        user_id: int,
        default: int = 0,
        session: AsyncSession | None = None,
    ) -> int:
        async with self._session(session) as lease:
            user = await self._get_user(lease.session, user_id)
            if not user:
                return int(default)
            return int(getattr(user, "auto_update_enabled", default) or 0)

    async def set_user_auto_update_enabled(
        self,
        user_id: int,
        enabled: int,
        session: AsyncSession | None = None,
    ) -> int:
        value = 1 if int(enabled) else 0
        async with self._session(session) as lease:
            user = await self._get_or_create_user(lease.session, user_id)
            user.auto_update_enabled = value
            await self._persist_user(lease, user)
            return value

    async def get_user_update_notification_state(
        self,
        user_id: int,
        session: AsyncSession | None = None,
    ) -> tuple[int, int]:
        async with self._session(session) as lease:
            user = await self._get_user(lease.session, user_id)
            if not user:
                return 0, 0
            return (
                int(getattr(user, "update_snooze_until", 0) or 0),
                int(getattr(user, "update_last_notified", 0) or 0),
            )

    async def set_user_update_snooze_until(
        self,
        user_id: int,
        until_ts: int,
        session: AsyncSession | None = None,
    ) -> int:
        value = int(until_ts)
        async with self._session(session) as lease:
            user = await self._get_or_create_user(lease.session, user_id)
            user.update_snooze_until = value
            await self._persist_user(lease, user)
            return value

    async def set_user_update_last_notified(
        self,
        user_id: int,
        ts_value: int,
        session: AsyncSession | None = None,
    ) -> int:
        value = int(ts_value)
        async with self._session(session) as lease:
            user = await self._get_or_create_user(lease.session, user_id)
            user.update_last_notified = value
            await self._persist_user(lease, user)
            return value

    async def get_user_gemini_proxy_config(
        self,
        user_id: int,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        async with self._session(session) as lease:
            user = await self._get_user(lease.session, user_id)
            if not user:
                return {"proxy": None, "enabled": 0, "status": 0, "checked_at": 0, "last_error": None}
            return self._proxy_config_from_user(user)

    async def set_user_gemini_proxy(
        self,
        user_id: int,
        proxy_value: str,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        proxy_clean = (proxy_value or "").strip()
        async with self._session(session) as lease:
            user = await self._get_or_create_user(lease.session, user_id)
            user.gemini_proxy = proxy_clean
            user.gemini_proxy_enabled = 1
            user.gemini_proxy_status = 0
            user.gemini_proxy_checked_at = int(time.time())
            user.gemini_proxy_last_error = None
            await self._persist_user(lease, user, refresh=True)
            return self._proxy_config_from_user(user)

    async def disable_user_gemini_proxy(
        self,
        user_id: int,
        reason: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        async with self._session(session) as lease:
            user = await self._get_or_create_user(lease.session, user_id)
            user.gemini_proxy_enabled = 0
            user.gemini_proxy_status = 0
            user.gemini_proxy_checked_at = int(time.time())
            user.gemini_proxy_last_error = reason or None
            await self._persist_user(lease, user, refresh=True)
            return self._proxy_config_from_user(user)

    async def set_user_gemini_proxy_health(
        self,
        user_id: int,
        is_ok: bool,
        error: str | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        async with self._session(session) as lease:
            user = await self._get_or_create_user(lease.session, user_id)
            user.gemini_proxy_status = 1 if is_ok else 0
            user.gemini_proxy_checked_at = int(time.time())
            user.gemini_proxy_last_error = None if is_ok else (error or "proxy_check_failed")
            await self._persist_user(lease, user, refresh=True)
            return self._proxy_config_from_user(user)

    async def get_latest_admin_health_event(
        self,
        admin_id: int,
        session: AsyncSession | None = None,
    ):
        async with self._session(session) as lease:
            result = await lease.session.execute(
                select(AccountHealth)
                .where(col(AccountHealth.admin_id) == int(admin_id))
                .order_by(col(AccountHealth.date).desc())
                .limit(1)
            )
            return result.scalars().first()
