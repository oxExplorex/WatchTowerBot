"""Small cached contact photos, using the existing sessions, limits and personal crypto."""
import asyncio
from core.logging import bot_logger
from core.media_store import MediaStore
from core.session_runtime import run_client_operation
from db.repositories.avatars_repo import AvatarsRepository
from db.repositories.history_repo import HistoryRepository
from db.repositories.media_repo import MediaRepository
from db.session import get_session_factory
from pyrogram.errors import FloodWait
from services.media_archive import resolve_media_client, SourceUnavailable
from utils.crypto_store import decrypt_text


async def archive_avatar(bot, repository, store, item, *, resolve_client=resolve_media_client,
                         run_client=run_client_operation, limits=None, keys=None):
    limits = limits or HistoryRepository(get_session_factory)
    keys = keys or MediaRepository(get_session_factory)
    try:
        public = await keys.get_public_key(item.owner_id)
        if not public or not item.file_id:
            raise SourceUnavailable()
        delay = await limits.media_slot(item.account_user_id)
        if delay:
            await repository.finish(item, delay=delay)
            return
        # A corrupt/oversized profile photo must not use the normal 100 MiB allowance.
        avatar_store = MediaStore(store.root, max_file_bytes=min(store.max_file_bytes, 2 * 1024**2),
                                  max_total_bytes=store.max_total_bytes)
        with avatar_store.writer(item.owner_id, public_key=public) as writer:
            async with asyncio.timeout(60):
                if item.source == "business":
                    await bot.download(decrypt_text(item.file_id), destination=writer, seek=False, timeout=60)
                else:
                    client = await resolve_client(item.owner_id, item.account_user_id)
                    if client is None:
                        raise SourceUnavailable()
                    async def download():
                        async for chunk in client.stream_media(decrypt_text(item.file_id)):
                            writer.write(chunk)
                    await run_client(client, download)
            if not writer.size:
                raise ValueError("Empty avatar")
            blob_key, _ = writer.finish()
        await repository.finish(item, blob_key=blob_key)
    except asyncio.CancelledError:
        await repository.finish(item, delay=30)
        raise
    except FloodWait as error:
        await limits.defer(item.account_user_id, int(error.value) + 5)
        await repository.finish(item, delay=int(error.value) + 5)
    except Exception as error:
        await repository.finish(item, delay=3600)
        bot_logger.debug("Avatar download deferred: account_user_id=%s peer_id=%s error=%s",
                         item.account_user_id, item.user_id, type(error).__name__)


async def run_avatar_archiver(bot):
    repository, store = AvatarsRepository(get_session_factory), MediaStore.from_environment()
    await asyncio.sleep(90)
    while True:
        try:
            item = await repository.claim()
            if item is not None:
                await archive_avatar(bot, repository, store, item)
        except Exception as error:
            bot_logger.warning("Avatar queue deferred: %s", type(error).__name__)
        await asyncio.sleep(5)
