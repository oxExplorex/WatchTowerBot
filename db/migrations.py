from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from core.logging import bot_logger
from db.engine import DatabaseSettings, load_database_settings

_APP_TABLES = {
    "username_history_db",
    "user_db",
    "app_tg_db",
    "apps_db",
    "history_users_db",
    "dump_chat_user_db",
    "account_health_db",
    "version_state_db",
}
_BASELINE_REVISION = "20260308_01"
_MIGRATIONS_DONE = False
_MIGRATIONS_LOCK = asyncio.Lock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _build_alembic_config(connection_string: str) -> Config:
    root = _project_root()
    ini_path = root / "alembic.ini"
    script_path = root / "migrations"
    if not ini_path.exists():
        raise FileNotFoundError(f"Alembic config file not found: {ini_path}")
    if not script_path.exists():
        raise FileNotFoundError(f"Alembic script directory not found: {script_path}")

    config = Config(str(ini_path))
    config.set_main_option("script_location", str(script_path))
    config.set_main_option("sqlalchemy.url", connection_string)
    return config


def _upgrade_head(config: Config) -> None:
    command.upgrade(config, "head")


def _stamp_baseline(config: Config) -> None:
    command.stamp(config, _BASELINE_REVISION)


async def _has_table(connection_string: str, table_name: str) -> bool:
    engine = create_async_engine(connection_string, echo=False, future=True)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(table_name))
    finally:
        await engine.dispose()


async def _has_any_app_table(connection_string: str) -> bool:
    engine = create_async_engine(connection_string, echo=False, future=True)
    try:
        async with engine.connect() as conn:
            table_names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
            return bool(_APP_TABLES.intersection(table_names))
    finally:
        await engine.dispose()


async def run_db_migrations(db_settings: DatabaseSettings | None = None) -> None:
    global _MIGRATIONS_DONE
    async with _MIGRATIONS_LOCK:
        if _MIGRATIONS_DONE:
            return

        settings = db_settings or load_database_settings()
        connection_string = settings.connection_string
        config = _build_alembic_config(connection_string)

        has_version_table = await _has_table(connection_string, "alembic_version")
        if not has_version_table and await _has_any_app_table(connection_string):
            await asyncio.to_thread(_stamp_baseline, config)
            bot_logger.info(f"Alembic: stamped existing schema to baseline {_BASELINE_REVISION}")

        await asyncio.to_thread(_upgrade_head, config)
        _MIGRATIONS_DONE = True
