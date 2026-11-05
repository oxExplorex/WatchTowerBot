from typing import List

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import data.text as constant_text
from db.models import app_tg_db


async def apps_tg_admin_inline(apps_tg: List[app_tg_db], page: int, total_pages: int, *, linked_counts: dict):
    keyboard = InlineKeyboardBuilder()

    keyboard.row(
        InlineKeyboardButton(text=constant_text.APPS_MENU_ADD, callback_data="apps_admin_menu_add"),
    )

    for item in apps_tg:
        linked_count = linked_counts.get(item.uuid, 0)
        keyboard.row(
            InlineKeyboardButton(
                text=constant_text.APPS_MENU_USE.format(
                    tag_name=item.tag_name,
                    app_id=item.app_id,
                    linked_count=linked_count,
                ),
                callback_data=f"account_admin_menu_add:{item.uuid}",
            ),
            InlineKeyboardButton(
                text=constant_text.APPS_MENU_DELETE,
                callback_data=f"apps_admin_menu_delete:{item.uuid}",
            ),
        )

    if total_pages > 1:
        navigation = []
        if page > 1:
            navigation.append(InlineKeyboardButton(text=constant_text.ACTION_PAGE_PREV_TEXT, callback_data=f"apps_admin_menu:{page - 1}"))
        navigation.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            navigation.append(InlineKeyboardButton(text=constant_text.ACTION_PAGE_NEXT_TEXT, callback_data=f"apps_admin_menu:{page + 1}"))
        keyboard.row(*navigation)
    keyboard.row(
        InlineKeyboardButton(text=constant_text.ACTION_REFRESH_TEXT, callback_data=f"apps_admin_menu:{page}"),
        InlineKeyboardButton(text=constant_text.MAIN_MENU_BUTTON, callback_data="panel:home"),
    )

    return keyboard.as_markup()
