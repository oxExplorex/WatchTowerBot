"""Settings keyboards are built from values; they never fetch database state."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import data.text as constant_text
from data.admin_text import MENU_BUTTON as ADMINS_BUTTON
from utils.settings_formatting import auto_update_label, proxy_status_label, tz_offset_label


def settings_keyboard(tz_offset: int, auto_update: int, proxy_cfg: dict, has_update: bool) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    keyboard.row(InlineKeyboardButton(text=ADMINS_BUTTON, callback_data="adm:list:0"))

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_AUTO_UPDATE.format(state=auto_update_label(auto_update)),
            callback_data=f"set:au:{0 if auto_update else 1}",
        )
    )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_CHECK_UPDATE,
            callback_data="set:update:check",
        )
    )

    if has_update:
        keyboard.row(
            InlineKeyboardButton(
                text=constant_text.SETTINGS_BTN_RUN_UPDATE,
                callback_data="set:update:run",
            )
        )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_PROXY.format(state=proxy_status_label(proxy_cfg)),
            callback_data="set:proxy:open",
        )
    )
    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_PROXY_DISABLE,
            callback_data="set:proxy:disable",
        ),
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_PROXY_CHECK,
            callback_data="set:proxy:check",
        ),
    )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_TIMEZONE.format(tz_label=tz_offset_label(tz_offset)),
            callback_data="set:tz:open",
        )
    )
    keyboard.row(
        InlineKeyboardButton(text=constant_text.SETTINGS_BTN_RESTART, callback_data="set:reboot"),
    )
    keyboard.row(
        InlineKeyboardButton(text=constant_text.SETTINGS_BTN_CLOSE, callback_data="set:close"),
    )
    return keyboard.as_markup()


def timezone_keyboard(current_offset: int):
    keyboard = InlineKeyboardBuilder()
    offsets = list(range(-12, 15))

    for i in range(0, len(offsets), 3):
        buttons = []
        for value in offsets[i : i + 3]:
            base_text = constant_text.TIMEZONE_BTN_PREFIX.format(offset=(f"+{value}" if value >= 0 else str(value)))
            text = constant_text.TIMEZONE_BTN_SELECTED.format(label=base_text) if value == current_offset else base_text
            buttons.append(InlineKeyboardButton(text=text, callback_data=f"set:tz:{value}"))
        keyboard.row(*buttons)

    keyboard.row(InlineKeyboardButton(text=constant_text.TIMEZONE_BTN_RESET, callback_data="set:tz:reset"))
    keyboard.row(InlineKeyboardButton(text=constant_text.ACTION_BACK_TEXT, callback_data="set:back"))
    return keyboard.as_markup()

def update_notice_close_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=constant_text.UPDATE_NOTIFY_BTN_CLOSE, callback_data="upd:close"),
    ]])


def update_notification_keyboard(
    include_snooze: bool = True,
    include_update: bool = False,
    include_close: bool = True,
):
    keyboard = InlineKeyboardBuilder()
    if include_update:
        keyboard.row(
            InlineKeyboardButton(
                text=constant_text.UPDATE_NOTIFY_BTN_UPDATE_NOW,
                callback_data="upd:update",
            )
        )
    if include_snooze:
        keyboard.row(
            InlineKeyboardButton(
                text=constant_text.UPDATE_NOTIFY_BTN_SNOOZE_WEEK,
                callback_data="upd:snooze",
            )
        )
    if include_close:
        keyboard.row(
            InlineKeyboardButton(
                text=constant_text.UPDATE_NOTIFY_BTN_CLOSE,
                callback_data="upd:close",
            )
        )
    return keyboard.as_markup()


