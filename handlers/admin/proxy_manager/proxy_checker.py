from google import genai
from google.genai import types

import data.text as constant_text
from core.logging import bot_logger
from data.config import GEMINI_KEY
from db.main import set_user_gemini_proxy_health


async def check_proxy_now(admin_id: int, proxy_url: str, log_source: str) -> tuple[bool, str]:
    if not GEMINI_KEY:
        return False, constant_text.PROXY_GEMINI_KEY_EMPTY_TEXT

    http_options = types.HttpOptions(
        client_args={"proxy": proxy_url},
        async_client_args={"proxy": proxy_url},
    )
    client = genai.Client(api_key=GEMINI_KEY, http_options=http_options)

    try:
        await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents="ping",
        )
        await set_user_gemini_proxy_health(admin_id, is_ok=True)
        return True, "ok"
    except Exception as exc:
        error_text = str(exc)[:220]
        bot_logger.exception(f"Proxy check failed in {log_source}")
        await set_user_gemini_proxy_health(admin_id, is_ok=False, error=error_text)
        return False, error_text

