from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from aiogram import Router

router = Router(name=__name__)


@router.message(StateFilter("*"))
async def any_message_handler(message: Message, state: FSMContext):
    _ = message
    _ = state
