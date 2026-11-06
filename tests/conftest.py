from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
import types
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def isolate_library_log_routes(monkeypatch):
    # Bootstrap tests may install an application route on the process-wide root.
    # Keep it from forwarding another test's synthetic logger and capturing it twice.
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [handler for handler in root.handlers
        if not (type(handler).__module__ == "core.log_safety" and type(handler).__name__ == "LibraryErrorHandler")])


def pytest_addoption(parser):
    parser.addoption("--database-backend", choices=("sqlite", "postgresql"), default="sqlite")
    parser.addoption("--postgres-bin", default=None, help="Directory containing initdb and pg_ctl for disposable tests")


@pytest.fixture(scope="session")
def postgres_cluster(request, tmp_path_factory):
    if request.config.getoption("--database-backend") != "postgresql":
        yield None
        return
    from postgres_cluster import temporary_postgres

    with temporary_postgres(tmp_path_factory.mktemp("watchtower-postgres"), request.config.getoption("--postgres-bin")) as settings:
        yield settings


@pytest.fixture
def offline_module(monkeypatch):
    config = types.ModuleType("data.config")
    config.TOKEN_BOT = "123456:offline_test_token"
    config.GEMINI_KEY = ""
    config.GEMINI_ACTION_DEBUG = False
    config.admin_id_list = []
    logger = types.ModuleType("core.logging")
    logger.bot_logger = logging.getLogger("watchtower_offline_tests")
    database = types.ModuleType("db.main")

    def database_function(name):
        if name.startswith("__"):
            raise AttributeError(name)
        function = AsyncMock(name=name)
        setattr(database, name, function)
        return function

    database.__getattr__ = database_function
    monkeypatch.setitem(sys.modules, "data.config", config)
    monkeypatch.setitem(sys.modules, "core.logging", logger)
    monkeypatch.setitem(sys.modules, "db.main", database)

    def load(relative_path):
        path = Path(__file__).resolve().parents[1] / relative_path
        spec = importlib.util.spec_from_file_location(f"_offline_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        # Dataclasses and runtime annotation resolution consult sys.modules.
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        return module

    return load


@pytest_asyncio.fixture
async def database_module(tmp_path: Path, monkeypatch, postgres_cluster):
    db_file = tmp_path / "test_db.sqlite3"

    monkeypatch.setenv("BOT_DB_ENGINE", "sqlite+aiosqlite")
    monkeypatch.setenv("BOT_DB_PATH", str(db_file))
    test_database = None
    if postgres_cluster:
        test_database = "wt_test_" + uuid4().hex
        admin = await asyncpg.connect(**postgres_cluster)
        try:
            await admin.execute(f'CREATE DATABASE "{test_database}"')
        finally:
            await admin.close()
        for name, value in {"ENGINE": "postgresql+asyncpg", "NAME": test_database,
                            "HOST": postgres_cluster["host"], "PORT": postgres_cluster["port"],
                            "USER": postgres_cluster["user"], "PASSWORD": "", "ADMIN_NAME": "postgres"}.items():
            monkeypatch.setenv("BOT_DB_" + name, str(value))
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-encryption-key")
    # Real repositories and migrations, with no .env access or file logging.
    monkeypatch.setitem(sys.modules, "data.config", types.ModuleType("data.config"))
    logger = types.ModuleType("core.logging")
    logger.bot_logger = logging.getLogger("watchtower_database_tests")
    monkeypatch.setitem(sys.modules, "core.logging", logger)

    for module_name in [
        "db.engine",
        "db.session",
        "db.main",
        "db.migrations",
    ]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    import db.main as db_main_module

    try:
        yield db_main_module
    finally:
        await db_main_module.close_database()
        if test_database:
            assert test_database.startswith("wt_test_") and len(test_database) == 40
            admin = await asyncpg.connect(**postgres_cluster)
            try:
                await admin.execute(f'DROP DATABASE "{test_database}" WITH (FORCE)')
            finally:
                await admin.close()


@pytest_asyncio.fixture
async def db_main(database_module):
    await database_module.connect_database()
    return database_module
