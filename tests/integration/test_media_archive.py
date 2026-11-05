import asyncio
import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from core.media_store import MediaStore
from core.session_manager import SessionManager
from db.media_models import MessageAttachment
from db.repositories.media_repo import MediaRepository
from utils.crypto_store import decrypt_text


async def attachments(db):
    async with db.create_unit_of_work() as uow:
        return list((await uow.session.scalars(select(MessageAttachment))).all())


async def ingest(db, *, message_id=10, source="business", file_id="bot-file", unique_id="shared", size=12):
    return await db.messages_repository.record(owner_id=123, account_user_id=456, chat_id=789,
        message_id=message_id, source=source, event_key="original", kind="new", sent_at=100,
        payload={"text": None, "media": [{"kind": "document", "file_id": file_id,
                  "file_unique_id": unique_id, "file_size": size}]})


@pytest.mark.asyncio
async def test_sources_are_encrypted_and_repeated_files_reuse_blob(db_main, tmp_path, monkeypatch):
    from aiogram import Bot
    from services.media_archive import archive_attachment

    await ingest(db_main)
    await ingest(db_main, source="userbot", file_id="userbot-file")
    await ingest(db_main, message_id=11)
    repository = MediaRepository(db_main.get_session_factory)
    store = MediaStore(tmp_path / "media")
    rows = await attachments(db_main)
    merged = next(row for row in rows if len(json.loads(decrypt_text(row.sources))) == 2)
    assert "bot-file" not in merged.sources

    async def stream(**kwargs):
        yield b"private-"
        yield b"file"

    bot = Bot("123456:offline_test_token")
    monkeypatch.setattr(bot, "get_file", AsyncMock(return_value=SimpleNamespace(file_path="offline-file")))
    monkeypatch.setattr(bot.session, "stream_content", stream)
    monkeypatch.setattr(bot, "download", AsyncMock(wraps=bot.download))
    unavailable = AsyncMock(return_value=None)
    for _ in range(2):
        item = await repository.claim()
        await archive_attachment(bot, repository, store, item, resolve_client=unavailable)
    assert bot.download.await_count == 1
    rows = await attachments(db_main)
    assert {row.status for row in rows} == {"stored"}
    assert len({row.blob_key for row in rows}) == 1
    assert store.read(123, rows[0].blob_key) == b"private-file"
    # Different Telegram IDs for the same bytes still leave one physical copy.
    await ingest(db_main, message_id=12, unique_id="another-id")
    await archive_attachment(bot, repository, store, await repository.claim(), resolve_client=unavailable)
    assert bot.download.await_count == 2
    assert len(list(tmp_path.rglob("*.wtm"))) == 1
    await bot.session.close()


@pytest.mark.asyncio
async def test_claim_is_exclusive_and_expired_worker_cannot_overwrite_new_lease(db_main):
    await ingest(db_main)
    repository = MediaRepository(db_main.get_session_factory)
    claimed = await asyncio.gather(repository.claim(), repository.claim())
    assert sum(item is not None for item in claimed) == 1
    old = next(item for item in claimed if item is not None)
    async with db_main.create_unit_of_work() as uow:
        await uow.session.execute(update(MessageAttachment).values(lease_until=0))
        await uow.commit()
    replacement = await MediaRepository(db_main.get_session_factory).claim()
    assert replacement.lease_token != old.lease_token
    await repository.finish(old, blob_key="0" * 64, stored_size=12)
    assert (await attachments(db_main))[0].status == "downloading"
    await repository.finish(replacement, blob_key="1" * 64, stored_size=12)
    assert (await attachments(db_main))[0].blob_key == "1" * 64


@pytest.mark.asyncio
async def test_cancellation_requeues_download_and_removes_partial_ciphertext(db_main, tmp_path):
    from services.media_archive import archive_attachment

    await ingest(db_main)
    repository = MediaRepository(db_main.get_session_factory)
    started = asyncio.Event()

    async def download(file_id, *, destination, **kwargs):
        destination.write(b"part")
        started.set()
        await asyncio.Future()

    task = asyncio.create_task(archive_attachment(SimpleNamespace(download=download), repository,
                                                MediaStore(tmp_path / "media"), await repository.claim()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.wtm"))
    row = (await attachments(db_main))[0]
    assert row.status == "pending" and row.lease_token is None
    assert row.last_error == "Cancelled"


@pytest.mark.asyncio
async def test_new_source_arriving_during_failure_gets_its_own_retries(db_main):
    await ingest(db_main)
    repository = MediaRepository(db_main.get_session_factory)
    old = await repository.claim()
    await ingest(db_main, source="userbot", file_id="new-alternative")
    await repository.finish(old, error="ExpiredFileId", permanent=True)
    row = (await attachments(db_main))[0]
    assert row.status == "pending" and row.attempts == 0
    assert len(json.loads(decrypt_text(row.sources))) == 2
    assert await repository.claim() is not None


@pytest.mark.asyncio
async def test_userbot_download_survives_bot_limit_and_retries_failures(db_main, tmp_path):
    from services.media_archive import archive_attachment

    await ingest(db_main, source="userbot", file_id="userbot-file")
    repository = MediaRepository(db_main.get_session_factory)
    bot = SimpleNamespace(download=AsyncMock(side_effect=RuntimeError("offline failure")))
    attempts = 0

    async def stream(file_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield b"part"
            raise RuntimeError("offline interrupted stream")
        yield b"private-file"

    client = SimpleNamespace(stream_media=stream)
    resolver = AsyncMock(return_value=client)
    store = MediaStore(tmp_path / "media")
    await archive_attachment(bot, repository, store, await repository.claim(), resolve_client=resolver,
                             run_client=lambda client, operation: operation())
    row = (await attachments(db_main))[0]
    assert row.status == "pending" and row.attempts == 1
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.wtm"))
    async with db_main.create_unit_of_work() as uow:
        await uow.session.execute(update(MessageAttachment).values(next_attempt_at=0))
        await uow.commit()
    await archive_attachment(bot, repository, store, await repository.claim(), resolve_client=resolver,
                             run_client=lambda client, operation: operation())
    row = (await attachments(db_main))[0]
    assert row.status == "stored" and store.read(123, row.blob_key) == b"private-file"
    bot.download.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("quota", [False, True])
async def test_limits_preserve_metadata_without_filling_disk(db_main, tmp_path, quota):
    from services.media_archive import archive_attachment

    await ingest(db_main)
    repository = MediaRepository(db_main.get_session_factory)
    store = MediaStore(tmp_path / "media", max_file_bytes=100 if quota else 3, max_total_bytes=1 if quota else 1000)
    bot = SimpleNamespace(download=AsyncMock())
    await archive_attachment(bot, repository, store, await repository.claim())
    row = (await attachments(db_main))[0]
    assert row.status == ("pending" if quota else "failed")
    assert row.last_error == ("MediaQuotaExceeded" if quota else "MediaTooLarge")
    assert not list(tmp_path.rglob("*.wtm"))
    bot.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_stop_defers_download_without_consuming_retry_or_leaving_partial_file(db_main, tmp_path):
    from services.media_archive import archive_attachment

    await ingest(db_main, source="userbot", file_id="userbot-file")
    repository = MediaRepository(db_main.get_session_factory)
    manager = SessionManager()
    started = asyncio.Event()

    async def stream(file_id):
        yield b"part"
        started.set()
        await asyncio.Future()

    active = SimpleNamespace(is_initialized=True, is_connected=True, stream_media=stream)
    await manager.add(active)
    downloading = asyncio.create_task(archive_attachment(SimpleNamespace(), repository, MediaStore(tmp_path / "media"),
        await repository.claim(), resolve_client=AsyncMock(return_value=active), run_client=manager.run))
    async with asyncio.timeout(2):
        await started.wait()
        await manager.stop(active, AsyncMock())
        await downloading
    row = (await attachments(db_main))[0]
    assert row.status == "pending" and row.attempts == 0 and row.last_error == "SourceUnavailable"
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
async def test_scheduled_media_pause_stays_pending_without_warning_or_network(
        db_main, tmp_path, caplog, blocked):
    from core.personal_crypto import create_key_bundle
    from db.repositories.personal_repo import PersonalKeyRepository
    from services.media_archive import archive_attachment

    await PersonalKeyRepository(db_main.get_session_factory).install(123, create_key_bundle(123, "OfflineSecret123"))
    await ingest(db_main, source="history", file_id="history-file")
    repository = MediaRepository(db_main.get_session_factory)
    now = int(time.time())
    limits = SimpleNamespace(blocked_until=AsyncMock(return_value=now + 30 if blocked else 0),
                             media_slot=AsyncMock(return_value=30))
    resolver = AsyncMock()
    bot = SimpleNamespace(download=AsyncMock())
    with caplog.at_level(logging.WARNING):
        await archive_attachment(bot, repository, MediaStore(tmp_path / "media"), await repository.claim(),
                                 resolve_client=resolver, limits=limits)
    row = (await attachments(db_main))[0]
    assert row.status == "pending" and row.attempts == 0 and row.lease_token is None
    assert row.last_error == "TelegramDeferred" and row.next_attempt_at >= now + 29
    assert await repository.claim() is None
    resolver.assert_not_awaited()
    bot.download.assert_not_awaited()
    assert not caplog.records
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.asyncio
async def test_real_floodwait_logs_once_and_repeated_cooldown_is_quiet(db_main, tmp_path, caplog):
    from pyrogram.errors import FloodWait
    from services.media_archive import archive_attachment

    await ingest(db_main, source="userbot", file_id="userbot-file")
    repository = MediaRepository(db_main.get_session_factory)
    limits = SimpleNamespace(blocked_until=AsyncMock(return_value=0), defer=AsyncMock())
    async def stream(file_id):
        raise FloodWait(120)
        yield
    resolver = AsyncMock(return_value=SimpleNamespace(stream_media=stream))
    store = MediaStore(tmp_path / "media")
    with caplog.at_level(logging.WARNING):
        await archive_attachment(SimpleNamespace(), repository, store, await repository.claim(),
            resolve_client=resolver, limits=limits, run_client=lambda client, operation: operation())
        limits.defer.assert_awaited_once_with(456, 125)
        row = (await attachments(db_main))[0]
        assert row.status == "pending" and row.attempts == 0
        # A second attachment encounters the existing cooldown without another network call.
        limits.blocked_until.return_value = int(time.time()) + 125
        await ingest(db_main, message_id=11, source="userbot", unique_id="second")
        await archive_attachment(SimpleNamespace(), repository, store, await repository.claim(),
            resolve_client=resolver, limits=limits)
    assert resolver.await_count == 1
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1 and "Attachment Telegram cooldown" in warnings[0].message
    assert all(row.attempts == 0 and row.status == "pending" for row in await attachments(db_main))
    assert not list(tmp_path.rglob("*.part"))
