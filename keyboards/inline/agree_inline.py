from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from keyboards.inline.navigation import with_navigation

import data.text as constant_text


def agree_inline():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.ACTION_CONFIRM_TEXT,
            callback_data="agree",
        ),
    )
    return with_navigation(keyboard.as_markup(), "panel:apps")
