import math

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from db.main import get_account_user_id, get_app_tg_user_id, get_user_names_by_ids
from filters.all_filters import IsAdmin, IsPrivate
from keyboards.inline.account_manage.account_menu_inline import account_tg_admin_inline

from utils.datetime_tools import DateTime
from utils.panel import edit_panel

router = Router(name=__name__)

PAGE_SIZE = 5


def _normalize_page(value: int) -> int:
    return 1 if value < 1 else value


async def _get_accounts_page(admin_id: int, page: int):
    normalized_page = _normalize_page(page)
    offset = (normalized_page - 1) * PAGE_SIZE

    accounts, count = await get_account_user_id(admin_id, offset)
    total_pages = max(1, math.ceil(count / PAGE_SIZE))
    names = await get_user_names_by_ids([account.user_id for account in accounts])
    keyboard = await account_tg_admin_inline(accounts, normalized_page, total_pages, names=names)
    return count, total_pages, keyboard


@router.message(IsPrivate(), IsAdmin(), F.text == constant_text.ACCOUNTS_USER_KEYBOARD[0], StateFilter("*"))
async def open_accounts_menu_handler(message: Message, state: FSMContext):
    await state.clear()

    user_id = message.from_user.id
    _, apps_count = await get_app_tg_user_id(user_id)
    total, total_pages, keyboard = await _get_accounts_page(user_id, 1)
    await message.answer(
        text=constant_text.ACCOUNT_COUNT_INFO_TEXT.format(
            _count=total,
            _count_apps=apps_count,
            date=DateTime().time_strftime("%d.%m.%Y %H:%M:%S.%f"),
        ),
        reply_markup=keyboard,
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("acc:m:"), StateFilter("*"))
@router.callback_query(IsPrivate(), IsAdmin(), F.data == "panel:accounts", StateFilter("*"))
async def paginate_accounts_menu_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        page = 1 if call.data == "panel:accounts" else int(call.data.split(":")[-1])
    except (TypeError, ValueError, IndexError):
        return await call.answer(constant_text.ERROR_FORMAT_TEXT)

    _, apps_count = await get_app_tg_user_id(call.from_user.id)

    total, total_pages, _ = await _get_accounts_page(call.from_user.id, 1)
    if page < 1 or page > total_pages:
        return await call.answer(constant_text.WARNING_PAGE_EDGE)

    _, _, keyboard = await _get_accounts_page(call.from_user.id, page)

    await edit_panel(call.message,
        text=constant_text.ACCOUNT_COUNT_INFO_TEXT.format(
            _count=total,
            _count_apps=apps_count,
            date=DateTime().time_strftime("%d.%m.%Y %H:%M:%S.%f"),
        ),
        reply_markup=keyboard,
    )
    await call.answer()

