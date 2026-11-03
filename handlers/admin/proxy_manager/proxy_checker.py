import asyncio

from google.genai import types

import data.text as constant_text
from core.logging import bot_logger
from data.config import GEMINI_KEY
from db.main import set_user_gemini_proxy_health
from utils.gemini_client import managed_gemini_client


async def check_proxy_now(admin_id: int, proxy_url: str, log_source: str) -> tuple[bool, str]:
    if not GEMINI_KEY:
        return False, constant_text.PROXY_GEMINI_KEY_EMPTY_TEXT

    http_options = types.HttpOptions(
        client_args={"proxy": proxy_url},
        async_client_args={"proxy": proxy_url},
    )
    bot_logger.info(f"Proxy check started: source={log_source} admin_id={admin_id}")
    try:
        async with managed_gemini_client(api_key=GEMINI_KEY, http_options=http_options) as client:
            await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-3.1-flash-lite-preview",
                    contents="ping",
                ),
                timeout=25,
            )
        await set_user_gemini_proxy_health(admin_id, is_ok=True)
        bot_logger.info(f"Proxy check success: source={log_source} admin_id={admin_id}")
        return True, "ok"
    except TimeoutError:
        error_text = "timeout"
        bot_logger.warning(f"Proxy check timeout: source={log_source} admin_id={admin_id}")
        await set_user_gemini_proxy_health(admin_id, is_ok=False, error=error_text)
        return False, error_text
    except Exception as exc:
        error_text = str(exc)[:220]
        bot_logger.exception(f"Proxy check failed in {log_source}")
        await set_user_gemini_proxy_health(admin_id, is_ok=False, error=error_text)
        return False, error_text
