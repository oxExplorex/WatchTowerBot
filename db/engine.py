from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import asyncpg

import data.config as config


def _cfg(name: str, default: Any = None) -> Any:
    return getattr(config, name, default)


def normalize_engine_name(engine: str) -> str:
    value = (engine or "").lower().strip()
    if value in {"postgres", "postgresql", "psql", "postgresql+asyncpg"}:
        return "postgresql+asyncpg"
    if value in {"sqlite", "sqlite+aiosqlite"}:
        return "sqlite+aiosqlite"
    return value


@dataclass(frozen=True)
class DatabaseSettings:
    engine: str
    name: str
    user: str
    password: str
    host: str
    port: int
    path: str
    admin_name: str

    @property
    def normalized_engine(self) -> str:
        return normalize_engine_name(self.engine)

    @property
    def connection_string(self) -> str:
        if self.normalized_engine == "sqlite+aiosqlite":
            return f"{self.normalized_engine}:///{self.path}"
        return (
            f"{self.normalized_engine}://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


def load_database_settings() -> DatabaseSettings:
    return DatabaseSettings(
        engine=os.getenv("BOT_DB_ENGINE", _cfg("db_http", "postgres")),
        name=os.getenv("BOT_DB_NAME", _cfg("database_name", _cfg("db", "gemini_message_manager"))),
        user=os.getenv("BOT_DB_USER", _cfg("user", "postgres")),
        password=os.getenv("BOT_DB_PASSWORD", _cfg("password", "postgres")),
        host=os.getenv("BOT_DB_HOST", _cfg("host", "localhost")),
        port=int(os.getenv("BOT_DB_PORT", str(_cfg("port", 5432)))),
        path=os.getenv("BOT_DB_PATH", _cfg("database_path", "data/gemini_message_manager.sqlite3")),
        admin_name=os.getenv("BOT_DB_ADMIN_NAME", _cfg("database_admin_name", "postgres")),
    )


async def ensure_database_exists(settings: DatabaseSettings) -> None:
    if settings.normalized_engine != "postgresql+asyncpg":
        return

    connection = None
    admin_db_candidates = [settings.admin_name, "postgres", "template1"]

    for admin_db in admin_db_candidates:
        try:
            connection = await asyncpg.connect(
                user=settings.user,
                password=settings.password,
                host=settings.host,
                port=settings.port,
                database=admin_db,
            )
            break
        except Exception:
            connection = None

    if connection is None:
        raise RuntimeError("Cannot connect to PostgreSQL admin database to ensure target database exists")

    try:
        # noinspection SqlNoDataSourceInspection
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", settings.name)
        if not exists:
            safe_db_name = settings.name.replace('"', '""')
            # noinspection SqlNoDataSourceInspection
            await connection.execute(f'CREATE DATABASE "{safe_db_name}"')
    finally:
        await connection.close()
