from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
DOTENV_PATH = ROOT_DIR / ".env"

# Load local .env once. Existing system env vars have priority.
load_dotenv(dotenv_path=DOTENV_PATH, override=False)


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _env_int_list(name: str, default: list[int] | None = None) -> list[int]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return list(default or [])

    result: list[int] = []
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        try:
            result.append(int(token))
        except ValueError:
            continue
    return result


TOKEN_BOT = _env_str("TOKEN_BOT", "")
GEMINI_KEY = _env_str("GEMINI_KEY", "")

# Database connection
user = _env_str("DB_USER", "postgres")
password = _env_str("DB_PASSWORD", "postgres")
database_name = _env_str("DB_NAME", "gemini_message_manager")
database_admin_name = _env_str("DB_ADMIN_NAME", "postgres")
host = _env_str("DB_HOST", "localhost")
port = _env_int("DB_PORT", 5432)

# SQLAlchemy driver for SQLModel
# PostgreSQL recommended: postgresql+asyncpg
# SQLite: sqlite+aiosqlite
# Also supported via env in db/main.py: BOT_DB_ENGINE
# If not set, this value is used.
db_http = _env_str("DB_ENGINE", "postgresql+asyncpg")

# Optional for sqlite engine
# If DB_ENGINE=sqlite+aiosqlite and BOT_DB_PATH is not set, this path can be used by db/main.py fallback.
database_path = _env_str("DB_PATH", "data/gemini_message_manager.sqlite3")

# Admin Telegram user IDs (comma-separated in .env)
# Example: ADMIN_ID_LIST=123456789,987654321
admin_id_list = _env_int_list("ADMIN_ID_LIST", default=[])

# Logs path
path_logs = _env_str("LOG_PATH", "data/logs/log_{d}.log")