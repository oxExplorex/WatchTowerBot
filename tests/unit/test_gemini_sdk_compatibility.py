from __future__ import annotations

import base64
import json
import sys
import types as namespace_types
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import pytest_asyncio
from google import genai
from google.genai import types


@pytest.fixture
def gemini_module(monkeypatch, offline_module):
    loader = namespace_types.ModuleType("loader")
    loader.gemini_system_instruction = "Offline system instruction"
    monkeypatch.setitem(sys.modules, "loader", loader)
    module = offline_module("handlers_app/user/gemini_handler.py")
    monkeypatch.setattr(module, "GEMINI_KEY", "offline-test-key")
    return module


@pytest_asyncio.fixture
async def sdk_transport(monkeypatch, gemini_module):
    real_client = genai.Client
    state = namespace_types.SimpleNamespace(requests=[], options=[], clients=[], status=200)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_ENTERPRISE", raising=False)

    def respond(request):
        state.requests.append(request)
        if state.status != 200:
            return httpx.Response(
                state.status,
                json={"error": {"code": state.status, "message": "Offline test error", "status": "PERMISSION_DENIED"}},
            )
        return httpx.Response(200, json={
            "candidates": [{"content": {"role": "model", "parts": [{"text": "Ответ Gemini"}]}, "finishReason": "STOP"}],
        })

    def client_factory(*, api_key, http_options=None):
        state.options.append(http_options)
        transport = httpx.MockTransport(respond)
        options = types.HttpOptions(
            base_url="https://generativelanguage.googleapis.com",
            api_version="v1beta",
            httpx_client=httpx.Client(transport=transport, trust_env=False),
            httpx_async_client=httpx.AsyncClient(transport=transport, trust_env=False),
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        client = real_client(api_key=api_key, http_options=options)
        state.clients.append(client)
        return client

    monkeypatch.setattr(genai, "Client", client_factory)
    try:
        yield state
    finally:
        for client in state.clients:
            await client.aio.aclose()
            client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("proxy", [None, "http://127.0.0.1:8080"])
async def test_real_sdk_serializes_text_media_and_configuration(gemini_module, sdk_transport, proxy):
    parts = [types.Part.from_text(text="Проверка"), types.Part.from_bytes(data=b"offline-image", mime_type="image/png")]
    answer = await gemini_module._request_gemini(parts, proxy_url=proxy)
    assert answer == "Ответ Gemini"
    assert len(sdk_transport.requests) == 1
    request = sdk_transport.requests[0]
    assert request.method == "POST"
    assert request.url.path.endswith(f"/{gemini_module._GEMINI_MODEL_NAME}:generateContent")
    body = json.loads(request.content)
    assert body["contents"][0]["parts"][0]["text"] == "Проверка"
    inline_data = body["contents"][0]["parts"][1]["inlineData"]
    assert inline_data["data"] == base64.b64encode(b"offline-image").decode()
    assert types.Blob.model_validate(inline_data).mime_type == "image/png"
    assert body["systemInstruction"]["parts"][0]["text"] == "Offline system instruction"
    assert body["safetySettings"]
    options = sdk_transport.options[0]
    if proxy:
        assert options.client_args["proxy"] == proxy
        assert options.async_client_args["proxy"] == proxy
    else:
        assert options is None


@pytest.mark.asyncio
async def test_api_error_keeps_existing_unavailable_response(monkeypatch, gemini_module, sdk_transport):
    sdk_transport.status = 403
    proxy_config = AsyncMock(return_value={"proxy": None, "enabled": 0})
    health = AsyncMock()
    monkeypatch.setattr(gemini_module, "get_user_gemini_proxy_config", proxy_config)
    monkeypatch.setattr(gemini_module, "set_user_gemini_proxy_health", health)
    answer = await gemini_module._generate_with_gemini(123, [types.Part.from_text(text="test")])
    assert answer == gemini_module.constant_text.GEMINI_UNAVAILABLE_TEXT
    assert len(sdk_transport.requests) == 1
    assert health.await_args.kwargs["is_ok"] is False


@pytest.mark.asyncio
async def test_proxy_transport_error_keeps_existing_direct_retry(monkeypatch, gemini_module):
    monkeypatch.setattr(gemini_module, "get_user_gemini_proxy_config", AsyncMock(return_value={
        "proxy": "http://offline_user:offline_password@127.0.0.1:8080", "enabled": 1,
    }))
    request = AsyncMock(side_effect=[OSError("proxy connection failed"), "direct answer"])
    monkeypatch.setattr(gemini_module, "_request_gemini", request)
    monkeypatch.setattr(gemini_module, "set_user_gemini_proxy_health", AsyncMock())
    assert await gemini_module._generate_with_gemini(123, []) == "direct answer"
    assert request.await_args_list[0].kwargs["proxy_url"] == "http://offline_user:offline_password@127.0.0.1:8080"
    assert request.await_args_list[1].kwargs["proxy_url"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [None, TimeoutError("offline timeout"), RuntimeError("offline API error")])
async def test_proxy_checker_reports_success_timeout_and_error(monkeypatch, offline_module, error):
    module = offline_module("handlers/admin/proxy_manager/proxy_checker.py")
    monkeypatch.setattr(module, "GEMINI_KEY", "offline-test-key")
    generate = AsyncMock(side_effect=error)
    factory = Mock(return_value=namespace_types.SimpleNamespace(aio=namespace_types.SimpleNamespace(
        models=namespace_types.SimpleNamespace(generate_content=generate), aclose=AsyncMock(),
    ), close=Mock()))
    monkeypatch.setattr(genai, "Client", factory)
    health = AsyncMock()
    monkeypatch.setattr(module, "set_user_gemini_proxy_health", health)
    success, reason = await module.check_proxy_now(123, "http://127.0.0.1:8080", "offline_test")
    assert success is (error is None)
    assert reason == ("ok" if error is None else "timeout" if isinstance(error, TimeoutError) else "offline API error")
    assert health.await_args.kwargs["is_ok"] is success
    factory.return_value.aio.aclose.assert_awaited_once()
    factory.return_value.close.assert_called_once()
    options = factory.call_args.kwargs["http_options"]
    assert options.async_client_args["proxy"] == "http://127.0.0.1:8080"


@pytest.mark.asyncio
async def test_real_sdk_accepts_project_proxy_options(monkeypatch):
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_ENTERPRISE", raising=False)
    proxy = "http://offline_user:offline_password@127.0.0.1:8080"
    client = genai.Client(api_key="offline-test-key", http_options=types.HttpOptions(
        client_args={"proxy": proxy}, async_client_args={"proxy": proxy},
    ))
    try:
        assert callable(client.aio.models.generate_content)
    finally:
        await client.aio.aclose()
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_observed_account_alone_does_not_authorize_userbot_commands(monkeypatch, gemini_module, allowed):
    module = gemini_module
    monkeypatch.setattr(module, "get_account_by_number", AsyncMock(return_value=namespace_types.SimpleNamespace(
        is_active=True, user_id=456, admin_id=1001)))
    monkeypatch.setattr(module, "is_admin", AsyncMock(return_value=allowed))
    request = AsyncMock(return_value="offline answer")
    monkeypatch.setattr(module, "_generate_with_gemini", request)
    message = namespace_types.SimpleNamespace(id=12, text=".question", caption=None, reply_to_message=None,
        from_user=namespace_types.SimpleNamespace(id=456, username="offline", full_name="Offline"), edit_text=AsyncMock())
    await module.gemini_app_handler(namespace_types.SimpleNamespace(name="data/session/offline"), message)
    assert request.await_count == int(allowed)
    assert message.edit_text.await_count == (2 if allowed else 0)
