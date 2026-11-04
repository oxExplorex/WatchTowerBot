import asyncio
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from pyrogram import Client

from core.logging import bot_logger
from core.session_manager import SessionManager
import data.text as constant_text
from data.config import GEMINI_KEY, TOKEN_BOT
from db.main import get_account_all, get_active_accounts_with_apps
from db.session import is_connected


_PROMPT_PATH = Path("data/promt_ai_userbot.txt")
_PROMPT_ADMIN_PLACEHOLDER = constant_text.GEMINI_PROMPT_ADMIN_PLACEHOLDER


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _build_system_instruction(admin_ids_text: str) -> str:
    if not _PROMPT_PATH.exists():
        return ""

    try:
        prompt_raw = _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        bot_logger.exception("Failed to read Gemini prompt file")
        return ""

    return prompt_raw.replace(_PROMPT_ADMIN_PLACEHOLDER, admin_ids_text)


loop = _get_or_create_event_loop()
_runtime_initialized = False


async def _get_apps_user() -> list[Client]:
    try:
        apps: list[Client] = []
        for account, app_tg in await get_active_accounts_with_apps():
            apps.append(
                Client(
                    name=f"data/session/{account.number}",
                    api_id=app_tg.app_id,
                    api_hash=app_tg.api_hash,
                    phone_number=f"{account.number}",
                )
            )
        return apps
    except Exception:
        bot_logger.exception("Failed to build apps session list")
        return []


async def _build_gemini_system_instruction() -> str:
    if not GEMINI_KEY:
        bot_logger.warning("GEMINI_KEY is empty; Gemini disabled")
        return ""

    try:
        accounts = await get_account_all(active_only=True)
        admin_ids = sorted({int(x.user_id) for x in accounts if x.user_id is not None})
        admin_ids_text = ", ".join(str(x) for x in admin_ids)
        system_instruction = _build_system_instruction(admin_ids_text)
        return system_instruction
    except Exception:
        bot_logger.exception("Failed to build Gemini system instruction")
        return ""

session_manager = SessionManager()
gemini_system_instruction = ""


async def initialize_runtime_state() -> None:
    global _runtime_initialized, gemini_system_instruction
    if _runtime_initialized:
        return

    if not is_connected():
        raise RuntimeError(
            "Database must be connected before initialize_runtime_state(). "
            "Call connect_database() first."
        )

    apps = await _get_apps_user()
    await session_manager.clear()
    await session_manager.extend(apps)
    gemini_system_instruction = await _build_gemini_system_instruction()
    _runtime_initialized = True

bot = Bot(
    token=TOKEN_BOT,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)


