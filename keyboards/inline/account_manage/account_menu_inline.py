from typing import List

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import data.text as constant_text
from db.models import apps_db


async def account_tg_admin_inline(account_tg: List[apps_db], page: int, total_pages: int, *, names: dict):
    keyboard = InlineKeyboardBuilder()

    for item in account_tg:
        name = names.get(item.user_id) or constant_text.ACCOUNT_MENU_UNKNOWN_NAME
        status = constant_text.ACCOUNT_MENU_ACTIVE_ICON if item.is_active else constant_text.ACCOUNT_MENU_INACTIVE_ICON
        title = constant_text.ACCOUNT_MENU_TITLE.format(status=status, name=name, user_id=item.user_id)

        keyboard.row(
            InlineKeyboardButton(
                text=title,
                callback_data=f"acc:e:{item.uuid}",
            ),
        )

    if total_pages > 1:
        navigation = []
        if page > 1:
            navigation.append(InlineKeyboardButton(text=constant_text.ACTION_PAGE_PREV_TEXT, callback_data=f"acc:m:{page - 1}"))
        navigation.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            navigation.append(InlineKeyboardButton(text=constant_text.ACTION_PAGE_NEXT_TEXT, callback_data=f"acc:m:{page + 1}"))
        keyboard.row(*navigation)
    keyboard.row(
        InlineKeyboardButton(text=constant_text.ACTION_REFRESH_TEXT, callback_data=f"acc:m:{page}"),
        InlineKeyboardButton(text=constant_text.MAIN_MENU_BUTTON, callback_data="panel:home"),
    )

    return keyboard.as_markup()
