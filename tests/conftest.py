from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest_asyncio


@pytest_asyncio.fixture
async def db_main(tmp_path: Path):
    db_file = tmp_path / "test_db.sqlite3"

    os.environ["BOT_DB_ENGINE"] = "sqlite+aiosqlite"
    os.environ["BOT_DB_PATH"] = str(db_file)
    os.environ["DB_ENCRYPTION_KEY"] = "test-encryption-key"

    for module_name in [
        "db.engine",
        "db.session",
        "db.main",
        "db.migrations",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db.main as db_main_module

    await db_main_module.connect_database()
    try:
        yield db_main_module
    finally:
        await db_main_module.close_database()
