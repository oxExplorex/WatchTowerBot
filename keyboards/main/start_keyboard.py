from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import data.text as constant_text
from data.admin_text import MENU_BUTTON as ADMINS_BUTTON
from data.texts.account_ownership import MENU as OWN_ACCOUNT_BUTTON
from callbacks.account_ownership import HOME_CALLBACK


def static_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=constant_text.ACCOUNTS_USER_KEYBOARD[0], callback_data="panel:accounts"),
         InlineKeyboardButton(text=constant_text.APP_TG_USER_KEYBOARD[0], callback_data="panel:apps")],
        [InlineKeyboardButton(text=constant_text.ACCOUNTS_USER_KEYBOARD[1], callback_data="panel:search"),
         InlineKeyboardButton(text=OWN_ACCOUNT_BUTTON, callback_data=HOME_CALLBACK)],
        [InlineKeyboardButton(text=constant_text.SETTINGS_BOT_KEYBOARD[0], callback_data="panel:stats:own"),
         InlineKeyboardButton(text=constant_text.SETTINGS_BOT_KEYBOARD[1], callback_data="panel:stats:all")],
        [InlineKeyboardButton(text=ADMINS_BUTTON, callback_data="adm:list:0"),
         InlineKeyboardButton(text=constant_text.SETTINGS_BOT_KEYBOARD[2], callback_data="panel:settings")],
    ])
