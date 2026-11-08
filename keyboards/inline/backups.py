from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from callbacks import backups as callback
from data.texts import backups as text
from keyboards.inline.navigation import with_navigation
from core.viewer_distribution import download_url
from scripts.update_bot import REPO_OWNER, REPO_NAME


def backup_keyboard(*, uploading=False, complete=False):
    rows = []
    if not uploading:
        rows = [[InlineKeyboardButton(text=text.CREATE_BUTTON, callback_data=callback.CREATE)],
                [InlineKeyboardButton(text=text.DUMP_BUTTON, callback_data=callback.DUMP)],
                [InlineKeyboardButton(text=text.DUMP_ALL_BUTTON, callback_data=callback.DUMP_ALL)],
                [InlineKeyboardButton(text=text.IMPORT_BUTTON, callback_data=callback.IMPORT)],
                [InlineKeyboardButton(text=text.VIEWER_BUTTON, url=download_url(REPO_OWNER, REPO_NAME))]]
    elif complete:
        rows = [[InlineKeyboardButton(text=text.RESTORE_BUTTON, callback_data=callback.RESTORE)]]
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows),
                           callback.MENU if uploading else "panel:settings")


def dump_accounts_keyboard(chat_id, accounts, page, has_next):
    rows = [[InlineKeyboardButton(text=str(account), callback_data=f"{callback.DUMP_SELECT}{chat_id}:{account}")]
            for account in accounts]
    navigation = []
    if page:
        navigation.append(InlineKeyboardButton(text="‹", callback_data=f"{callback.DUMP_PAGE}{chat_id}:{page - 1}"))
    if has_next:
        navigation.append(InlineKeyboardButton(text="›", callback_data=f"{callback.DUMP_PAGE}{chat_id}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    return with_navigation(InlineKeyboardMarkup(inline_keyboard=rows), callback.MENU)
