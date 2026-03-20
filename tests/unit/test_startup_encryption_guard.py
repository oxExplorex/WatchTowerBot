from __future__ import annotations

import importlib
import os
import sys

import pytest


@pytest.mark.asyncio
async def test_connect_database_requires_encryption_key(tmp_path):
    db_file = tmp_path / "guard_db.sqlite3"
    os.environ["BOT_DB_ENGINE"] = "sqlite+aiosqlite"
    os.environ["BOT_DB_PATH"] = str(db_file)
    os.environ["DB_ENCRYPTION_KEY"] = ""

    for module_name in ["db.engine", "db.session", "db.main", "db.migrations"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db.main as db_main_module

    with pytest.raises(RuntimeError, match="DB_ENCRYPTION_KEY is required"):
        await db_main_module.connect_database()
