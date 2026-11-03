import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


def temporary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data/session").mkdir(parents=True)
    base = f"data/session/_auth_1001_79000000001_{uuid4().hex}"
    Path(base + ".session").write_bytes(b"synthetic authorization")
    Path("data/session/79000000001.session").write_bytes(b"existing authorization")
    return base


def fake_client():
    storage = SimpleNamespace(conn=object())

    async def close_storage():
        storage.conn = None

    storage.close = AsyncMock(side_effect=close_storage)
    active = SimpleNamespace(is_initialized=False, is_connected=True, storage=storage)

    async def disconnect():
        await storage.close()
        active.is_connected = False

    active.stop = AsyncMock(side_effect=ConnectionError("Client is already terminated"))
    active.disconnect = AsyncMock(side_effect=disconnect)
    return active


@pytest.mark.asyncio
@pytest.mark.parametrize("connected", [False, True])
async def test_shutdown_closes_temporary_clients_even_without_completed_fsm_save(tmp_path, monkeypatch, offline_module, connected):
    module = offline_module("core/auth_sessions.py")
    registry = module.TemporaryClients()
    base = temporary(tmp_path, monkeypatch)
    active = fake_client()
    active.is_connected = connected
    state = SimpleNamespace(clear=AsyncMock())
    registry.register(active, base, state)
    await registry.close_all()
    active.storage.close.assert_awaited_once()
    state.clear.assert_awaited_once()
    assert not Path(base + ".session").exists()
    assert Path("data/session/79000000001.session").read_bytes() == b"existing authorization"


@pytest.mark.asyncio
async def test_restart_cancels_and_joins_connecting_authorization_before_cleanup(tmp_path, monkeypatch, offline_module):
    module = offline_module("core/auth_sessions.py")
    registry = module.TemporaryClients()
    base = temporary(tmp_path, monkeypatch)
    active = fake_client()
    state = SimpleNamespace(clear=AsyncMock())
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def authorize():
        registry.register(active, base, state)
        started.set()
        try:
            await asyncio.Future()
        finally:
            await registry.discard(active)
            cleaned.set()

    operation = asyncio.create_task(authorize())
    await started.wait()
    async with asyncio.timeout(2):
        await registry.close_all()
    assert operation.cancelled() and cleaned.is_set()
    assert not Path(base + ".session").exists()
    state.clear.assert_awaited_once()
    with pytest.raises(RuntimeError, match="shutting down"):
        registry.register(fake_client(), base)
    registry.resume()
    assert Path("data/session/79000000001.session").read_bytes() == b"existing authorization"


@pytest.mark.asyncio
async def test_failed_temporary_close_is_retained_for_retry(tmp_path, monkeypatch, offline_module):
    module = offline_module("core/auth_sessions.py")
    registry = module.TemporaryClients()
    base = temporary(tmp_path, monkeypatch)
    active = fake_client()
    disconnect = active.disconnect
    active.disconnect = AsyncMock(side_effect=RuntimeError("offline disconnect failed"))
    registry.register(active, base)
    with pytest.raises(RuntimeError, match="Failed to close"):
        await registry.close_all()
    assert Path(base + ".session").exists()
    active.disconnect = disconnect
    await registry.close_all()
    assert not Path(base + ".session").exists()


@pytest.mark.asyncio
async def test_temporary_cleanup_rejects_normal_session_paths(tmp_path, monkeypatch, offline_module):
    module = offline_module("core/auth_sessions.py")
    temporary(tmp_path, monkeypatch)
    registry = module.TemporaryClients()
    with pytest.raises(ValueError):
        registry.register(fake_client(), "data/session/79000000001")
    with pytest.raises(ValueError):
        await module.discard_session_files("data/session/79000000001")
    assert Path("data/session/79000000001.session").read_bytes() == b"existing authorization"


@pytest.mark.asyncio
@pytest.mark.parametrize("leave_dialog", [False, True])
async def test_leaving_any_menu_closes_fsm_client_but_waiting_for_code_keeps_it(tmp_path, monkeypatch, offline_module, leave_dialog):
    module = offline_module("core/auth_sessions.py")
    registry = module.TemporaryClients()
    base = temporary(tmp_path, monkeypatch)
    active = fake_client()
    state = SimpleNamespace(get_data=AsyncMock(side_effect=[{"app_temp": active},
        {} if leave_dialog else {"app_temp": active}]), clear=AsyncMock())
    registry.register(active, base, state)
    middleware = offline_module("middlewares/auth_session_cleanup.py")
    monkeypatch.setattr(middleware, "auth_clients", registry)
    handler = AsyncMock(return_value="handled")
    result = await middleware.AuthSessionCleanupMiddleware()(handler,
        SimpleNamespace(message=object(), callback_query=None), {"state": state})
    assert result == "handled"
    assert active.is_connected is not leave_dialog
    assert Path(base + ".session").exists() is not leave_dialog
    await registry.close_all()
