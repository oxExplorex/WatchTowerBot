import hashlib
import time

from sqlalchemy import BigInteger, func, literal, select, update

from db.personal_models import OwnerArchiveKey


async def lock_owner(session, owner_id):
    """Serialize enabling keys, message writes and migration, including absent keys."""
    if session.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(f"archive-owner:{owner_id}".encode()).digest()[:8], "big", signed=True)
        await session.execute(select(func.pg_advisory_xact_lock(literal(key, type_=BigInteger))))
    else:
        # Even when no row matches, this starts a SQLite write transaction before
        # reading the key. FOR UPDATE alone cannot lock an absent SQLite row.
        await session.execute(update(OwnerArchiveKey).where(OwnerArchiveKey.owner_id == owner_id).values(owner_id=owner_id))
    return await session.get(OwnerArchiveKey, owner_id)


class PersonalKeyRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def get(self, owner_id):
        async with self._session_factory()() as session:
            return await session.get(OwnerArchiveKey, owner_id)

    async def install(self, owner_id, bundle):
        async with self._session_factory()() as session, session.begin():
            if await lock_owner(session, owner_id) is not None:
                return False
            session.add(OwnerArchiveKey(owner_id=owner_id, created_at=int(time.time()), **bundle))
            return True

    async def owners(self):
        async with self._session_factory()() as session:
            return list((await session.scalars(select(OwnerArchiveKey.owner_id).where(
                OwnerArchiveKey.migration_state != "complete"))).all())
