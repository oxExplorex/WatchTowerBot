from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.texts import admins as text


def admin_list_keyboard(entries, page, pages):
    builder = InlineKeyboardBuilder()
    for user_id, label in entries:
        builder.row(InlineKeyboardButton(text=label, callback_data=f"adm:view:{user_id}:{page}"))
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text=text.PREVIOUS_BUTTON, callback_data=f"adm:list:{page - 1}"))
    if page + 1 < pages:
        navigation.append(InlineKeyboardButton(text=text.NEXT_BUTTON, callback_data=f"adm:list:{page + 1}"))
    if navigation:
        builder.row(*navigation)
    builder.row(InlineKeyboardButton(text=text.ADD_BUTTON, callback_data="adm:add"))
    builder.row(InlineKeyboardButton(text=text.CLOSE_BUTTON, callback_data="adm:close"))
    return builder.as_markup()


def admin_detail_keyboard(user_id, page, *, can_revoke):
    builder = InlineKeyboardBuilder()
    if can_revoke:
        builder.row(InlineKeyboardButton(text=text.REVOKE_BUTTON, callback_data=f"adm:revoke:{user_id}:{page}"))
    builder.row(InlineKeyboardButton(text=text.BACK_BUTTON, callback_data=f"adm:list:{page}"))
    return builder.as_markup()


def admin_confirmation_keyboard(action, nonce, *, page=0):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=text.CONFIRM_BUTTON, callback_data=f"adm:{action}:{nonce}"))
    builder.row(InlineKeyboardButton(text=text.CANCEL_BUTTON, callback_data=f"adm:list:{page}"))
    return builder.as_markup()


def admin_cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=text.CANCEL_BUTTON, callback_data="adm:list:0"))
    return builder.as_markup()
