import time

from sqlalchemy import delete, func, select, text

from db.admin_models import AdminGrant
from db.repositories.base import conflict_insert


def telegram_user_id(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**63:
        raise ValueError("Invalid Telegram user ID")
    return value


class AdminsRepository:
    def __init__(self, session_factory, configured_ids):
        self._session_factory = session_factory
        self.configured_ids = frozenset(int(value) for value in configured_ids if int(value) > 0)

    async def get_ids(self) -> set[int]:
        async with self._session_factory()() as session:
            return set(self.configured_ids) | set(await session.scalars(select(AdminGrant.user_id)))

    async def is_admin(self, user_id: int) -> bool:
        telegram_user_id(user_id)
        if user_id in self.configured_ids:
            return True
        async with self._session_factory()() as session:
            return await session.get(AdminGrant, user_id) is not None

    async def get_grants(self) -> list[AdminGrant]:
        async with self._session_factory()() as session:
            return list(await session.scalars(select(AdminGrant).order_by(AdminGrant.created_at, AdminGrant.user_id)))

    @staticmethod
    async def _lock(session):
        if session.get_bind().dialect.name == "postgresql":
            await session.execute(select(func.pg_advisory_xact_lock(734192004)))
        elif session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))

    def _authorize(self, actor_id):
        telegram_user_id(actor_id)
        if actor_id not in self.configured_ids:
            raise PermissionError("Configured administrator access is required")

    async def grant(self, actor_id: int, user_id: int) -> bool:
        self._authorize(actor_id)
        telegram_user_id(user_id)
        async with self._session_factory()() as session, session.begin():
            await self._lock(session)
            if user_id in self.configured_ids:
                return False
            statement = conflict_insert(session, AdminGrant).values(
                user_id=user_id, granted_by=actor_id, created_at=int(time.time()))
            result = await session.execute(statement.on_conflict_do_nothing(
                index_elements=["user_id"]).returning(AdminGrant.user_id))
            return result.scalar_one_or_none() is not None

    async def revoke(self, actor_id: int, user_id: int) -> bool:
        self._authorize(actor_id)
        telegram_user_id(user_id)
        async with self._session_factory()() as session, session.begin():
            await self._lock(session)
            if user_id in self.configured_ids:
                raise ValueError("Configured administrators cannot be revoked")
            if user_id == actor_id:
                raise ValueError("Self-revocation is not allowed")
            result = await session.execute(delete(AdminGrant).where(
                AdminGrant.user_id == user_id).returning(AdminGrant.user_id))
            return result.scalar_one_or_none() is not None
