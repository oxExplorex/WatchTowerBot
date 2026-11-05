from contextlib import closing
import sqlite3

import pytest
from pyrogram.storage import SQLiteStorage

from core.session_schema import SessionSchemaError, validate_session_schema


@pytest.mark.parametrize("usernames", [
    "id TEXT PRIMARY KEY, peer_id INTEGER, last_update_on INTEGER",
    "id INTEGER, username TEXT",
    "unknown TEXT",
])
def test_old_or_partial_fork_session_requires_manual_login_without_any_writes(tmp_path, usernames):
    path = tmp_path / "legacy.session"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            "CREATE TABLE peers (id INTEGER, username TEXT);"
            "CREATE TABLE version (number INTEGER); INSERT INTO version VALUES (4);"
            "CREATE TABLE update_state (id INTEGER);"
            f"CREATE TABLE usernames ({usernames});")
    before = path.read_bytes()
    with pytest.raises(SessionSchemaError, match="manual authorization"):
        validate_session_schema(path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.asyncio
async def test_current_sdk_session_is_accepted_without_changes(tmp_path):
    storage = SQLiteStorage("current", tmp_path)
    await storage.open()
    await storage.close()
    path = tmp_path / "current.session"
    before = path.read_bytes()
    validate_session_schema(path)
    assert path.read_bytes() == before
