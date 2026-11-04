"""Align a disconnected session's API ID with its explicitly selected profile."""
from pathlib import Path


async def sync_session_api(client):
    from pyrogram import Client

    if not isinstance(client, Client) or client.is_connected or not getattr(client, "api_id", None):
        return
    if not Path(f"{client.name}.session").is_file():
        return
    await client.storage.open()
    try:
        if await client.storage.api_id() != client.api_id:
            await client.storage.api_id(client.api_id)
    finally:
        await client.storage.close()
