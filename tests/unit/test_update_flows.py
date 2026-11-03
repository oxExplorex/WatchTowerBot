from pathlib import Path
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
async def test_failure_sending_start_message_releases_update_lock(update_modules):
    notifier, settings, _ = update_modules
    message = types.SimpleNamespace(edit_text=AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        await settings._run_update_flow(message, "1", "2", "start", "done", "failed")
    assert await notifier.try_acquire_update_run() is True
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
