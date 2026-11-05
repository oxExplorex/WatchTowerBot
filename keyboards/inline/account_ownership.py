from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks.account_ownership import HOME_CALLBACK, OwnAccount
from data.texts import account_ownership as text
from keyboards.inline.navigation import navigation_keyboard, with_navigation


def button(label, action, token="-", page=0):
    return InlineKeyboardButton(text=label, callback_data=OwnAccount(action=action, token=str(token), page=page).pack())


def self_menu_keyboard():
    return navigation_keyboard()


def accounts_keyboard(accounts):
    builder = InlineKeyboardBuilder()
    for account in accounts:
        builder.row(button(str(account.user_id), "detail", account.uuid.hex))
    return with_navigation(builder.as_markup())


def detail_keyboard(account, operation=None):
    builder = InlineKeyboardBuilder()
    if account.admin_id == account.user_id:
        builder.row(InlineKeyboardButton(text=text.BTN_MANAGE, callback_data=f"acc:e:{account.uuid}"))
    else:
        builder.row(button(text.BTN_TRANSFER, "profiles"))
    if operation:
        builder.row(button(text.BTN_STATUS, "status", operation.uuid.hex))
    builder.row(button(text.BTN_DELETE, "delete", account.uuid.hex))
    return with_navigation(builder.as_markup(), HOME_CALLBACK)


def profiles_keyboard(profiles, page, total_pages, *, account_uuid=None):
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
    parent = OwnAccount(action="detail", token=str(account_uuid)).pack() if account_uuid else HOME_CALLBACK
    return with_navigation(builder.as_markup(), parent)


def approval_keyboard(operation):
    label = text.BTN_RESUME if operation.status == "needs_secret" else text.BTN_CONFIRM
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=[[
        button(label, "approve", operation.uuid.hex), button(text.BTN_REJECT, "reject", operation.uuid.hex),
    ]]), HOME_CALLBACK)


def delete_keyboard(operation, *, back_callback=HOME_CALLBACK):
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(text.BTN_CONFIRM_DELETE, "erase", operation.uuid.hex)],
        [button(text.BTN_CANCEL, "reject", operation.uuid.hex)],
    ])


def status_keyboard(operation, actor_id):
    if operation.kind == "transfer" and operation.status in {"pending", "needs_secret"}:
        if operation.owner_id == actor_id:
            return approval_keyboard(operation)
        return with_navigation(InlineKeyboardMarkup(inline_keyboard=[[button(text.BTN_CANCEL, "reject", operation.uuid.hex)]]), HOME_CALLBACK)
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=[[button(text.BTN_STATUS, "status", operation.uuid.hex)]]), HOME_CALLBACK)
