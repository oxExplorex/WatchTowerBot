import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from core.personal_crypto import create_key_bundle, unlock_private_key
from db.history_models import HistoryChat, HistoryRun
from db.message_models import MessageRevision, StoredMessage
from db.repositories.history_repo import HistoryRepository
from db.repositories.personal_repo import PersonalKeyRepository
from services.history_windows import HistoryWindow


def message(identity, *, chat=11, edited=False, text="private history", media=None):
    return SimpleNamespace(id=identity, chat=SimpleNamespace(id=chat, type="private", username=None, full_name="Offline"),
        from_user=SimpleNamespace(id=chat, username=None, full_name="Offline"),
        date=datetime.fromtimestamp(100, timezone.utc),
        edit_date=datetime.fromtimestamp(200, timezone.utc) if edited else None,
        text=text, document=media)


@pytest_asyncio.fixture
async def history(db_main, offline_module, monkeypatch):
    module = offline_module("services/history_backfill.py")
    import services.message_service as messages
    monkeypatch.setattr(messages, "messages_repository", db_main.messages_repository)
    await db_main.create_app_tg(1001, 12345, "synthetic", "app")
    app = (await db_main.get_app_tg_user_id(1001))[0][0]
    account = await db_main.create_account_tg(1001, 2002, app.uuid, "79000000001")
    bundle = create_key_bundle(1001, "Личныйсекрет1001")
    await PersonalKeyRepository(db_main.get_session_factory).install(1001, bundle)
    return SimpleNamespace(module=module, db=db_main, account=account, bundle=bundle,
        repository=HistoryRepository(db_main.get_session_factory),
        bot=SimpleNamespace(id=777777, send_message=AsyncMock()), pause=AsyncMock())


async def reset_run(history):
    async with history.db.create_unit_of_work() as uow:
        await uow.session.execute(update(HistoryRun).values(next_run_at=0))


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True])
async def test_worker_waits_for_initial_peer_cache_before_history_requests(offline_module, monkeypatch, loaded):
    import sys
    module = offline_module("services/history_backfill.py")
    lookup = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(sys.modules["db.main"], "get_account_by_number", lookup)
    monkeypatch.setattr(module, "session_number_from_client", lambda _: "offline")
    client = SimpleNamespace(_watchtower_dialogs_loaded=loaded)
    manager = SimpleNamespace(get_snapshot=AsyncMock(return_value=[client]),
        is_available=AsyncMock(return_value=True), run=AsyncMock())
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError]))
    with pytest.raises(asyncio.CancelledError):
        await module.run_history_backfill(SimpleNamespace(id=777777), manager)
    assert lookup.await_count == int(loaded)
    assert manager.run.await_count == int(loaded)


async def rows(history, model):
    async with history.db.create_unit_of_work() as uow:
        return list(await uow.session.scalars(select(model)))


@pytest.mark.asyncio
async def test_history_target_logs_distinguish_owner_account_and_dialog_ids(history, caplog):
    import logging
    h = history
    caplog.set_level(logging.DEBUG)
    await h.db.create_dump_chat_user(2002, 11)
    await h.repository.observe_heads(h.account.uuid, {11: 75})
    error = TimeoutError("synthetic-private-message")
    fetch = AsyncMock(side_effect=error)
    await h.module.backfill_account(h.bot, object(), h.account, h.repository, fetch_page=fetch, pause=h.pause)
    assert "source=dialogs chats=1" in caplog.text
    assert "owner_id=1001 account_user_id=2002 dump_admin_id=2002" in caplog.text
    assert "account_user_id=2002 owner_id=1001 chat_id=11 stage=get_chat_history error=TimeoutError" in caplog.text
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "chat_id_top_id" not in caplog.text and "synthetic-private-message" not in caplog.text
    assert "Личныйсекрет1001" not in caplog.text


@pytest.mark.asyncio
async def test_sparse_edited_snapshot_is_personally_encrypted_and_resumes_at_available_start(history):
    h = history
    await h.db.create_dump_chat_user(2002, 11)
    fetch = AsyncMock(return_value=([5000, 5003, 5010], [message(5010, edited=True), message(5003), message(5000)]))
    await h.module.backfill_account(h.bot, object(), h.account, h.repository, fetch_page=fetch, pause=h.pause)
    stored = await rows(h, StoredMessage)
    assert {item.message_id for item in stored} == {5000, 5003, 5010}
    assert all(not item.is_deleted for item in stored)
    assert next(item for item in stored if item.message_id == 5010).is_edited
    revisions = await rows(h, MessageRevision)
    assert all(item.kind == "snapshot" and item.encryption_version == 2 and "private history" not in item.payload for item in revisions)
    private = unlock_private_key(1001, h.bundle, "Личныйсекрет1001")
    assert h.db.messages_repository.decode_payload(revisions[0], owner_id=1001, private_key=private)["text"] == "private history"
    await reset_run(h)
    fetch.reset_mock(return_value=True)
    fetch.return_value = ([], [])
    restarted = HistoryRepository(h.db.get_session_factory)
    await h.module.backfill_account(h.bot, object(), h.account, restarted, fetch_page=fetch, pause=h.pause)
    assert fetch.await_args.args[2] == HistoryWindow(1, 4999)
    progress = (await rows(h, HistoryChat))[0]
    assert progress.reached_start and progress.oldest_message_id == 5000
    assert await restarted.ranges(h.account.uuid, 11) == [(1, 5010)]


@pytest.mark.asyncio
async def test_budget_is_persistent_fair_and_excludes_groups_and_control_bot(history):
    h = history
    eligible = set(range(11, 36))
    for chat_id in [*sorted(eligible), -123, -100123, h.bot.id]:
        await h.db.create_dump_chat_user(2002, chat_id)
    async def fetch(client, chat_id, window):
        identity = min(100, window.high_id or 100)
        return [identity], [message(identity, chat=chat_id)]
    fetch = AsyncMock(side_effect=fetch)
    await h.module.backfill_account(h.bot, object(), h.account, h.repository, fetch_page=fetch, pause=h.pause)
    first = {call.args[1] for call in fetch.await_args_list}
    assert fetch.await_count == len(first) == 10 and first <= eligible
    assert h.pause.await_count == 9
    await h.module.backfill_account(h.bot, object(), h.account, HistoryRepository(h.db.get_session_factory), fetch_page=fetch, pause=h.pause)
    assert fetch.await_count == 10  # Restart must not reset the 20-minute budget.
    await reset_run(h)
    await h.module.backfill_account(h.bot, object(), h.account, h.repository, fetch_page=fetch, pause=h.pause)
    second = {call.args[1] for call in fetch.await_args_list[10:]}
    assert fetch.await_count == 20 and len(second) == 10 and second <= eligible
    assert first.isdisjoint(second)
    await reset_run(h)
    await h.module.backfill_account(h.bot, object(), h.account, h.repository, fetch_page=fetch, pause=h.pause)
    # The five still-unvisited chats precede any repeat, regardless of random order.
    assert {call.args[1] for call in fetch.await_args_list[20:25]} == eligible - first - second


@pytest.mark.asyncio
async def test_floodwait_persists_without_advancing_coverage(history):
    from pyrogram.errors import FloodWait
    import time

    h = history
    await h.db.create_dump_chat_user(2002, 11)
    fetch = AsyncMock(side_effect=FloodWait(1800))
    await h.module.backfill_account(h.bot, object(), h.account, h.repository, fetch_page=fetch, pause=h.pause)
    assert await h.repository.blocked_until(2002) >= int(time.time()) + 1800
    assert await h.repository.ranges(h.account.uuid, 11) == []
    await reset_run(h)
    await h.module.backfill_account(h.bot, object(), h.account, HistoryRepository(h.db.get_session_factory), fetch_page=fetch, pause=h.pause)
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_restart_after_partial_page_replays_without_duplicate_revisions(history):
    h = history
    await h.db.create_dump_chat_user(2002, 11)
    fetch = AsyncMock(return_value=([10, 11], [message(11), message(10)]))
    original = h.module.save_message
    async def interrupted(*args, **kwargs):
        await original(*args, **kwargs)
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await h.module.backfill_account(h.bot, object(), h.account, h.repository,
            fetch_page=fetch, save=interrupted, pause=h.pause)
    assert await h.repository.ranges(h.account.uuid, 11) == []
    await reset_run(h)
    await h.module.backfill_account(h.bot, object(), h.account, HistoryRepository(h.db.get_session_factory),
                                    fetch_page=fetch, pause=h.pause)
    assert len(await rows(h, StoredMessage)) == len(await rows(h, MessageRevision)) == 2
    assert await h.repository.ranges(h.account.uuid, 11) == [(10, 11)]


@pytest.mark.asyncio
async def test_known_missing_is_separate_from_deleted_and_unseen_ids_are_not_invented(history):
    h = history
    for chat_id, identity in [(11, 73), (22, 75)]:
        await h.db.messages_repository.record(owner_id=1001, account_user_id=2002, chat_id=chat_id,
            message_id=identity, kind="new", source="userbot", event_key=str(identity),
            sent_at=100, payload={"text": "known", "media": []})
    await h.repository.seed(h.account, h.bot.id)
    progress = next(item for item in await rows(h, HistoryChat) if item.chat_id == 11)
    import time
    await h.repository.checkpoint(progress, HistoryWindow(70, 80), [71, 72, 74, 77, 80],
                                  [71, 72, 74, 77, 80], time.time_ns() // 1000)
    stored = await rows(h, StoredMessage)
    assert len(stored) == 2
    assert next(item for item in stored if item.message_id == 73).history_missing_at is not None
    assert next(item for item in stored if item.message_id == 75).history_missing_at is None
    assert not any(item.is_deleted for item in stored)
    # An identical replay must clear unavailability without creating a revision.
    await h.db.messages_repository.record(owner_id=1001, account_user_id=2002, chat_id=11,
        message_id=73, kind="new", source="userbot", event_key="73", sent_at=100,
        payload={"text": "known", "media": []})
    assert next(item for item in await rows(h, StoredMessage) if item.message_id == 73).history_missing_at is None
    assert len(await rows(h, MessageRevision)) == 2


@pytest.mark.asyncio
async def test_old_snapshot_cannot_overwrite_live_content_and_personal_key_is_required(history):
    h = history
    repo = h.db.messages_repository
    original = await repo.record(owner_id=1001, account_user_id=2002, chat_id=11, message_id=10,
        source="business", event_key="live", kind="edit", version_at=200, payload={"text": "fresh", "media": []})
    await repo.record(owner_id=1001, account_user_id=2002, chat_id=11, message_id=10,
        source="history", event_key="old", kind="new", version_at=100, payload={"text": "stale", "media": []}, historical=True)
    revisions = await repo.get_revisions(owner_id=1001, message_uuid=original.message_uuid)
    assert len(revisions) == 1
    assert (await rows(h, StoredMessage))[0].is_edited
    assert await repo.record(owner_id=9009, account_user_id=8008, chat_id=11, message_id=10,
        source="history", event_key="missing-key", kind="new", payload={"text": "must not be legacy", "media": []}, historical=True) is None
    assert (await h.db.get_archive_statistics(9009))["messages"] == 0


@pytest.mark.asyncio
async def test_historical_page_cannot_resurrect_deleted_dialog_or_emit_new_chat(history):
    from db.models import HistoryUser

    h = history
    await h.db.record_chat_presence(2002, 11, 1001, present=True, date=100)
    await h.db.record_chat_presence(2002, 11, 1001, present=False, date=200)
    result = await h.db.messages_repository.record(owner_id=1001, account_user_id=2002, chat_id=11,
        message_id=10, source="history", event_key="old", kind="new", version_at=100,
        payload={"text": "old contents", "media": []}, historical=True)
    assert result is not None and not result.new_chat
    assert await h.db.get_dump_chat_admin_all(2002) == []
    assert [item.action_id for item in sorted(await rows(h, HistoryUser), key=lambda item: item.date)] == [1, 2]
    assert len(await rows(h, StoredMessage)) == 1


@pytest.mark.asyncio
async def test_history_media_requires_secret_and_is_throttled_without_plaintext_files(history, tmp_path):
    from core.media_store import MediaStore
    from db.media_models import MessageAttachment
    from db.repositories.media_repo import MediaRepository
    from services.media_archive import archive_attachment

    h = history
    await h.db.create_dump_chat_user(2002, 11)
    data = b"private attachment contents"
    messages = [message(identity, media=SimpleNamespace(
        file_id=f"file-{identity}", file_unique_id=f"unique-{identity}", file_size=len(data),
        file_name="private-document.txt")) for identity in (11, 10)]
    fetch = AsyncMock(return_value=([11, 10], messages))
    await h.module.backfill_account(h.bot, object(), h.account, h.repository, fetch_page=fetch, pause=h.pause)
    repository = MediaRepository(h.db.get_session_factory)
    store = MediaStore(tmp_path / "history-media")
    downloaded = []
    async def stream(file_id):
        downloaded.append(file_id)
        yield data
    client = SimpleNamespace(stream_media=stream)
    resolver = AsyncMock(return_value=client)
    for _ in range(2):
        await archive_attachment(h.bot, repository, store, await repository.claim(), resolve_client=resolver,
                                 run_client=lambda client, operation: operation(), limits=h.repository)
    items = await rows(h, MessageAttachment)
    ready = next(item for item in items if item.status == "stored")
    pending = next(item for item in items if item.status == "pending")
    assert ready.encryption_version == ready.sources_encryption_version == 2
    assert pending.attempts == 0 and len(downloaded) == 1
    with pytest.raises(PermissionError):
        store.read(1001, ready.blob_key)
    private = unlock_private_key(1001, h.bundle, "Личныйсекрет1001")
    assert store.read(1001, ready.blob_key, private_key=private) == data
    assert data not in store.path(1001, ready.blob_key).read_bytes()
    assert not list(tmp_path.rglob("*.part")) and not list(tmp_path.rglob("private-document.txt"))
    stats = await h.db.get_archive_statistics(1001)
    assert (stats["messages"], stats["revisions"], stats["media_stored"], stats["media_pending"]) == (2, 2, 1, 1)
    assert (await h.db.get_archive_statistics(9009))["messages"] == 0
