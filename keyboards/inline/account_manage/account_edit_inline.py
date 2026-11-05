from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

import data.text as constant_text
from db.models import apps_db
from keyboards.inline.navigation import with_navigation
from data.texts import account_ownership as ownership_text


def _state_emoji(value: int) -> str:
    return "✅" if int(value) else "❌"


async def account_edit_admin_inline(account: apps_db):
    keyboard = InlineKeyboardBuilder()

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.ACCOUNT_EDIT_BTN_SESSION.format(state=_state_emoji(account.is_active)),
            callback_data=f"acc:ts:{account.uuid}",
        ),
    )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.ACCOUNT_EDIT_BTN_NEW_CHATS.format(state=_state_emoji(account.alert_new_chat)),
            callback_data=f"acc:tn:{account.uuid}",
        ),
    )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.ACCOUNT_EDIT_BTN_DEL_CHATS.format(state=_state_emoji(account.alert_del_chat)),
            callback_data=f"acc:td:{account.uuid}",
        ),
    )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.ACCOUNT_EDIT_BTN_BOTS.format(state=_state_emoji(account.alert_bot)),
            callback_data=f"acc:tb:{account.uuid}",
        ),
    )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.ACCOUNT_EDIT_BTN_SPOILER_MEDIA.format(
                state=_state_emoji(getattr(account, "alert_spoiler_media", 1))
            ),
            callback_data=f"acc:tm:{account.uuid}",
        ),
    )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.ACCOUNT_EDIT_BTN_CHECK_NOW,
            callback_data=f"acc:chk:{account.uuid}",
        ),
    )
    keyboard.row(InlineKeyboardButton(text=ownership_text.BTN_DISCONNECT, callback_data=f"acc:del:{account.uuid}"))
    keyboard.row(InlineKeyboardButton(text=ownership_text.BTN_DELETE_FULL, callback_data=f"acc:purge:{account.uuid}"))

    return with_navigation(keyboard.as_markup(), "acc:m:1")
