"""Settings keyboards are built from values; they never fetch database state."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import data.text as constant_text
from callbacks.personal_secret import STATUS_CALLBACK
from data.texts.personal_secret import MENU_BUTTON as SECRET_BUTTON
from utils.settings_formatting import auto_update_label, proxy_status_label, tz_offset_label
from keyboards.inline.navigation import with_navigation
from data.texts.logs import BUTTON as LOG_BUTTON


def settings_keyboard(tz_offset: int, auto_update: int, proxy_cfg: dict, has_update: bool,
                      *, can_export_logs=False) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_RUN_UPDATE if has_update else constant_text.SETTINGS_BTN_CHECK_UPDATE,
            callback_data="set:update:run" if has_update else "set:update:check",
        )
    )

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_AUTO_UPDATE.format(state=auto_update_label(auto_update)),
            callback_data=f"set:au:{0 if auto_update else 1}",
        )
    )

    keyboard.row(InlineKeyboardButton(text=SECRET_BUTTON, callback_data=STATUS_CALLBACK))
    if can_export_logs:
        keyboard.row(InlineKeyboardButton(text=LOG_BUTTON, callback_data="set:logs:last"))
        from callbacks.backups import MENU
        from data.texts.backups import BUTTON
        keyboard.row(InlineKeyboardButton(text=BUTTON, callback_data=MENU))

    keyboard.row(
        InlineKeyboardButton(
            text=constant_text.SETTINGS_BTN_PROXY.format(state=proxy_status_label(proxy_cfg)),
            callback_data="set:proxy:open",
        )
    )
    if proxy_cfg.get("proxy"):
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
    return with_navigation(keyboard.as_markup())


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
    return with_navigation(keyboard.as_markup(), "set:back")

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


