from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from core.logging import bot_logger
from loader import router



@router.edited_business_message(StateFilter("*"))
async def edited_business_handler(message: Message, state: FSMContext):
    await state.clear()

    bot_logger.info(message)
    return
