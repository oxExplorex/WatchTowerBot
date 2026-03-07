import asyncio
import os
import traceback

import google.generativeai as genai
from aiogram import Bot, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from google.generativeai import ChatSession
from pyrogram import Client

from core.logging import bot_logger
from data.gemini_safety import SAFETY_SETTINGS
from data.config import GEMINI_KEY, TOKEN_BOT
from db.main import close_database, connect_database, get_account_all, get_app_tg_uuid_aio
from db.migrations import run_db_migrations


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


loop = _get_or_create_event_loop()
asyncio_lock = asyncio.Lock()


async def _bootstrap_db() -> None:
    await run_db_migrations()


async def _get_apps_user() -> list[Client]:
    try:
        await connect_database()

        apps = []
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


_ = loop.run_until_complete(_bootstrap_db())
apps_session: list[Client] = loop.run_until_complete(_get_apps_user())

router = Router()
bot = Bot(
    token=TOKEN_BOT,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)


async def _get_gemini_chat():
    try:
        await connect_database()

        if os.path.exists("data/proxy.txt"):
            with open("data/proxy.txt", "r", encoding="utf-8") as file:
                proxy_raw = file.read().strip()
                if proxy_raw and proxy_raw != "0":
                    ip, port, user, password = proxy_raw.split(":")
                    proxy = f"http://{user}:{password}@{ip}:{port}"
                    bot_logger.info(f"Proxy enabled: {proxy}")

                    os.environ["http_proxy"] = proxy
                    os.environ["HTTP_PROXY"] = proxy
                    os.environ["https_proxy"] = proxy
                    os.environ["HTTPS_PROXY"] = proxy
                    os.environ["grpc_proxy"] = proxy
                    os.environ["GRPC_PROXY"] = proxy

        genai.configure(api_key=GEMINI_KEY)

        with open("data/promt_ai_userbot.txt", "r", encoding="utf-8") as file:
            system_instruction = file.read()

        admin_ids = list(set(x.user_id for x in await get_account_all(active_only=True)))
        admin_ids_text = ", ".join(str(x) for x in admin_ids)

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=system_instruction.replace("[Здесь перечислить user_id через запятую]", admin_ids_text),
            safety_settings=SAFETY_SETTINGS,
        )
        chat_gemini = model.start_chat(history=[])

        await close_database()
        return chat_gemini
    except Exception:
        bot_logger.info(traceback.format_exc())
        try:
            await close_database()
        except Exception:
            pass
        return None


chat_gemini: ChatSession = loop.run_until_complete(_get_gemini_chat())


