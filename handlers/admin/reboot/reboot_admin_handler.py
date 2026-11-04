from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import data.text as constant_text
from core.process_control import restart_with_clients
from filters.all_filters import IsAdmin, IsPrivate

from scripts.startup_status import current_reporter

router = Router(name=__name__)


@router.message(IsPrivate(), IsAdmin(), F.text.in_(constant_text.RESTART_BOT_W_KEYBOARD), StateFilter("*"))
async def restart_handler(message: Message, state: FSMContext):
    await state.clear()
    if current_reporter() is None:
        await message.answer(constant_text.RESTARTING_TEXT)
    await restart_with_clients()
