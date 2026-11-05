"""Align a disconnected session's API ID with its explicitly selected profile."""
from pathlib import Path
from core.thread_tools import run_blocking
from core.session_schema import validate_session_schema


async def sync_session_api(client):
    from pyrogram import Client

    if not isinstance(client, Client) or client.is_connected or not getattr(client, "api_id", None):
        return
    path = getattr(client.storage, "database", None)
    if not isinstance(path, Path) or not path.is_file():
        return
    # Old fork sessions require manual reauthorization, never automatic conversion.
    await run_blocking(validate_session_schema, path)
    await client.storage.open()
    try:
        if await client.storage.api_id() != client.api_id:
            await client.storage.api_id(client.api_id)
    finally:
        await client.storage.close()
