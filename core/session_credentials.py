"""Align a disconnected session's API ID with its explicitly selected profile."""
from pathlib import Path
from core.thread_tools import run_blocking
from scripts.migrate_telegram_sessions import migrate_legacy_session


async def sync_session_api(client):
    from pyrogram import Client

    if not isinstance(client, Client) or client.is_connected or not getattr(client, "api_id", None):
        return
    path = getattr(client.storage, "database", None)
    if not isinstance(path, Path) or not path.is_file():
        return
    # Validate/convert only this client's actual file under its lifecycle lock.
    # Unknown schemas fail this client before the SDK can mutate the database.
    await run_blocking(migrate_legacy_session, path)
    await client.storage.open()
    try:
        if await client.storage.api_id() != client.api_id:
            await client.storage.api_id(client.api_id)
    finally:
        await client.storage.close()
