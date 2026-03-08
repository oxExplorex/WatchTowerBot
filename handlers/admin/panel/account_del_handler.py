import glob
import os
from contextlib import suppress

from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import data.text as constant_text
from core.session_runtime import stop_and_remove_session
from db.main import del_account_uuid, get_account_user_id, get_account_uuid, get_app_tg_user_id
from filters.all_filters import IsAdmin, IsPrivate
from keyboards.inline.account_manage.account_menu_inline import account_tg_admin_inline
from loader import router
from utils.datetime_tools import DateTime

PAGE_SIZE = 5


async def _show_accounts_or_close(call: CallbackQuery) -> None:
    accounts, count = await get_account_user_id(call.from_user.id, 0)
    if count <= 0:
        with suppress(Exception):
            await call.message.delete()
        return

    _, apps_count = await get_app_tg_user_id(call.from_user.id)
    total_pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    keyboard = await account_tg_admin_inline(accounts, 1, total_pages)

    await call.message.edit_text(
        text=constant_text.ACCOUNT_COUNT_INFO_TEXT.format(
            _count=count,
            _count_apps=apps_count,
            date=DateTime().time_strftime("%d.%m.%Y %H:%M:%S.%f"),
        ),
        reply_markup=keyboard,
    )


def _account_uuid_from_callback(call: CallbackQuery) -> str | None:
    try:
        return call.data.split(":")[-1]
    except (AttributeError, IndexError, TypeError):
        return None


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("acc:del:"), StateFilter("*"))
async def account_delete_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    account_uuid = _account_uuid_from_callback(call)
    if account_uuid is None:
        return await call.answer(constant_text.ERROR_FORMAT_TEXT)

    account = await get_account_uuid(account_uuid, call.from_user.id)
    if not account:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        return await _show_accounts_or_close(call)

    await stop_and_remove_session(account.number)

    if await del_account_uuid(account.uuid, call.from_user.id):
        for session_path in glob.glob(f"data/session/{account.number}*"):
            with suppress(OSError):
                os.remove(session_path)

        await call.message.edit_text(constant_text.SUCCESS_DEL_ACCOUNT_TEXT)
        return

    await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)

