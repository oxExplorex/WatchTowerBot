from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_list_keyboard(entries, page, pages):
    builder = InlineKeyboardBuilder()
    for user_id, label in entries:
        builder.row(InlineKeyboardButton(text=label, callback_data=f"adm:view:{user_id}:{page}"))
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="←", callback_data=f"adm:list:{page - 1}"))
    if page + 1 < pages:
        navigation.append(InlineKeyboardButton(text="→", callback_data=f"adm:list:{page + 1}"))
    if navigation:
        builder.row(*navigation)
    builder.row(InlineKeyboardButton(text="➕ Добавить администратора", callback_data="adm:add"))
    builder.row(InlineKeyboardButton(text="Закрыть", callback_data="adm:close"))
    return builder.as_markup()


def admin_detail_keyboard(user_id, page, *, can_revoke):
    builder = InlineKeyboardBuilder()
    if can_revoke:
        builder.row(InlineKeyboardButton(text="Отозвать доступ", callback_data=f"adm:revoke:{user_id}:{page}"))
    builder.row(InlineKeyboardButton(text="← К списку", callback_data=f"adm:list:{page}"))
    return builder.as_markup()


def admin_confirmation_keyboard(action, nonce, *, page=0):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Подтвердить", callback_data=f"adm:{action}:{nonce}"))
    builder.row(InlineKeyboardButton(text="Отмена", callback_data=f"adm:list:{page}"))
    return builder.as_markup()


def admin_cancel_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Отмена", callback_data="adm:list:0"))
    return builder.as_markup()
