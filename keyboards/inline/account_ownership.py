from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.account_ownership import OwnAccount
from data.texts import account_ownership as text


def button(label, action, token="-", page=0):
    return InlineKeyboardButton(text=label, callback_data=OwnAccount(action=action, token=str(token), page=page).pack())


def self_menu_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=text.MENU)]], resize_keyboard=True)


def accounts_keyboard(accounts):
    builder = InlineKeyboardBuilder()
    for account in accounts:
        builder.row(button(str(account.user_id), "detail", account.uuid.hex))
    return builder.as_markup()


def detail_keyboard(account, operation=None):
    builder = InlineKeyboardBuilder()
    if account.admin_id == account.user_id:
        builder.row(InlineKeyboardButton(text=text.BTN_MANAGE, callback_data=f"acc:e:{account.uuid}"))
    else:
        builder.row(button(text.BTN_TRANSFER, "profiles"))
    if operation:
        builder.row(button(text.BTN_STATUS, "status", operation.uuid.hex))
    builder.row(button(text.BTN_DELETE, "delete", account.uuid.hex))
    return builder.as_markup()


def profiles_keyboard(profiles, page, total_pages):
    builder = InlineKeyboardBuilder()
    for profile in profiles:
        label = f"{profile.app_id} · {profile.tag_name or ''}"[:64]
        builder.row(button(label, "pick", profile.uuid.hex))
    nav = []
    if page > 0:
        nav.append(button("‹", "profiles", page=page - 1))
    if page + 1 < total_pages:
        nav.append(button("›", "profiles", page=page + 1))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text=text.BTN_PROFILE, callback_data="apps_admin_menu_add"))
    builder.row(button(text.BTN_BACK, "home"))
    return builder.as_markup()


def approval_keyboard(operation):
    label = text.BTN_RESUME if operation.status == "needs_secret" else text.BTN_CONFIRM
    return InlineKeyboardMarkup(inline_keyboard=[[
        button(label, "approve", operation.uuid.hex), button(text.BTN_REJECT, "reject", operation.uuid.hex),
    ]])


def delete_keyboard(operation):
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(text.BTN_CONFIRM_DELETE, "erase", operation.uuid.hex)],
        [button(text.BTN_CANCEL, "reject", operation.uuid.hex)],
    ])


def status_keyboard(operation, actor_id):
    if operation.kind == "transfer" and operation.status in {"pending", "needs_secret"}:
        if operation.owner_id == actor_id:
            return approval_keyboard(operation)
        return InlineKeyboardMarkup(inline_keyboard=[[button(text.BTN_CANCEL, "reject", operation.uuid.hex)]])
    return InlineKeyboardMarkup(inline_keyboard=[[button(text.BTN_STATUS, "status", operation.uuid.hex)]])
