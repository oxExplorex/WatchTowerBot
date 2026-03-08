import asyncio
import traceback
from pathlib import Path

from aiogram import Bot, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from pyrogram import Client

from core.logging import bot_logger
import data.text as constant_text
from data.config import GEMINI_KEY, TOKEN_BOT
from db.main import close_database, connect_database, get_account_all, get_app_tg_uuid_aio
from db.migrations import run_db_migrations


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
asyncio_lock = asyncio.Lock()


async def _bootstrap_db() -> None:
    await run_db_migrations()


async def _get_apps_user() -> list[Client]:
    try:
        await connect_database()

        apps: list[Client] = []
        for account in await get_account_all(active_only=True):
            app_tg = await get_app_tg_uuid_aio(account.app_tg)
            if not app_tg:
                continue

            apps.append(
                Client(
                    name=f"data/session/{account.number}",
                    api_id=app_tg.app_id,
                    api_hash=app_tg.api_hash,
                    phone_number=f"{account.number}",
                )
            )

        await close_database()
        return apps
    except Exception:
        bot_logger.info(traceback.format_exc())
        try:
            await close_database()
        except Exception:
            pass
        return []


async def _build_gemini_system_instruction() -> str:
    if not GEMINI_KEY:
        bot_logger.warning("GEMINI_KEY is empty; Gemini disabled")
        return ""

    try:
        await connect_database()
        accounts = await get_account_all(active_only=True)
        admin_ids = sorted({int(x.user_id) for x in accounts if x.user_id is not None})
        admin_ids_text = ", ".join(str(x) for x in admin_ids)
        system_instruction = _build_system_instruction(admin_ids_text)

        await close_database()
        return system_instruction
    except Exception:
        bot_logger.info(traceback.format_exc())
        try:
            await close_database()
        except Exception:
            pass
        return ""


_ = loop.run_until_complete(_bootstrap_db())
apps_session: list[Client] = loop.run_until_complete(_get_apps_user())
gemini_system_instruction = loop.run_until_complete(_build_gemini_system_instruction())

router = Router()
bot = Bot(
    token=TOKEN_BOT,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)


