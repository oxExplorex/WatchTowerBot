from __future__ import annotations

from db.engine import DatabaseSettings, ensure_database_exists


async def ensure_postgres_database_exists(settings: DatabaseSettings) -> None:
    # Backward-compatible shim for old imports.
    await ensure_database_exists(settings)


async def apply_bootstrap(*_args, **_kwargs) -> None:
    # Legacy no-op: schema changes are handled by Alembic migrations.
    return None
