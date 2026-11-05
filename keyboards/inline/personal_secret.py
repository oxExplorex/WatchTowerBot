"""Keyboards used by the personal archive secret dialog."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from callbacks.personal_secret import CANCEL_CALLBACK, SETUP_CALLBACK
from data.texts.personal_secret import CANCEL_BUTTON, SETUP_BUTTON
from keyboards.inline.navigation import with_navigation


def setup_keyboard() -> InlineKeyboardMarkup:
    return with_navigation(InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=SETUP_BUTTON, callback_data=SETUP_CALLBACK),
        ]],
    ))


def cancel_keyboard(back_callback="panel:settings") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=CANCEL_BUTTON, callback_data=CANCEL_CALLBACK),
    ]])
