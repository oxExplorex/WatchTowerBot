from typing import List

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import data.text as constant_text
from db.main import get_user
from db.models import apps_db


async def account_tg_admin_inline(account_tg: List[apps_db], page: int, total_pages: int):
    keyboard = InlineKeyboardBuilder()

    for item in account_tg:
        user = await get_user(item.user_id)
        name = user.full_name if user and user.full_name else constant_text.ACCOUNT_MENU_UNKNOWN_NAME
        status = constant_text.ACCOUNT_MENU_ACTIVE_ICON if item.is_active else constant_text.ACCOUNT_MENU_INACTIVE_ICON
        title = constant_text.ACCOUNT_MENU_TITLE.format(status=status, name=name, user_id=item.user_id)

        keyboard.row(
            InlineKeyboardButton(
                text=title,
                callback_data=f"acc:e:{item.uuid}",
            ),
        )

    keyboard.row(
        InlineKeyboardButton(text=constant_text.ACTION_PAGE_PREV_TEXT, callback_data=f"acc:m:{page - 1}"),
        InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data=f"acc:m:{page}"),
        InlineKeyboardButton(text=constant_text.ACTION_PAGE_NEXT_TEXT, callback_data=f"acc:m:{page + 1}"),
    )
    keyboard.row(
        InlineKeyboardButton(text=constant_text.ACTION_REFRESH_TEXT, callback_data=f"acc:m:{page}"),
    )

    return keyboard.as_markup()
