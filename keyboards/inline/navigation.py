"""Shared navigation footer; callback IDs work without a remembered FSM state."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from data.texts.common import ACTION_BACK_TEXT, MAIN_MENU_BUTTON


def navigation_keyboard(back_callback=None):
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=[]), back_callback)


def with_navigation(markup, back_callback=None):
    row = []
    if back_callback and back_callback != "panel:home":
        row.append(InlineKeyboardButton(text=ACTION_BACK_TEXT, callback_data=back_callback))
    row.append(InlineKeyboardButton(text=MAIN_MENU_BUTTON, callback_data="panel:home"))
    return InlineKeyboardMarkup(inline_keyboard=[*markup.inline_keyboard, row])
