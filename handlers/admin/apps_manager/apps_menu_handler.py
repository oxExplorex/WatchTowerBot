import math

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from db.main import get_account_counts_by_apps, get_app_tg_user_id
from filters.all_filters import IsAdmin, IsPrivate
from keyboards.inline.apps_manager.apps_menu_inline import apps_tg_admin_inline

from utils.datetime_tools import DateTime
from utils.panel import edit_panel

router = Router(name=__name__)

PAGE_SIZE = 5


def _normalize_page(value: int) -> int:
    return 1 if value < 1 else value


async def _get_apps_page(user_id: int, page: int):
    normalized_page = _normalize_page(page)
    offset = (normalized_page - 1) * PAGE_SIZE

    apps, count = await get_app_tg_user_id(user_id, offset)
    total_pages = max(1, math.ceil(count / PAGE_SIZE))
    linked_counts = await get_account_counts_by_apps([app.uuid for app in apps])
    keyboard = await apps_tg_admin_inline(apps, normalized_page, total_pages, linked_counts=linked_counts)
    return count, total_pages, keyboard


@router.message(IsPrivate(), IsAdmin(), F.text.in_(constant_text.APP_TG_USER_KEYBOARD), StateFilter("*"))
async def open_apps_menu_handler(message: Message, state: FSMContext):
    await state.clear()

    total, _, keyboard = await _get_apps_page(message.from_user.id, 1)
    await message.answer(
        text=constant_text.APPS_COUNT_INFO_TEXT.format(
            _count=total,
            date=DateTime().time_strftime("%d.%m.%Y %H:%M:%S.%f"),
        ),
        reply_markup=keyboard,
    )


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("apps_admin_menu:"), StateFilter("*"))
@router.callback_query(IsPrivate(), IsAdmin(), F.data == "panel:apps", StateFilter("*"))
async def paginate_apps_menu_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        page = 1 if call.data == "panel:apps" else int(call.data.split(":")[-1])
    except (TypeError, ValueError, IndexError):
        return await call.answer(constant_text.ERROR_FORMAT_TEXT)

    total, total_pages, _ = await _get_apps_page(call.from_user.id, 1)
    if page < 1 or page > total_pages:
        return await call.answer(constant_text.WARNING_PAGE_EDGE)

    _, _, keyboard = await _get_apps_page(call.from_user.id, page)
    await edit_panel(call.message,
        text=constant_text.APPS_COUNT_INFO_TEXT.format(
            _count=total,
            date=DateTime().time_strftime("%d.%m.%Y %H:%M:%S.%f"),
        ),
        reply_markup=keyboard,
    )
    await call.answer()
