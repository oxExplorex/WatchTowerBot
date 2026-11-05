from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import data.text as constant_text
from filters.all_filters import IsAdmin, IsPrivate
from keyboards.main.start_keyboard import static_admin_keyboard

from utils.others import close_state_pyrogram_client
from utils.panel import clear_panel_state, edit_input_panel, edit_panel, remember_panel

router = Router(name=__name__)


@router.message(IsPrivate(), IsAdmin(), CommandStart(), StateFilter("*"))
async def start_user_handler(message: Message, state: FSMContext):
    await close_state_pyrogram_client(state)
    data = await state.get_data()
    await clear_panel_state(state)
    if type(data.get("panel_message_id")) is not int:
        # Telegram cannot edit a message sent with ReplyKeyboardRemove into an
        # inline menu. Remove legacy keyboards with a separate transient message.
        notice = await message.answer(constant_text.START_PANEL_OPENING_TEXT,
                                      reply_markup=ReplyKeyboardRemove(), disable_notification=True)
        try:
            await notice.delete()
        except TelegramBadRequest:
            pass  # A failed cleanup must not prevent opening the actual menu.
    panel = await message.answer(constant_text.START_MESSAGE_TEXT, reply_markup=static_admin_keyboard(), parse_mode="HTML")
    await remember_panel(state, panel)
    previous = data.get("panel_message_id")
    if type(previous) is int and previous != panel.message_id:
        try:
            await message.bot.delete_message(message.chat.id, previous)
        except TelegramBadRequest:
            pass


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "noop", StateFilter("*"))
async def noop_callback_handler(call: CallbackQuery):
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "panel:home", StateFilter("*"))
async def main_menu_handler(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await close_state_pyrogram_client(state)
    await clear_panel_state(state)
    panel = await edit_panel(call.message, constant_text.START_MESSAGE_TEXT, static_admin_keyboard())
    await remember_panel(state, panel or call.message)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "back_delete", StateFilter("*"))
async def back_delete_handler(call: CallbackQuery, state: FSMContext):
    # Compatibility with cancel buttons sent before inline navigation.
    await main_menu_handler(call, state)
