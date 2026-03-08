from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from db.main import (
    get_user_gemini_proxy_config,
    get_user_timezone_offset,
    set_user_gemini_proxy,
)
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.proxy_manager.proxy_checker import check_proxy_now
from handlers.admin.states import AdminStates
from loader import router
from utils.datetime_tools import DateTime
from utils.proxy_utils import compact_proxy_display, normalize_http_proxy_input


def _proxy_status_label(proxy_cfg: dict) -> str:
    enabled = int(proxy_cfg.get("enabled", 0) or 0)
    status = int(proxy_cfg.get("status", 0) or 0)
    checked_at = int(proxy_cfg.get("checked_at", 0) or 0)
    last_error = (proxy_cfg.get("last_error") or "").strip()
    if not enabled:
        return constant_text.PROXY_STATUS_DISABLED_TEXT
    if status == 1:
        return constant_text.PROXY_STATUS_OK_TEXT
    if checked_at > 0 and not last_error:
        return constant_text.PROXY_STATUS_OK_TEXT
    return constant_text.PROXY_STATUS_PENDING_TEXT


def _checked_at_label(checked_at: int, tz_offset: int) -> str:
    if checked_at <= 0:
        return constant_text.PROXY_MENU_NO_DATA_TEXT
    return DateTime(tz_offset).convert_timestamp(checked_at, "%d.%m.%Y %H:%M:%S")["str"]


def _proxy_menu_text(proxy_cfg: dict, tz_offset: int) -> str:
    proxy_text = compact_proxy_display(proxy_cfg.get("proxy"))
    status_text = _proxy_status_label(proxy_cfg)
    checked_at = int(proxy_cfg.get("checked_at", 0) or 0)
    last_error = (proxy_cfg.get("last_error") or "").strip()

    checked_line = _checked_at_label(checked_at, tz_offset)
    error_line = last_error[:120] if last_error else constant_text.PROXY_MENU_NO_DATA_TEXT

    return constant_text.PROXY_MENU_PROMPT_TEXT.format(
        proxy=proxy_text,
        status=status_text,
        checked_at=checked_line,
        error=error_line,
    ).replace("(unix)", "")


@router.message(IsPrivate(), IsAdmin(), F.text.in_(constant_text.PROXY_USER_KEYBOARD), StateFilter("*"))
async def open_proxy_menu_handler(message: Message, state: FSMContext):
    await state.clear()
    cfg = await get_user_gemini_proxy_config(message.from_user.id)
    tz_offset = await get_user_timezone_offset(message.from_user.id)
    await message.answer(_proxy_menu_text(cfg, tz_offset))
    await state.set_state(AdminStates.wait_proxy_manager)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:proxy:open", StateFilter("*"))
async def open_proxy_menu_from_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    cfg = await get_user_gemini_proxy_config(call.from_user.id)
    tz_offset = await get_user_timezone_offset(call.from_user.id)
    await call.message.edit_text(_proxy_menu_text(cfg, tz_offset))
    await state.set_state(AdminStates.wait_proxy_manager)
    await call.answer()


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.wait_proxy_manager))
async def save_proxy_handler(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    if text in {"/start", "/cancel", constant_text.ACTION_CANCEL_TEXT, constant_text.SETTINGS_BOT_KEYBOARD[2]}:
        await state.clear()
        await message.answer(constant_text.ACTION_CANCELLED_TEXT)
        return

    proxy_url = normalize_http_proxy_input(text)
    if not proxy_url:
        await message.answer(constant_text.PROXY_INVALID_FORMAT_TEXT)
        await state.set_state(AdminStates.wait_proxy_manager)
        return

    await set_user_gemini_proxy(message.from_user.id, proxy_url)
    await state.clear()

    probe = await message.answer(constant_text.PROXY_CHECKING_TEXT)
    ok, reason = await check_proxy_now(message.from_user.id, proxy_url, log_source="proxy_menu_handler")

    if ok:
        await probe.edit_text(constant_text.PROXY_SET_AND_CHECK_OK_TEXT)
    else:
        await probe.edit_text(constant_text.PROXY_CHECK_FAIL_TEXT.format(reason=reason[:160]))
