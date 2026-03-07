import os

from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import data.text as constant_text
from core.session_runtime import stop_client
from filters.all_filters import IsAdmin, IsPrivate
from loader import apps_session, router
from update_bot import download_and_extract_github_repo


@router.message(IsPrivate(), IsAdmin(), F.text.in_(constant_text.RESTART_BOT_W_KEYBOARD), StateFilter("*"))
async def restart_windows_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(constant_text.RESTARTING_TEXT)

    for app in list(apps_session):
        await stop_client(app)

    download_and_extract_github_repo()
    os.system("start.bat")
