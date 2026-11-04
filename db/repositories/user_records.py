"""Shared conflict-safe user creation for profiles and settings."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.repositories.base import conflict_insert


async def get_user_for_update(session: AsyncSession, user_id: int, *, role: str | None = None) -> User:
    statement = conflict_insert(session, User).values(user_id=int(user_id), roles=role, timezone_offset=3)
    await session.execute(statement.on_conflict_do_nothing(index_elements=["user_id"]))
    return (await session.scalars(
        select(User).where(User.user_id == int(user_id)).with_for_update()
    )).one()
