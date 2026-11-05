import time

from sqlalchemy import case, delete, select

from db.repositories.base import conflict_insert
from db.runtime_health_models import RuntimeHealth

SAMPLE_SECONDS = 300
RETENTION_SECONDS = 30 * 86400


class RuntimeHealthRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def record(self, observations, *, now=None):
        now = int(time.time()) if now is None else int(now)
        async with self._session_factory()() as session, session.begin():
            for component, owner_id, expected, available in observations:
                if component not in {"bot", "userbot"} or not 0 <= available <= expected:
                    raise ValueError("Invalid runtime observation")
                status = 0 if not expected else 1 if available == expected else 2 if available else 3
                insert = conflict_insert(session, RuntimeHealth).values(
                    component=component, owner_id=owner_id, bucket_at=now // SAMPLE_SECONDS * SAMPLE_SECONDS,
                    observed_at=now, status=status, expected=expected, available=available)
                await session.execute(insert.on_conflict_do_update(
                    index_elements=["component", "owner_id", "bucket_at"],
                    set_={"status": case((RuntimeHealth.status > status, RuntimeHealth.status), else_=status),
                          "observed_at": now, "expected": expected, "available": available}))
            await session.execute(delete(RuntimeHealth).where(RuntimeHealth.bucket_at < now - RETENTION_SECONDS))

    async def get(self, owner_id, since):
        async with self._session_factory()() as session:
            return list(await session.scalars(select(RuntimeHealth).where(
                RuntimeHealth.bucket_at >= since,
                ((RuntimeHealth.component == "bot") & (RuntimeHealth.owner_id == 0)) |
                ((RuntimeHealth.component == "userbot") & (RuntimeHealth.owner_id == owner_id))
            ).order_by(RuntimeHealth.bucket_at)))
