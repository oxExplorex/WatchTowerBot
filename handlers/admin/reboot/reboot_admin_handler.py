from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import data.text as constant_text
from core.process_control import restart_current_process
from core.session_runtime import stop_all_clients
from filters.all_filters import IsAdmin, IsPrivate
from loader import router


@router.message(IsPrivate(), IsAdmin(), F.text.in_(constant_text.RESTART_BOT_W_KEYBOARD), StateFilter("*"))
async def restart_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(constant_text.RESTARTING_TEXT)
    await stop_all_clients()
    restart_current_process()
