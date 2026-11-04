from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

import data.text as constant_text
from data.admin_text import MENU_BUTTON as ADMINS_BUTTON
from data.texts.account_ownership import MENU as OWN_ACCOUNT_BUTTON


def static_admin_keyboard():
    keyboard = [
        [KeyboardButton(text=constant_text.ACCOUNTS_USER_KEYBOARD[0]), KeyboardButton(text=constant_text.ACCOUNTS_USER_KEYBOARD[1])],
        [KeyboardButton(text=constant_text.APP_TG_USER_KEYBOARD[0])],
        [
            KeyboardButton(text=constant_text.SETTINGS_BOT_KEYBOARD[0]),
            KeyboardButton(text=constant_text.SETTINGS_BOT_KEYBOARD[1]),
        ],
        [KeyboardButton(text=constant_text.SETTINGS_BOT_KEYBOARD[2])],
        [KeyboardButton(text=ADMINS_BUTTON)],
        [KeyboardButton(text=OWN_ACCOUNT_BUTTON)],
    ]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Gemini Message Manager",
    )
