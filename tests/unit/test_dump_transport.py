from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, "start", "send"])
async def test_dump_transport_uses_bot_token_and_always_closes_client(offline_module, monkeypatch, tmp_path, fails):
    module = offline_module("services/chat_dump.py")
    path = tmp_path / "dump.zip"
    path.write_bytes(b"synthetic cipher archive")
    client = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError() if fails == "start" else None),
                             send_document=AsyncMock(side_effect=RuntimeError() if fails == "send" else None))
    factory = Mock(return_value=client)
    close = AsyncMock()
    monkeypatch.setattr(module, "close_partial_client", close)
    async def send(method, owner_id, key, title, **kwargs):
        return await method(chat_id=owner_id, message_thread_id=77, **kwargs)
    monkeypatch.setattr(module, "delivery", lambda _: SimpleNamespace(send=send))
    bot = SimpleNamespace(id=123456, token="synthetic-bot-token")
    app = SimpleNamespace(user_id=123, app_id=42, api_hash="synthetic-api-hash")
    if fails:
        with pytest.raises(RuntimeError):
            await module.send_chat_dump(bot, 123, path, "caption", app, client_factory=factory)
    else:
        await module.send_chat_dump(bot, 123, path, "caption", app, client_factory=factory)
    assert factory.call_args.kwargs["bot_token"] == bot.token
    assert factory.call_args.kwargs["in_memory"] is True
    assert factory.call_args.kwargs["no_updates"] is True
    assert "phone_number" not in factory.call_args.kwargs
    if fails == "start":
        client.send_document.assert_not_awaited()
    else:
        assert client.send_document.await_args.kwargs["message_thread_id"] == 77
    close.assert_awaited_once_with(client)
