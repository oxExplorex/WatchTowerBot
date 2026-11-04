"""Keyboards used by the personal archive secret dialog."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from callbacks.personal_secret import SETUP_CALLBACK
from data.texts.personal_secret import SETUP_BUTTON


def setup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=SETUP_BUTTON, callback_data=SETUP_CALLBACK),
        ]],
    )
