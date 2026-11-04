"""Gemini transport and proxy policy, independent of Telegram update handlers."""
import traceback

from google.genai import types

import data.text as constant_text
from core.logging import bot_logger
from data.gemini_safety import SAFETY_SETTINGS
from utils.gemini_client import managed_gemini_client
from utils.proxy_utils import normalize_http_proxy_input

GEMINI_MODEL_NAME = "gemini-3.1-flash-lite-preview"
_GEMINI_MODEL_NAME = GEMINI_MODEL_NAME


def _response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).replace("\\n", "\n")

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        chunks: list[str] = []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                chunks.append(str(part_text))
        if chunks:
            return "\n".join(chunks)

    return constant_text.GEMINI_UNAVAILABLE_TEXT


def _is_proxy_transport_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "proxy",
        "tunnel",
        "connection",
        "connecterror",
        "network",
        "timeout",
        "name or service not known",
        "nodename nor servname provided",
    )
    return any(marker in text for marker in markers)


async def request_gemini(parts: list[types.Part], proxy_url: str | None, *, api_key: str, system_instruction: str) -> str:
    if proxy_url:
        http_options = types.HttpOptions(
            client_args={"proxy": proxy_url},
            async_client_args={"proxy": proxy_url},
        )
    else:
        http_options = None

    config = types.GenerateContentConfig(
        system_instruction=system_instruction or None,
        safety_settings=SAFETY_SETTINGS,
    )

    async with managed_gemini_client(api_key=api_key, http_options=http_options) as client:
        response = await client.aio.models.generate_content(
            model=_GEMINI_MODEL_NAME,
            contents=[types.Content(role="user", parts=parts)],
            config=config,
        )
        return _response_text(response)


async def generate_with_proxy(admin_id: int, parts: list[types.Part], *, api_key: str, request,
                              get_proxy_config, set_proxy_health) -> str:
    if not api_key:
        return constant_text.GEMINI_UNAVAILABLE_TEXT

    proxy_config = await get_proxy_config(admin_id)
    proxy_raw = proxy_config.get("proxy")
    enabled = int(proxy_config.get("enabled", 0) or 0)

    proxy_url: str | None = None
    if enabled and proxy_raw:
        proxy_url = normalize_http_proxy_input(str(proxy_raw))
        if not proxy_url:
            await set_proxy_health(admin_id, is_ok=False, error="invalid_proxy_format")
            return constant_text.GEMINI_PROXY_INVALID_TEXT

    try:
        answer = await request(parts, proxy_url=proxy_url)
        await set_proxy_health(admin_id, is_ok=True)
        return answer
    except Exception as exc:
        error_text = str(exc)
        await set_proxy_health(admin_id, is_ok=False, error=error_text[:250])

        # Proxy mode failed at transport layer: keep saved proxy and retry once without proxy.
        if proxy_url and _is_proxy_transport_error(exc):
            try:
                return await request(parts, proxy_url=None)
            except Exception:
                bot_logger.error(traceback.format_exc())
                return getattr(constant_text, "GEMINI_PROXY_OR_VPN_HINT_TEXT", constant_text.GEMINI_UNAVAILABLE_TEXT)

        bot_logger.error(traceback.format_exc())
        if not proxy_url:
            return getattr(constant_text, "GEMINI_PROXY_OR_VPN_HINT_TEXT", constant_text.GEMINI_UNAVAILABLE_TEXT)
        return constant_text.GEMINI_UNAVAILABLE_TEXT
