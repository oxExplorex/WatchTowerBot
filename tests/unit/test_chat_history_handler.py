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


loader_stub = types.ModuleType("loader")
loader_stub.router = _RouterStub()
loader_stub.apps_session = []
loader_stub.bot = types.SimpleNamespace()
sys.modules["loader"] = loader_stub

handler_mod = importlib.import_module("handlers.admin.panel.chat_history_handler")


class _FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.from_user = types.SimpleNamespace(id=5001)
        self.sent: list[str] = []

    async def answer(self, text: str):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_send_chunked_splits_long_text():
    message = _FakeMessage()
    lines = [f"line-{i}" for i in range(100)]
    text = "\n".join(lines)
    await handler_mod._send_chunked(message, text, chunk_size=120)
    assert len(message.sent) > 1
    assert "line-0" in message.sent[0]


@pytest.mark.asyncio
async def test_current_presence_lines_masks_account_ids(monkeypatch):
    async def _get_account_all(active_only=False):
        _ = active_only
        return [
            types.SimpleNamespace(admin_id=5001, user_id=111111),
            types.SimpleNamespace(admin_id=5001, user_id=222222),
        ]

    async def _get_dump_chat_user(owner_user_id, chat_id):
        return object() if (owner_user_id == 111111 and chat_id == 70001) else None

    async def _get_user(user_id):
        if user_id in (111111, 222222):
            return types.SimpleNamespace(full_name="Account Holder", username=None)
        return types.SimpleNamespace(full_name="Target User", username=None)

    monkeypatch.setattr(handler_mod, "get_account_all", _get_account_all)
    monkeypatch.setattr(handler_mod, "get_dump_chat_user", _get_dump_chat_user)
    monkeypatch.setattr(handler_mod, "get_user", _get_user)

    lines = await handler_mod._current_presence_lines(admin_id=5001, chat_ids=[70001])
    rendered = "\n".join(lines)
    assert "есть у:" in rendered
    assert "[11**11]" in rendered
    assert "[" in rendered and "]" in rendered


@pytest.mark.asyncio
async def test_render_history_shows_presence_even_without_events(monkeypatch):
    message = _FakeMessage(text="/chat_history 777")

    async def _resolve_chat_ids(query: str):
        _ = query
        return [777]

    async def _presence_lines(admin_id: int, chat_ids: list[int]):
        _ = (admin_id, chat_ids)
        return ["<b>Сейчас в чатах</b>", "user_id <code>777</code> | есть у: name [11***22]", ""]

    async def _get_chat_history_events(admin_id: int, chat_id: int, limit: int = 250):
        _ = (admin_id, chat_id, limit)
        return []

    async def _get_user_timezone_offset(_):
        return 3

    monkeypatch.setattr(handler_mod, "_resolve_chat_ids", _resolve_chat_ids)
    monkeypatch.setattr(handler_mod, "_current_presence_lines", _presence_lines)
    monkeypatch.setattr(handler_mod, "get_chat_history_events", _get_chat_history_events)
    monkeypatch.setattr(handler_mod, "get_user_timezone_offset", _get_user_timezone_offset)

    await handler_mod._render_history(message, query="777", admin_id=5001)

    joined = "\n".join(message.sent)
    assert "Сейчас в чатах" in joined
    assert "История по запросу не найдена" in joined
