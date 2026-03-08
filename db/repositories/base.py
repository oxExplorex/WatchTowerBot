from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class SessionLease:
    session: AsyncSession
    owns_session: bool


class BaseRepository:
    def __init__(self, session_scope: Callable, autocommit: bool = True):
        self._session_scope = session_scope
        self._autocommit = autocommit

    @asynccontextmanager
    async def _session(self, session: AsyncSession | None = None) -> AsyncIterator[SessionLease]:
        if session is not None:
            yield SessionLease(session=session, owns_session=False)
            return

        async with self._session_scope() as managed_session:
            yield SessionLease(session=managed_session, owns_session=True)

    async def _commit(self, session: AsyncSession, owns_session: bool) -> None:
        if self._autocommit and owns_session:
            await session.commit()
