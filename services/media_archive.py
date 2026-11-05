import asyncio
import json
import time

from core.logging import bot_logger
from core.media_store import MediaQuotaExceeded, MediaStore, MediaTooLarge
from core.session_manager import SessionUnavailable
from core.session_runtime import run_client_operation
from db.repositories.history_repo import HistoryRepository
from db.session import get_session_factory
from pyrogram.errors import FloodWait
from utils.crypto_store import decrypt_text


class SourceUnavailable(RuntimeError):
    pass


class TelegramDeferred(RuntimeError):
    def __init__(self, delay):
        self.delay = max(1, int(delay))


async def resolve_media_client(owner_id, account_user_id):
    from core.session_runtime import get_client_by_number
    from db.main import get_accounts_for_user_id

    for account in await get_accounts_for_user_id(account_user_id):
        if account.admin_id == owner_id and account.is_active:
            client = await get_client_by_number(account.number)
            if client is not None and client.is_initialized:
                return client
    return None


async def archive_attachment(bot, repository, store, item, *, resolve_client=resolve_media_client,
                             run_client=run_client_operation, limits=None):
    try:
        limits = limits or HistoryRepository(get_session_factory)
        public_key = await repository.get_public_key(item.owner_id)
        sources = json.loads(decrypt_text(item.sources))
        history_only = sources and all(source["source"] == "history" for source in sources)
        if history_only and public_key is None:
            raise SourceUnavailable()
        cached = await repository.find_stored(item)
        if cached is not None and store.path(item.owner_id, cached.blob_key).is_file():
            version = store.version(item.owner_id, cached.blob_key)
            if not history_only or public_key is None or version == 2:
                await repository.finish(item, blob_key=cached.blob_key, stored_size=cached.stored_size,
                                        encryption_version=version)
                return
            # The existing migration owns rewrapping and its owner lock. Do not
            # redownload or publish a legacy blob as a completed personal archive.
            raise SourceUnavailable()
        if item.expected_size is not None and item.expected_size > store.max_file_bytes:
            raise MediaTooLarge("Media file exceeds archive limit")
        last_error = SourceUnavailable()
        unavailable = False
        deadline = asyncio.get_running_loop().time() + 600
        for source in reversed(sources):
            try:
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError()
                client = None
                if source["source"] in {"userbot", "history"}:
                    blocked = await limits.blocked_until(source["account_user_id"])
                    if blocked > int(time.time()):
                        raise TelegramDeferred(blocked - int(time.time()))
                    if source["source"] == "history":
                        if public_key is None:
                            raise SourceUnavailable()
                        delay = await limits.media_slot(source["account_user_id"])
                        if delay:
                            raise TelegramDeferred(delay)
                    client = await resolve_client(item.owner_id, source["account_user_id"])
                    if client is None:
                        raise SourceUnavailable()
                with store.writer(item.owner_id, compress=source["kind"] == "document", public_key=public_key) as writer:
                    async with asyncio.timeout_at(deadline):
                        if client is None:
                            await bot.download(source["file_id"], destination=writer, seek=False, timeout=600)
                        else:
                            async def download():
                                async for chunk in client.stream_media(source["file_id"]):
                                    writer.write(chunk)
                            await run_client(client, download)
                    if (item.expected_size is not None and writer.size != item.expected_size) or (
                        writer.size == 0 and item.expected_size != 0
                    ):
                        raise ValueError("Incomplete media download")
                    blob_key, size = writer.finish()
                if history_only and public_key is not None and store.version(item.owner_id, blob_key) != 2:
                    raise SourceUnavailable()  # Deduplication found a legacy orphan; migration will rewrap it.
                await repository.finish(item, blob_key=blob_key, stored_size=size,
                                        encryption_version=store.version(item.owner_id, blob_key))
                return
            except (MediaTooLarge, MediaQuotaExceeded):
                raise
            except TelegramDeferred:
                raise
            except FloodWait as exc:
                await limits.defer(source["account_user_id"], int(exc.value) + 5)
                bot_logger.warning("Attachment Telegram cooldown: account_user_id=%s wait_seconds=%s",
                                   source["account_user_id"], int(exc.value) + 5)
                raise TelegramDeferred(int(exc.value) + 5) from None
            except Exception as exc:
                last_error = exc
                unavailable = unavailable or isinstance(exc, (SourceUnavailable, SessionUnavailable))
        if unavailable:
            raise SourceUnavailable()
        raise last_error
    except asyncio.CancelledError:
        # Queue is durable; shutdown releases the lease rather than losing work.
        await repository.finish(item, error="Cancelled", delay=1)
        raise
    except TelegramDeferred as exc:
        # Rate limits are scheduled waits, not failed download attempts.
        await repository.finish(item, error="TelegramDeferred", delay=exc.delay)
    except Exception as exc:
        delay = (60 if isinstance(exc, SourceUnavailable)
                 else 3600 if isinstance(exc, MediaQuotaExceeded) else 0)
        await repository.finish(item, error=type(exc).__name__, delay=delay, permanent=isinstance(exc, MediaTooLarge))
        bot_logger.warning("Attachment download deferred or failed: %s", type(exc).__name__)


async def run_media_archiver(bot):
    from db.repositories.media_repo import MediaRepository
    from db.session import get_session_factory

    store = MediaStore.from_environment()
    repository = MediaRepository(get_session_factory)
    next_cleanup = 0
    while True:
        try:
            if time.monotonic() >= next_cleanup:
                await asyncio.to_thread(store.cleanup_parts)
                next_cleanup = time.monotonic() + 3600
            item = await repository.claim()
            if item is None:
                await asyncio.sleep(2)
            else:
                await archive_attachment(bot, repository, store, item)
        except Exception as exc:
            bot_logger.warning("Attachment queue unavailable: %s", type(exc).__name__)
            await asyncio.sleep(5)
