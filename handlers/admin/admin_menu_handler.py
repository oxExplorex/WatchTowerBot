from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from filters.all_filters import IsAdmin, IsPrivate
from keyboards.main.start_keyboard import static_admin_keyboard
from loader import router
from utils.others import close_state_pyrogram_client, not_warning_delete_message


@router.message(IsPrivate(), IsAdmin(), F.text.startswith("/start"), StateFilter("*"))
async def start_user_handler(message: Message, state: FSMContext):
    await close_state_pyrogram_client(state)
    await state.clear()

    await message.answer(
        text=constant_text.START_MESSAGE_TEXT.format(
            version="1.1",
            version_status="stable",
            last_check="-",
            last_check_sec="-",
        ),
        reply_markup=static_admin_keyboard(),
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "noop", StateFilter("*"))
async def noop_callback_handler(call: CallbackQuery):
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "back_delete", StateFilter("*"))
async def back_delete_handler(call: CallbackQuery, state: FSMContext):
    await close_state_pyrogram_client(state)
    await state.clear()
    await not_warning_delete_message(message=call)
    await call.answer(constant_text.ACTION_CANCELLED_TEXT)
