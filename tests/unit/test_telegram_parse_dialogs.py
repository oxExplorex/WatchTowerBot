from __future__ import annotations

import importlib
import sys
import types

import pytest


class _RouterStub:
    def _decorator_factory(self, *args, **kwargs):
        _ = (args, kwargs)

        def _decorator(fn):
            return fn

        return _decorator

    def include_router(self, *args, **kwargs):
        _ = (args, kwargs)
        return None

    def __getattr__(self, _name):
        return self._decorator_factory


async def _noop_send_message(*args, **kwargs):
    _ = (args, kwargs)


loader_stub = types.ModuleType("loader")
loader_stub.apps_session = []
loader_stub.bot = types.SimpleNamespace(send_message=_noop_send_message)
loader_stub.router = _RouterStub()
sys.modules["loader"] = loader_stub

parser_mod = importlib.import_module("aiotask.telegram_parse_dialogs")


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
async def test_baseline_sync_no_new_chat_spam(monkeypatch):
    fake_client = _FakeClient([11, 22, 33])

    created: list[int] = []
    history_added: list[int] = []
    sent = []
    
    async def _get_account_by_number(_):
        return _account()

    async def _get_dump_chat_admin_all(_):
        return []

    async def _create_dump_chat_user(admin_id, chat_id):
        _ = admin_id
        created.append(chat_id)
        return True

    async def _add_chat_history_event(**kwargs):
        history_added.append(kwargs.get("chat_id"))

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
    monkeypatch.setattr(parser_mod, "apps_session", [fake_client])
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda _: "79000000001")
    monkeypatch.setattr(parser_mod, "get_account_by_number", _get_account_by_number)
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", _get_dump_chat_admin_all)
    monkeypatch.setattr(parser_mod, "create_dump_chat_user", _create_dump_chat_user)
    monkeypatch.setattr(parser_mod, "add_chat_history_event", _add_chat_history_event)
    monkeypatch.setattr(parser_mod, "update_user", _update_user)
    monkeypatch.setattr(parser_mod, "update_account_uuid", _update_account_uuid)
    monkeypatch.setattr(parser_mod, "add_account_health_event", _add_account_health_event)
    monkeypatch.setattr(parser_mod, "remove_client_from_runtime", _remove_client_from_runtime)
    monkeypatch.setattr(parser_mod.bot, "send_message", _send_message)

    await parser_mod.__tg_parse_dialogs_handler()

    assert sorted(created) == [11, 22, 33]
    assert history_added == []
    assert sent == []


@pytest.mark.asyncio
async def test_mass_delete_guard_first_scan_blocks_deletes(monkeypatch):
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

    async def _del_dump_chat_user(admin_id, chat_id):
        _ = admin_id
        deleted.append(chat_id)
        return True

    async def _create_dump_chat_user(*args, **kwargs):
        _ = (args, kwargs)
        return True

    async def _add_chat_history_event(*args, **kwargs):
        _ = (args, kwargs)

    async def _get_user(chat_id):
        return types.SimpleNamespace(username=f"u{chat_id}", full_name=f"n{chat_id}")

    async def _add_account_health_event(*args, **kwargs):
        _ = (args, kwargs)

    async def _remove_client_from_runtime(*args, **kwargs):
        _ = (args, kwargs)

    monkeypatch.setattr(parser_mod, "Client", _FakeClient)
    monkeypatch.setattr(parser_mod, "apps_session", [fake_client])
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda _: "79000000002")
    monkeypatch.setattr(parser_mod, "get_account_by_number", _get_account_by_number)
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", _get_dump_chat_admin_all)
    monkeypatch.setattr(parser_mod, "update_user", _update_user)
    monkeypatch.setattr(parser_mod, "del_dump_chat_user", _del_dump_chat_user)
    monkeypatch.setattr(parser_mod, "create_dump_chat_user", _create_dump_chat_user)
    monkeypatch.setattr(parser_mod, "add_chat_history_event", _add_chat_history_event)
    monkeypatch.setattr(parser_mod, "get_user", _get_user)
    monkeypatch.setattr(parser_mod, "update_account_uuid", _update_account_uuid)
    monkeypatch.setattr(parser_mod, "add_account_health_event", _add_account_health_event)
    monkeypatch.setattr(parser_mod, "remove_client_from_runtime", _remove_client_from_runtime)

    await parser_mod.__tg_parse_dialogs_handler()

    assert deleted == []
    assert updated_kwargs.get("pending_delete_signature")
    assert int(updated_kwargs.get("pending_delete_count", 0)) >= 10


@pytest.mark.asyncio
async def test_mass_delete_confirmed_on_second_scan(monkeypatch):
    existing_ids = list(range(1, 41))
    seen_ids = list(range(1, 11))
    deleted_expected = sorted(set(existing_ids) - set(seen_ids))
    signature = parser_mod._ids_signature(set(deleted_expected))
    fake_client = _FakeClient(seen_ids)

    deleted: list[int] = []
    
    async def _get_account_by_number(_):
        return _account(
            last_dialogs_count=0,
            pending_delete_signature=signature,
            pending_delete_count=len(deleted_expected),
        )

    async def _get_dump_chat_admin_all(_):
        return [types.SimpleNamespace(chat_id=x) for x in existing_ids]

    async def _update_user(*args, **kwargs):
        _ = (args, kwargs)

    async def _del_dump_chat_user(admin_id, chat_id):
        _ = admin_id
        deleted.append(chat_id)
        return True

    async def _create_dump_chat_user(*args, **kwargs):
        _ = (args, kwargs)
        return True

    async def _add_chat_history_event(*args, **kwargs):
        _ = (args, kwargs)

    async def _get_user(chat_id):
        return types.SimpleNamespace(username=f"u{chat_id}", full_name=f"n{chat_id}")

    async def _update_account_uuid(*args, **kwargs):
        _ = (args, kwargs)

    async def _add_account_health_event(*args, **kwargs):
        _ = (args, kwargs)

    async def _remove_client_from_runtime(*args, **kwargs):
        _ = (args, kwargs)

    monkeypatch.setattr(parser_mod, "Client", _FakeClient)
    monkeypatch.setattr(parser_mod, "apps_session", [fake_client])
    monkeypatch.setattr(parser_mod, "session_number_from_client", lambda _: "79000000003")
    monkeypatch.setattr(parser_mod, "get_account_by_number", _get_account_by_number)
    monkeypatch.setattr(parser_mod, "get_dump_chat_admin_all", _get_dump_chat_admin_all)
    monkeypatch.setattr(parser_mod, "update_user", _update_user)
    monkeypatch.setattr(parser_mod, "del_dump_chat_user", _del_dump_chat_user)
    monkeypatch.setattr(parser_mod, "create_dump_chat_user", _create_dump_chat_user)
    monkeypatch.setattr(parser_mod, "add_chat_history_event", _add_chat_history_event)
    monkeypatch.setattr(parser_mod, "get_user", _get_user)
    monkeypatch.setattr(parser_mod, "update_account_uuid", _update_account_uuid)
    monkeypatch.setattr(parser_mod, "add_account_health_event", _add_account_health_event)
    monkeypatch.setattr(parser_mod, "remove_client_from_runtime", _remove_client_from_runtime)

    await parser_mod.__tg_parse_dialogs_handler()

    assert sorted(deleted) == deleted_expected
