import asyncio
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

from core.session_manager import SessionManager


@pytest_asyncio.fixture
async def authorization(monkeypatch, tmp_path, offline_module):
    root = Path(__file__).resolve().parents[2]
    for name, directory in [("handlers", "handlers"), ("handlers.admin", "handlers/admin")]:
        package = types.ModuleType(name)
        package.__path__ = [str(root / directory)]
        monkeypatch.setitem(sys.modules, name, package)
    loader = types.ModuleType("loader")
    decorator = lambda *args, **kwargs: lambda fn: fn
    loader.router = types.SimpleNamespace(callback_query=decorator, message=decorator)
    loader.bot = AsyncMock()
    loader.session_manager = SessionManager()
    monkeypatch.setitem(sys.modules, "loader", loader)
    module = offline_module("handlers/admin/panel/accounts_add_handler.py")
    monkeypatch.setattr(module, "is_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "get_account_by_number", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "get_account_tg_to_user_id", AsyncMock(return_value=None))
    monkeypatch.setattr(module.AccountOperationsRepository, "is_busy", AsyncMock(return_value=False))
    monkeypatch.chdir(tmp_path)
    Path("data/session").mkdir(parents=True)
    monkeypatch.setattr(module, "not_warning_delete_message", AsyncMock())
    return module


@pytest.mark.asyncio
async def test_failed_code_request_leaves_running_session_untouched(authorization, monkeypatch):
    module = authorization
    Path("data/session/79000000001.session").write_bytes(b"original")
    stop = AsyncMock()
    monkeypatch.setattr(module, "stop_and_remove_session", stop)
    monkeypatch.setattr(module, "get_app_tg_uuid", AsyncMock(return_value=types.SimpleNamespace(app_id=12345, api_hash="synthetic")))
    client = types.SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(), is_connected=True,
                                   send_phone_number_code=AsyncMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(module, "Client", Mock(return_value=client))
    state = types.SimpleNamespace(get_data=AsyncMock(return_value={"uuid_app": "app"}), clear=AsyncMock())
    message = types.SimpleNamespace(from_user=types.SimpleNamespace(id=1001), text="79000000001", answer=AsyncMock())
    await module.receive_account_number_handler(message, state)
    stop.assert_not_awaited()
    assert Path("data/session/79000000001.session").read_bytes() == b"original"


@pytest.mark.asyncio
async def test_failed_database_save_restores_files_and_previous_client(authorization, monkeypatch):
    module = authorization
    Path("data/session/79000000001.session").write_bytes(b"original")
    Path("data/session/temporary.session").write_bytes(b"authorized")
    previous = types.SimpleNamespace(start=AsyncMock(), is_initialized=True, is_connected=True)
    monkeypatch.setattr(module, "get_client_by_number", AsyncMock(return_value=previous))
    async def restart_previous(client):
        await client.start()
    monkeypatch.setattr(module, "start_client", restart_previous)
    monkeypatch.setattr(module, "stop_and_remove_session", AsyncMock())
    transaction = AsyncMock()
    transaction.__aenter__.return_value.accounts.create_account_tg.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(module, "create_unit_of_work", Mock(return_value=transaction))
    data = {"number": "79000000001", "temp_session_name": "data/session/temporary", "uuid_app": "app"}
    with pytest.raises(RuntimeError, match="database unavailable"):
        await module._save_authorized_session(data, types.SimpleNamespace(id=9001), 1001)
    assert Path("data/session/79000000001.session").read_bytes() == b"original"
    previous.start.assert_awaited_once()
    assert await module.session_manager.get_snapshot() == [previous]


@pytest.mark.asyncio
async def test_cancelled_save_also_restores_session(authorization, monkeypatch):
    module = authorization
    Path("data/session/79000000001.session").write_bytes(b"original")
    Path("data/session/temporary.session").write_bytes(b"authorized")
    monkeypatch.setattr(module, "get_client_by_number", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "stop_and_remove_session", AsyncMock())
    transaction = AsyncMock()
    transaction.__aenter__.return_value.accounts.create_account_tg.side_effect = asyncio.CancelledError()
    monkeypatch.setattr(module, "create_unit_of_work", Mock(return_value=transaction))
    data = {"number": "79000000001", "temp_session_name": "data/session/temporary", "uuid_app": "app"}
    with pytest.raises(asyncio.CancelledError):
        await module._save_authorized_session(data, types.SimpleNamespace(id=9001), 1001)
    assert Path("data/session/79000000001.session").read_bytes() == b"original"


@pytest.mark.asyncio
async def test_successful_reauthorization_saves_account_and_promotes_session(db_main, authorization, monkeypatch):
    module = authorization
    await db_main.create_app_tg(1001, 12345, "synthetic", "app")
    apps, _ = await db_main.get_app_tg_user_id(1001)
    Path("data/session/79000000001.session").write_bytes(b"original")
    Path("data/session/temporary.session").write_bytes(b"authorized")
    monkeypatch.setattr(module, "get_client_by_number", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "stop_and_remove_session", AsyncMock())
    monkeypatch.setattr(module, "create_unit_of_work", db_main.create_unit_of_work)
    data = {"number": "79000000001", "temp_session_name": "data/session/temporary", "uuid_app": apps[0].uuid}
    result = types.SimpleNamespace(id=9001, username="new_user", full_name="New User")
    await module._save_authorized_session(data, result, 1001, update_profile=True)
    assert Path("data/session/79000000001.session").read_bytes() == b"authorized"
    assert (await db_main.get_account_by_number("79000000001")).user_id == 9001
    assert (await db_main.get_user(9001)).username == "new_user"
    assert not list(Path("data/session").glob("_session_backup_*"))


@pytest.mark.asyncio
async def test_revoked_owner_cannot_promote_authorized_session(authorization, monkeypatch):
    module = authorization
    Path("data/session/79000000001.session").write_bytes(b"original")
    Path("data/session/temporary.session").write_bytes(b"authorized")
    monkeypatch.setattr(module, "is_admin", AsyncMock(return_value=False))
    stop = AsyncMock()
    monkeypatch.setattr(module, "stop_and_remove_session", stop)
    data = {"number": "79000000001", "temp_session_name": "data/session/temporary", "uuid_app": "app"}
    with pytest.raises(PermissionError):
        await module._save_authorized_session(data, types.SimpleNamespace(id=9001), 1001)
    stop.assert_not_awaited()
    assert Path("data/session/79000000001.session").read_bytes() == b"original"


@pytest.mark.asyncio
async def test_cancellation_before_phone_prompt_cleans_registered_temporary_client(authorization, monkeypatch):
    from core.auth_sessions import TemporaryClients

    module = authorization
    registry = TemporaryClients()
    monkeypatch.setattr(module, "auth_clients", registry)
    Path("data/session/79000000001.session").write_bytes(b"original")
    started = asyncio.Event()
    created = []

    def factory(**options):
        active = types.SimpleNamespace(is_connected=False, is_initialized=False)
        created.append((active, options["name"]))

        async def connect():
            Path(options["name"] + ".session").write_bytes(b"temporary")
            active.is_connected = True

        async def disconnect():
            active.is_connected = False

        async def send_code(**kwargs):
            started.set()
            await asyncio.Future()

        active.connect = connect
        active.disconnect = AsyncMock(side_effect=disconnect)
        active.send_phone_number_code = send_code
        return active

    monkeypatch.setattr(module, "Client", factory)
    monkeypatch.setattr(module, "get_app_tg_uuid", AsyncMock(return_value=types.SimpleNamespace(app_id=1, api_hash="synthetic")))
    state = types.SimpleNamespace(get_data=AsyncMock(return_value={"uuid_app": "app"}), clear=AsyncMock(),
                                  update_data=AsyncMock(), set_state=AsyncMock())
    message = types.SimpleNamespace(from_user=types.SimpleNamespace(id=1001), text="79000000001", answer=AsyncMock())
    operation = asyncio.create_task(module.receive_account_number_handler(message, state))
    async with asyncio.timeout(2):
        await started.wait()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
    created[0][0].disconnect.assert_awaited_once()
    assert not Path(created[0][1] + ".session").exists()
    assert Path("data/session/79000000001.session").read_bytes() == b"original"
    state.update_data.assert_not_awaited()
    state.clear.assert_awaited_once()
