from pathlib import Path
import asyncio
import threading
import sys
import types
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from core.session_manager import SessionManager


@pytest_asyncio.fixture
async def update_modules(monkeypatch, offline_module):
    loader = types.ModuleType("loader")
    loader.bot = AsyncMock()
    loader.session_manager = SessionManager()
    decorator = lambda *args, **kwargs: lambda fn: fn
    loader.router = types.SimpleNamespace(message=decorator, callback_query=decorator)
    monkeypatch.setitem(sys.modules, "loader", loader)
    root = Path(__file__).resolve().parents[2]
    for name, relative in [("handlers", "handlers"), ("handlers.admin", "handlers/admin")]:
        package = types.ModuleType(name)
        package.__path__ = [str(root / relative)]
        monkeypatch.setitem(sys.modules, name, package)
    notifier = offline_module("aiotask/update_notifier.py")
    monkeypatch.setitem(sys.modules, "aiotask.update_notifier", notifier)
    settings = offline_module("handlers/admin/settings/setting_menu_handler.py")
    monkeypatch.setattr(settings, "get_configured_admin_ids", lambda: frozenset({1001}))
    monkeypatch.setattr(notifier, "_safe_send", AsyncMock())
    return notifier, settings, loader.session_manager


@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [True, False])
async def test_failed_download_never_stops_or_restarts_clients(update_modules, monkeypatch, manual):
    notifier, settings, manager = update_modules
    client = types.SimpleNamespace(stop=AsyncMock())
    await manager.add(client)
    module = settings if manual else notifier
    monkeypatch.setattr(module, "download_and_extract_github_repo", Mock(return_value=False))
    restart = AsyncMock()
    monkeypatch.setattr(module, "restart_with_clients" if manual else "_restart_process", restart)
    message = types.SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock())
    if manual:
        await settings._run_update_flow(message, "1", "2", "start", "done", "failed")
    else:
        await notifier._run_auto_update([1001], "1", "2")
    restart.assert_not_awaited()
    client.stop.assert_not_awaited()
    assert await manager.get_snapshot() == [client]
    assert await notifier.try_acquire_update_run() is True
    await notifier.release_update_run()


@pytest.mark.asyncio
@pytest.mark.parametrize("remote", ["2.0.3", "2.0.2", None])
async def test_settings_check_replaces_button_only_when_update_exists(update_modules, monkeypatch, remote):
    _, settings, _ = update_modules
    cached = [settings.constant_text.VERSION_STATE_UNKNOWN, 0, None]

    async def save_cache(*, local_version, remote_version, state):
        cached[:] = [state, int(settings.time.time()), remote_version]
        return cached[1]

    monkeypatch.setattr(settings, "get_local_version", Mock(return_value="2.0.2"))
    monkeypatch.setattr(settings, "_fetch_latest_version", AsyncMock(return_value=remote))
    monkeypatch.setattr(settings, "get_version_state_cache", AsyncMock(side_effect=lambda **kwargs: tuple(cached)))
    monkeypatch.setattr(settings, "set_version_state_cache", save_cache)
    monkeypatch.setattr(settings, "get_user_timezone_offset", AsyncMock(return_value=7))
    monkeypatch.setattr(settings, "get_user_auto_update_enabled", AsyncMock(return_value=1))
    monkeypatch.setattr(settings, "get_user_gemini_proxy_config", AsyncMock(return_value={}))
    monkeypatch.setattr(settings, "get_latest_admin_health_event", AsyncMock(return_value=None))
    before = await settings._settings_inline(1001)
    assert "set:update:check" in {button.callback_data for row in before.inline_keyboard for button in row}

    call = types.SimpleNamespace(from_user=types.SimpleNamespace(id=1001), answer=AsyncMock(),
                                 message=types.SimpleNamespace(edit_text=AsyncMock()))
    await settings.check_update_now_handler(call, types.SimpleNamespace(clear=AsyncMock()))
    markup = call.message.edit_text.await_args.kwargs["reply_markup"]
    callbacks = {button.callback_data for row in markup.inline_keyboard for button in row}
    assert ("set:update:run" in callbacks) == (remote == "2.0.3")
    assert ("set:update:check" in callbacks) == (remote != "2.0.3")
    assert " | L:" not in call.answer.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("has_proxy", [False, True])
async def test_settings_summary_distinguishes_unchecked_and_direct_connection(update_modules, monkeypatch, has_proxy):
    _, settings, _ = update_modules
    proxy_cfg = {"enabled": 0, "proxy": "http://user:private-pass@proxy.example:8080"} if has_proxy else {}
    monkeypatch.setattr(settings, "GEMINI_KEY", "offline-test-key")
    monkeypatch.setattr(settings, "get_local_version", Mock(return_value="2.0.2<test>"))
    monkeypatch.setattr(settings, "_get_cached_version_state", AsyncMock(return_value=("⚪ Неизвестно", 0, None)))
    monkeypatch.setattr(settings, "get_user_timezone_offset", AsyncMock(return_value=7))
    monkeypatch.setattr(settings, "get_user_gemini_proxy_config", AsyncMock(return_value=proxy_cfg))
    monkeypatch.setattr(settings, "get_latest_admin_health_event", AsyncMock(return_value=None))
    rendered = await settings._settings_text(1001)
    assert "ещё не выполнялась" in rendered and "0 мин назад" not in rendered
    assert "прямое подключение" in rendered and "UTC+7" in rendered
    assert "2.0.2&lt;test&gt;" in rendered and "private-pass" not in rendered
    assert ("Сохранённый адрес:" in rendered) == has_proxy
    keyboard = await settings._settings_inline(1001)
    callbacks = {button.callback_data for row in keyboard.inline_keyboard for button in row}
    assert ("set:proxy:disable" in callbacks) == has_proxy
    assert ("set:proxy:check" in callbacks) == has_proxy


@pytest.mark.asyncio
async def test_failure_sending_start_message_releases_update_lock(update_modules):
    notifier, settings, _ = update_modules
    message = types.SimpleNamespace(edit_text=AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        await settings._run_update_flow(message, "1", "2", "start", "done", "failed")
    assert await notifier.try_acquire_update_run() is True
    await notifier.release_update_run()


@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [True, False])
async def test_cancellation_keeps_update_lock_until_file_worker_finishes(update_modules, monkeypatch, manual):
    notifier, settings, _ = update_modules
    started, release = threading.Event(), threading.Event()

    def download():
        started.set()
        assert release.wait(5)
        return False

    module = settings if manual else notifier
    monkeypatch.setattr(module, "begin_operation", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "download_and_extract_github_repo", download)
    message = types.SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock())
    operation = (settings._run_update_flow(message, "1", "2", "start", "done", "failed")
                 if manual else notifier._run_auto_update([1001], "1", "2"))
    task = asyncio.create_task(operation)
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # Repeated cancellation must not release file ownership early.
        await asyncio.sleep(0)
        assert not task.done()
        assert not await notifier.try_acquire_update_run()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert await notifier.try_acquire_update_run()
    await notifier.release_update_run()


@pytest.mark.asyncio
async def test_failed_exec_restores_stopped_clients(update_modules, monkeypatch, offline_module):
    _, _, manager = update_modules
    module = offline_module("core/process_control.py")
    client = types.SimpleNamespace(is_initialized=True, is_connected=True)

    async def stop():
        client.is_initialized = False
        client.is_connected = False

    async def start():
        client.is_initialized = True
        client.is_connected = True

    client.stop = AsyncMock(side_effect=stop)
    client.start = AsyncMock(side_effect=start)
    await manager.add(client)
    monkeypatch.setattr(module, "restart_current_process", Mock(side_effect=OSError("exec failed")))
    with pytest.raises(OSError):
        await module.restart_with_clients()
    client.stop.assert_awaited_once()
    client.start.assert_awaited_once()
    assert client.is_initialized
    assert await manager.get_snapshot() == [client]


@pytest.mark.asyncio
async def test_failed_restart_never_starts_previously_inactive_client(update_modules, monkeypatch, offline_module):
    _, _, manager = update_modules
    module = offline_module("core/process_control.py")
    client = types.SimpleNamespace(is_initialized=False, is_connected=False, stop=AsyncMock(), start=AsyncMock())
    await manager.add(client)
    monkeypatch.setattr(module, "restart_current_process", Mock(side_effect=OSError("exec failed")))
    with pytest.raises(OSError):
        await module.restart_with_clients()
    client.start.assert_not_awaited()
    assert await manager.get_snapshot() == [client]


@pytest.mark.asyncio
async def test_manual_update_acknowledges_and_changes_panel_before_network_check(update_modules, monkeypatch):
    _, settings, _ = update_modules
    call = types.SimpleNamespace(answer=AsyncMock(), from_user=types.SimpleNamespace(id=1001),
                                 message=types.SimpleNamespace(edit_text=AsyncMock()))

    async def check(**kwargs):
        call.answer.assert_awaited_once()
        assert "Проверяем обновление" in call.message.edit_text.await_args.kwargs["text"]
        return "available", 1, "2.0.27"

    monkeypatch.setattr(settings, "_get_version_state", check)
    monkeypatch.setattr(settings, "get_local_version", lambda: "2.0.26")
    flow = AsyncMock()
    monkeypatch.setattr(settings, "_run_update_flow", flow)
    await settings.run_update_now_handler(call, types.SimpleNamespace(clear=AsyncMock()))
    flow.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_update_edits_panel_even_when_reporter_exists(update_modules, monkeypatch):
    _, settings, _ = update_modules
    message = types.SimpleNamespace(bot=object(), chat=types.SimpleNamespace(id=1001), edit_text=AsyncMock(), answer=AsyncMock())
    report = types.SimpleNamespace(condition=threading.Condition(), message_ids={},
                                   update=Mock(), finish=Mock(), fail=Mock())
    monkeypatch.setattr(settings, "begin_operation", lambda *args, **kwargs: report)
    announce = AsyncMock()
    monkeypatch.setattr(settings, "announce_update", announce)

    def download(*, progress):
        message.edit_text.assert_awaited_once()
        assert message.edit_text.await_args.kwargs["reply_markup"] is None
        assert progress == report.update
        announce.assert_awaited_once_with(message.bot, report, "1", "2")
        return False

    monkeypatch.setattr(settings, "download_and_extract_github_repo", download)
    await settings._run_update_flow(message, "1", "2", "start", "done", "failed")
    report.finish.assert_called_once()


@pytest.mark.asyncio
async def test_close_startup_notice_deletes_only_the_clicked_log(update_modules, monkeypatch):
    _, settings, _ = update_modules
    report = types.SimpleNamespace(dismiss=Mock())
    monkeypatch.setattr(settings, "current_reporter", lambda: report)
    message = types.SimpleNamespace(chat=types.SimpleNamespace(id=1001), message_id=500, delete=AsyncMock())
    call = types.SimpleNamespace(message=message, answer=AsyncMock())
    await settings.startup_notice_close_handler(call)
    report.dismiss.assert_called_once_with(1001, 500)
    message.delete.assert_awaited_once()
    call.answer.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [True, False])
async def test_callback_acknowledgement_ignores_only_expired_queries(expired):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import AnswerCallbackQuery
    from utils.callback_answers import answer_callback
    error = TelegramBadRequest(method=AnswerCallbackQuery(callback_query_id="synthetic"),
                               message="query is too old and response timeout expired" if expired else "other bad request")
    call = types.SimpleNamespace(answer=AsyncMock(side_effect=error))
    if expired:
        await answer_callback(call)
    else:
        with pytest.raises(TelegramBadRequest):
            await answer_callback(call)
