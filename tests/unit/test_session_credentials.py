from pyrogram import Client
import pytest

from core.session_credentials import sync_session_api
import sqlite3
from core.session_schema import SessionSchemaError


@pytest.mark.asyncio
async def test_selected_api_id_updates_only_disconnected_synthetic_session(tmp_path):
    client = Client(name=str(tmp_path / "synthetic"), api_id=23456, api_hash="synthetic")
    await client.storage.open()
    await client.storage.api_id(12345)
    await client.storage.close()
    await sync_session_api(client)
    await client.storage.open()
    try:
        assert await client.storage.api_id() == 23456
    finally:
        await client.storage.close()


    client.is_connected = True
    client.api_id = 34567
    await sync_session_api(client)
    client.is_connected = False
    await client.storage.open()
    try:
        assert await client.storage.api_id() == 23456
    finally:
        await client.storage.close()


@pytest.mark.asyncio
async def test_unknown_schema_is_rejected_before_sdk_open_without_mutation(tmp_path, monkeypatch, offline_module):
    from unittest.mock import AsyncMock
    path = tmp_path / "unknown.session"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE sessions (dc_id INTEGER PRIMARY KEY, api_id INTEGER, test_mode INTEGER, "
            "auth_key BLOB, date INTEGER NOT NULL, user_id INTEGER, is_bot INTEGER);"
            "CREATE TABLE peers (id INTEGER PRIMARY KEY, access_hash INTEGER, type TEXT, "
            "phone_number TEXT, last_update_on INTEGER);"
            "CREATE TABLE version (number INTEGER); INSERT INTO version VALUES (4);"
            "CREATE TABLE update_state (id INTEGER, pts INTEGER, qts INTEGER, date INTEGER, seq INTEGER);"
            "CREATE TABLE usernames (unknown TEXT);")
    before = path.read_bytes()
    client = Client(name=str(tmp_path / "unknown"), api_id=12345, api_hash="synthetic")
    client.storage.open = AsyncMock()
    with pytest.raises(SessionSchemaError) as caught:
        await sync_session_api(client)
    assert caught.value.columns == ("unknown",)
    client.storage.open.assert_not_awaited()
    assert path.read_bytes() == before
    import sys
    from types import SimpleNamespace
    from core.session_manager import SessionManager
    manager = SessionManager()
    await manager.add(client)
    monkeypatch.setitem(sys.modules, "loader", SimpleNamespace(session_manager=manager))
    runtime = offline_module("core/session_runtime.py")
    client.start = AsyncMock()
    with pytest.raises(SessionSchemaError):
        await runtime.start_client(client)
    client.start.assert_not_awaited()
    assert path.read_bytes() == before
