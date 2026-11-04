from pyrogram import Client
import pytest

from core.session_credentials import sync_session_api


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
