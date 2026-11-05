from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import data.text as constant_text
from filters.all_filters import IsAdmin, IsPrivate
from keyboards.main.start_keyboard import static_admin_keyboard

from utils.others import close_state_pyrogram_client
from utils.panel import edit_panel

router = Router(name=__name__)


@router.message(IsPrivate(), IsAdmin(), CommandStart(), StateFilter("*"))
async def start_user_handler(message: Message, state: FSMContext):
    await close_state_pyrogram_client(state)
    await state.clear()

    panel = await message.answer(
        text=constant_text.START_MESSAGE_TEXT,
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    await edit_panel(panel, constant_text.START_MESSAGE_TEXT, static_admin_keyboard())


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "noop", StateFilter("*"))
async def noop_callback_handler(call: CallbackQuery):
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "panel:home", StateFilter("*"))
async def main_menu_handler(call: CallbackQuery, state: FSMContext):
    await close_state_pyrogram_client(state)
    await state.clear()
    await edit_panel(call.message, constant_text.START_MESSAGE_TEXT, static_admin_keyboard())
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "back_delete", StateFilter("*"))
async def back_delete_handler(call: CallbackQuery, state: FSMContext):
    # Compatibility with cancel buttons sent before inline navigation.
    await main_menu_handler(call, state)
