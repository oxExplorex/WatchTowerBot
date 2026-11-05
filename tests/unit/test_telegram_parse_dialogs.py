from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock

import pytest

from core.session_manager import SessionManager


async def _noop_send_message(*args, **kwargs):
    _ = (args, kwargs)


@pytest.fixture
def parser_mod(monkeypatch, offline_module):
    loader_stub = types.ModuleType("loader")
    loader_stub.session_manager = SessionManager()
    loader_stub.bot = types.SimpleNamespace(send_message=_noop_send_message)
    monkeypatch.setitem(sys.modules, "loader", loader_stub)
    module = offline_module("aiotask/telegram_parse_dialogs.py")
    limits = types.SimpleNamespace(blocked_until=AsyncMock(return_value=0), defer=AsyncMock(), observe_heads=AsyncMock())
    monkeypatch.setattr(module, "HistoryRepository", lambda factory: limits)
    return module


class _FakeClient:
    def __init__(self, dialogs: list[int]):
        self._dialogs = dialogs

    async def get_dialogs_count(self):
        return len(self._dialogs)

    async def get_dialogs(self, limit: int = 0):
        _ = limit
        for chat_id in self._dialogs:
            chat = types.SimpleNamespace(
                id=chat_id,
                username=f"user{chat_id}",
                full_name=f"User {chat_id}",
                title=None,
                type="private",
            )
            yield types.SimpleNamespace(chat=chat)


@pytest.mark.asyncio
async def test_safe_call_retries_timeout_error(parser_mod):
    calls = 0

    async def _flaky_call():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("Request timed out")
        return 42

    result = await parser_mod.safe_call(_flaky_call, retries=2, delay=0)

    assert result == 42
    assert calls == 2


@pytest.mark.asyncio
async def test_shared_floodwait_stops_retries_and_delays_other_background_work(parser_mod):
    from pyrogram.errors import FloodWait

    deferred = AsyncMock()
    request = AsyncMock(side_effect=FloodWait(900))
    with pytest.raises(FloodWait):
        await parser_mod.safe_call(request, on_flood=deferred)
    request.assert_awaited_once()
    deferred.assert_awaited_once_with(900)


def _account(**kwargs):
    defaults = dict(
        uuid="acc-uuid",
        admin_id=5001,
        user_id=9001,
        is_active=1,
        last_dialogs_count=-1,
        last_full_dialogs_scan=0,
        alert_bot=1,
        alert_new_chat=0,
        alert_new_chat_id=1,
        alert_del_chat=0,
        alert_del_chat_id=1,
        pending_delete_signature=None,
        pending_delete_count=0,
    )
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_baseline_sync_no_new_chat_spam(monkeypatch, parser_mod):
    fake_client = _FakeClient([11, 22, 33])

    created: list[int] = []
    presence = AsyncMock()
    sent = []
    
    async def _get_account_by_number(_):
        return _account()

    async def _get_dump_chat_admin_all(_):
        return []

    async def _create_dump_chat_user(admin_id, chat_id):
        _ = admin_id
        created.append(chat_id)
        return True

    async def _update_user(*args, **kwargs):
        _ = (args, kwargs)

    async def _update_account_uuid(*args, **kwargs):
        _ = (args, kwargs)

    async def _add_account_health_event(*args, **kwargs):
        _ = (args, kwargs)

    async def _remove_client_from_runtime(*args, **kwargs):
        _ = (args, kwargs)

    async def _send_message(*args, **kwargs):
        sent.append((args, kwargs))

    monkeypatch.setattr(parser_mod, "Client", _FakeClient)
    await parser_mod.session_manager.add(fake_client)
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda _: "79000000001")
    monkeypatch.setattr(parser_mod, "get_account_by_number", _get_account_by_number)
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", _get_dump_chat_admin_all)
    monkeypatch.setattr(parser_mod, "create_dump_chat_user", _create_dump_chat_user)
    monkeypatch.setattr(parser_mod, "record_chat_presence", presence)
    monkeypatch.setattr(parser_mod, "update_user", _update_user)
    monkeypatch.setattr(parser_mod, "update_account_uuid", _update_account_uuid)
    monkeypatch.setattr(parser_mod, "add_account_health_event", _add_account_health_event)
    monkeypatch.setattr(parser_mod, "remove_client_from_runtime", _remove_client_from_runtime)
    monkeypatch.setattr(parser_mod.bot, "send_message", _send_message)

    await parser_mod.__tg_parse_dialogs_handler()

    assert sorted(created) == [11, 22, 33]
    presence.assert_not_awaited()
    assert sent == []


@pytest.mark.asyncio
async def test_mass_delete_guard_first_scan_blocks_deletes(monkeypatch, parser_mod):
    existing_ids = list(range(1, 41))
    seen_ids = list(range(1, 11))
    fake_client = _FakeClient(seen_ids)

    deleted: list[int] = []
    updated_kwargs = {}

    async def _update_account_uuid(*args, **kwargs):
        updated_kwargs.update(kwargs)
        return None
    
    async def _get_account_by_number(_):
        return _account(last_dialogs_count=0)

    async def _get_dump_chat_admin_all(_):
        return [types.SimpleNamespace(chat_id=x) for x in existing_ids]

    async def _update_user(*args, **kwargs):
        _ = (args, kwargs)

    async def _record_chat_presence(admin_id, chat_id, owner_id, *, present, date):
        if not present:
            deleted.append(chat_id)
        return True

    async def _create_dump_chat_user(*args, **kwargs):
        _ = (args, kwargs)
        return True

    async def _get_user(chat_id):
        return types.SimpleNamespace(username=f"u{chat_id}", full_name=f"n{chat_id}")

    async def _add_account_health_event(*args, **kwargs):
        _ = (args, kwargs)

    async def _remove_client_from_runtime(*args, **kwargs):
        _ = (args, kwargs)

    monkeypatch.setattr(parser_mod, "Client", _FakeClient)
    await parser_mod.session_manager.add(fake_client)
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda _: "79000000002")
    monkeypatch.setattr(parser_mod, "get_account_by_number", _get_account_by_number)
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", _get_dump_chat_admin_all)
    monkeypatch.setattr(parser_mod, "update_user", _update_user)
    monkeypatch.setattr(parser_mod, "record_chat_presence", _record_chat_presence)
    monkeypatch.setattr(parser_mod, "create_dump_chat_user", _create_dump_chat_user)
    monkeypatch.setattr(parser_mod, "get_user", _get_user)
    monkeypatch.setattr(parser_mod, "update_account_uuid", _update_account_uuid)
    monkeypatch.setattr(parser_mod, "add_account_health_event", _add_account_health_event)
    monkeypatch.setattr(parser_mod, "remove_client_from_runtime", _remove_client_from_runtime)

    await parser_mod.__tg_parse_dialogs_handler()

    assert deleted == []
    assert updated_kwargs.get("pending_delete_signature")
    assert int(updated_kwargs.get("pending_delete_count", 0)) >= 10


@pytest.mark.asyncio
async def test_mass_delete_confirmed_on_second_scan(monkeypatch, parser_mod):
    existing_ids = list(range(1, 41))
    seen_ids = list(range(1, 11))
    deleted_expected = sorted(set(existing_ids) - set(seen_ids))
    signature = parser_mod._ids_signature(set(deleted_expected))
    fake_client = _FakeClient(seen_ids)

    deleted: list[int] = []
    
    async def _get_account_by_number(_):
        return _account(
            last_dialogs_count=len(seen_ids),
            last_full_dialogs_scan=parser_mod.DateTime().timestamp(),
            pending_delete_signature=signature,
            pending_delete_count=len(deleted_expected),
        )

    async def _get_dump_chat_admin_all(_):
        return [types.SimpleNamespace(chat_id=x) for x in existing_ids]

    async def _update_user(*args, **kwargs):
        _ = (args, kwargs)

    async def _record_chat_presence(admin_id, chat_id, owner_id, *, present, date):
        if not present:
            deleted.append(chat_id)
        return True

    async def _create_dump_chat_user(*args, **kwargs):
        _ = (args, kwargs)
        return True

    async def _get_user(chat_id):
        return types.SimpleNamespace(username=f"u{chat_id}", full_name=f"n{chat_id}")

    async def _update_account_uuid(*args, **kwargs):
        _ = (args, kwargs)

    async def _add_account_health_event(*args, **kwargs):
        _ = (args, kwargs)

    async def _remove_client_from_runtime(*args, **kwargs):
        _ = (args, kwargs)

    monkeypatch.setattr(parser_mod, "Client", _FakeClient)
    await parser_mod.session_manager.add(fake_client)
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda _: "79000000003")
    monkeypatch.setattr(parser_mod, "get_account_by_number", _get_account_by_number)
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", _get_dump_chat_admin_all)
    monkeypatch.setattr(parser_mod, "update_user", _update_user)
    monkeypatch.setattr(parser_mod, "record_chat_presence", _record_chat_presence)
    monkeypatch.setattr(parser_mod, "create_dump_chat_user", _create_dump_chat_user)
    monkeypatch.setattr(parser_mod, "get_user", _get_user)
    monkeypatch.setattr(parser_mod, "update_account_uuid", _update_account_uuid)
    monkeypatch.setattr(parser_mod, "add_account_health_event", _add_account_health_event)
    monkeypatch.setattr(parser_mod, "remove_client_from_runtime", _remove_client_from_runtime)

    await parser_mod.__tg_parse_dialogs_handler()

    assert sorted(deleted) == deleted_expected


@pytest.mark.asyncio
async def test_removed_session_is_not_scanned(monkeypatch, parser_mod):
    fake_client = _FakeClient([11])
    monkeypatch.setattr(parser_mod, "Client", _FakeClient)
    lookup = AsyncMock()
    monkeypatch.setattr(parser_mod, "get_account_by_number", lookup)
    await parser_mod.session_manager.add(fake_client)
    await parser_mod.session_manager.remove(fake_client)
    await parser_mod.__tg_parse_dialogs_handler()
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_empty_dialog_list_is_not_treated_as_uninitialized(monkeypatch, parser_mod):
    client = _FakeClient([])
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda _: "offline")
    monkeypatch.setattr(parser_mod, "get_account_by_number", AsyncMock(return_value=_account(
        last_dialogs_count=0, last_full_dialogs_scan=parser_mod.DateTime().timestamp())))
    full_scan = AsyncMock()
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", full_scan)
    await parser_mod._scan_session(client)
    full_scan.assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_client_loads_peers_once_despite_unchanged_dialog_count(monkeypatch, parser_mod):
    class CountedClient(_FakeClient):
        scans = 0
        async def get_dialogs(self, limit=0):
            self.scans += 1
            async for dialog in super().get_dialogs(limit):
                yield dialog
    client = CountedClient([11, 22])
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda _: "offline")
    monkeypatch.setattr(parser_mod, "get_account_by_number", AsyncMock(return_value=_account(
        last_dialogs_count=2, last_full_dialogs_scan=parser_mod.DateTime().timestamp())))
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", AsyncMock(return_value=[
        types.SimpleNamespace(chat_id=11), types.SimpleNamespace(chat_id=22)]))
    monkeypatch.setattr(parser_mod, "update_user", AsyncMock())
    monkeypatch.setattr(parser_mod, "update_account_uuid", AsyncMock())
    monkeypatch.setattr(parser_mod, "add_account_health_event", AsyncMock())
    await parser_mod._scan_session(client)
    assert client.scans == 1 and client._watchtower_dialogs_loaded
    await parser_mod._scan_session(client)
    assert client.scans == 1


@pytest.mark.asyncio
async def test_stopping_during_partial_scan_does_not_record_false_deletions(monkeypatch, parser_mod):
    started = asyncio.Event()

    class PartialClient(_FakeClient):
        async def get_dialogs(self, limit=0):
            yield types.SimpleNamespace(chat=types.SimpleNamespace(
                id=1, username="offline", full_name="Offline", title=None, type="private"))
            started.set()
            await asyncio.Future()

    active = PartialClient([1, 2, 3])
    monkeypatch.setattr(parser_mod, "Client", PartialClient)
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda client: "offline")
    monkeypatch.setattr(parser_mod, "get_account_by_number", AsyncMock(return_value=_account()))
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", AsyncMock(return_value=[
        types.SimpleNamespace(chat_id=value) for value in (1, 2, 3)]))
    deleted = AsyncMock()
    drop = AsyncMock()
    monkeypatch.setattr(parser_mod, "record_chat_presence", deleted)
    monkeypatch.setattr(parser_mod, "delete_account_by_number", drop)
    await parser_mod.session_manager.add(active)
    scanning = asyncio.create_task(parser_mod.__tg_parse_dialogs_handler())
    async with asyncio.timeout(2):
        await started.wait()
        await parser_mod.session_manager.stop(active, AsyncMock())
        await scanning
    deleted.assert_not_awaited()
    drop.assert_not_awaited()
