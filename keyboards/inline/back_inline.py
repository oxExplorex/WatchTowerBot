from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import data.text as constant_text


def back_inline():
    keyboard = InlineKeyboardBuilder()

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.ACTION_CANCEL_TEXT,
            callback_data="back_delete",
        ),
    )
    return keyboard.as_markup()
