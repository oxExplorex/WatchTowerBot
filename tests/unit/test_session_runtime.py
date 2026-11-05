from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock

import pytest

from core.session_manager import SessionManager


@pytest.fixture
def runtime(monkeypatch, offline_module):
    loader = types.ModuleType("loader")
    loader.session_manager = SessionManager()
    monkeypatch.setitem(sys.modules, "loader", loader)
    return offline_module("core/session_runtime.py"), loader.session_manager


def client(number, *, connected=True, initialized=True):
    return types.SimpleNamespace(
        name=f"data/session/{number}",
        is_connected=connected,
        is_initialized=initialized,
        stop=AsyncMock(),
        disconnect=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_one_unknown_session_does_not_prevent_other_clients_starting(runtime, monkeypatch, caplog):
    from core.session_schema import SessionSchemaError
    module, manager = runtime
    broken, healthy = client("111"), client("222")
    started = []
    async def start(value):
        if value is broken:
            raise SessionSchemaError(["unknown"])
        started.append(value)
    monkeypatch.setattr(module, "start_client", start)
    await module.start_all_clients([broken, healthy])
    assert started == [healthy]
    assert "manual reauthorization" in caplog.text


@pytest.mark.asyncio
async def test_lookup_and_status_use_current_registry(runtime):
    module, manager = runtime
    active = client("111")
    inactive = client("222", connected=False, initialized=False)
    await manager.extend([active, inactive])
    assert await module.get_client_by_number("111") is active
    assert await module.get_client_by_number("222") is inactive
    assert await module.is_session_running("111") is True
    assert await module.is_session_running("222") is False
    assert await module.is_session_running("") is False
    assert await module.get_client_by_number("missing") is None
    await manager.remove(active)
    assert await module.get_client_by_number("111") is None
    assert await module.is_session_running("111") is False


@pytest.mark.asyncio
async def test_stop_and_remove_affects_only_matching_number(runtime):
    module, manager = runtime
    removed = client("111")
    retained = client("222")
    await manager.extend([removed, retained])
    assert await module.stop_and_remove_session("111") is True
    removed.stop.assert_awaited_once()
    retained.stop.assert_not_awaited()
    assert await manager.get_snapshot() == [retained]
    assert await module.stop_and_remove_session("111") is False
    assert await module.stop_and_remove_session("") is False


@pytest.mark.asyncio
async def test_remove_client_updates_the_shared_registry(runtime):
    module, manager = runtime
    removed = client("111")
    await manager.add(removed)
    await module.remove_client_from_runtime(removed)
    removed.stop.assert_awaited_once()
    assert await manager.count() == 0


@pytest.mark.asyncio
async def test_stop_all_keeps_clients_added_after_snapshot(runtime):
    module, manager = runtime
    original = client("111")
    added = client("222")
    started = asyncio.Event()
    finish = asyncio.Event()

    async def stop_original():
        started.set()
        await finish.wait()

    original.stop.side_effect = stop_original
    await manager.add(original)
    stopping = asyncio.create_task(module.stop_all_clients())
    await started.wait()
    await manager.add(added)
    finish.set()
    assert await stopping == 1
    assert await manager.get_snapshot() == [added]
    added.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_all_can_preserve_registry(runtime):
    module, manager = runtime
    retained = client("111")
    await manager.add(retained)
    assert await module.stop_all_clients(clear_runtime=False) == 1
    retained.stop.assert_awaited_once()
    assert await manager.get_snapshot() == [retained]


@pytest.mark.asyncio
async def test_restart_closes_initialized_clients_instead_of_only_forgetting_them(runtime):
    module, manager = runtime
    initialized = client("111")
    connected = client("222", initialized=False)
    await manager.extend([initialized, connected])
    assert await module.stop_all_clients(for_restart=True) == 2
    initialized.stop.assert_awaited_once()
    initialized.disconnect.assert_not_awaited()
    connected.stop.assert_awaited_once()
    assert await manager.count() == 0


@pytest.mark.asyncio
async def test_failed_stop_keeps_failed_client_registered(runtime):
    module, manager = runtime
    failing = client("111")
    failing.stop.side_effect = RuntimeError("offline stop error")
    other = client("222")
    await manager.extend([failing, other])
    with pytest.raises(RuntimeError, match="Failed to stop"):
        await module.stop_all_clients()
    other.stop.assert_awaited_once()
    assert await manager.get_snapshot() == [failing]
