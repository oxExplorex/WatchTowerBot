from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from callbacks.startup import CLOSE
from data.texts.startup import CLOSE_BUTTON


def close_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=CLOSE_BUTTON, callback_data=CLOSE),
    ]])
