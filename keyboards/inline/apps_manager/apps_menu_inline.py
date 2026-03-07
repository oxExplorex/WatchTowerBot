from typing import List

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import data.text as constant_text
from db.main import get_accounts_count_by_app_tg_uuid
from db.models import app_tg_db


async def apps_tg_admin_inline(apps_tg: List[app_tg_db], page: int, total_pages: int):
    keyboard = InlineKeyboardBuilder()

    keyboard.row(
        InlineKeyboardButton(text=constant_text.APPS_MENU_ADD, callback_data="apps_admin_menu_add"),
    )

    for item in apps_tg:
        linked_count = await get_accounts_count_by_app_tg_uuid(item.uuid)
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

    keyboard.row(
        InlineKeyboardButton(text=constant_text.ACTION_PAGE_PREV_TEXT, callback_data=f"apps_admin_menu:{page - 1}"),
        InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data=f"apps_admin_menu:{page}"),
        InlineKeyboardButton(text=constant_text.ACTION_PAGE_NEXT_TEXT, callback_data=f"apps_admin_menu:{page + 1}"),
    )
    keyboard.row(
        InlineKeyboardButton(text=constant_text.ACTION_REFRESH_TEXT, callback_data=f"apps_admin_menu:{page}"),
    )

    return keyboard.as_markup()