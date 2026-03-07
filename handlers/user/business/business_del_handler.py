from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from core.logging import bot_logger
from loader import router, bot



@router.deleted_business_messages(StateFilter("*"))
async def deleted_business_handler(message: Message):
    bot_logger.info(message)

    return


