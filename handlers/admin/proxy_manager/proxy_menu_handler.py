from google import genai
from google.genai import types
from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from data.config import GEMINI_KEY
from db.main import (
    disable_user_gemini_proxy,
    get_user_gemini_proxy_config,
    set_user_gemini_proxy,
    set_user_gemini_proxy_health,
)
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.states import AdminStates
from loader import router
from utils.proxy_utils import compact_proxy_display, normalize_http_proxy_input


def _proxy_status_label(proxy_cfg: dict) -> str:
    enabled = int(proxy_cfg.get("enabled", 0) or 0)
    status = int(proxy_cfg.get("status", 0) or 0)
    if not enabled:
        return constant_text.PROXY_STATUS_DISABLED_TEXT
    if status == 1:
        return constant_text.PROXY_STATUS_OK_TEXT
    return constant_text.PROXY_STATUS_PENDING_TEXT


def _proxy_menu_text(proxy_cfg: dict) -> str:
    proxy_text = compact_proxy_display(proxy_cfg.get("proxy"))
    status_text = _proxy_status_label(proxy_cfg)
    checked_at = int(proxy_cfg.get("checked_at", 0) or 0)
    last_error = (proxy_cfg.get("last_error") or "").strip()

    checked_line = f"{checked_at}" if checked_at > 0 else constant_text.PROXY_MENU_NO_DATA_TEXT
    error_line = last_error[:120] if last_error else constant_text.PROXY_MENU_NO_DATA_TEXT

    return constant_text.PROXY_MENU_PROMPT_TEXT.format(
        proxy=proxy_text,
        status=status_text,
        checked_at=checked_line,
        error=error_line,
    )


async def _check_proxy(admin_id: int, proxy_url: str) -> tuple[bool, str]:
    if not GEMINI_KEY:
        return False, constant_text.PROXY_GEMINI_KEY_EMPTY_TEXT

    http_options = types.HttpOptions(
        client_args={"proxy": proxy_url},
        async_client_args={"proxy": proxy_url},
    )
    client = genai.Client(api_key=GEMINI_KEY, http_options=http_options)

    try:
        await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents="ping",
        )
        await set_user_gemini_proxy_health(admin_id, is_ok=True)
        return True, "ok"
    except Exception as exc:
        err = str(exc)[:220]
        await set_user_gemini_proxy_health(admin_id, is_ok=False, error=err)
        return False, err


@router.message(IsPrivate(), IsAdmin(), F.text.in_(constant_text.PROXY_USER_KEYBOARD), StateFilter("*"))
async def open_proxy_menu_handler(message: Message, state: FSMContext):
    await state.clear()
    cfg = await get_user_gemini_proxy_config(message.from_user.id)
    await message.answer(_proxy_menu_text(cfg))
    await state.set_state(AdminStates.wait_proxy_manager)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:proxy:open", StateFilter("*"))
async def open_proxy_menu_from_settings_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    cfg = await get_user_gemini_proxy_config(call.from_user.id)
    await call.message.edit_text(_proxy_menu_text(cfg))
    await state.set_state(AdminStates.wait_proxy_manager)
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "set:proxy:check", StateFilter("*"))
async def check_proxy_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    cfg = await get_user_gemini_proxy_config(call.from_user.id)
    proxy = cfg.get("proxy")
    enabled = int(cfg.get("enabled", 0) or 0)

    if not enabled or not proxy:
        await call.answer(constant_text.GEMINI_PROXY_REQUIRED_TEXT)
        return

    ok, reason = await _check_proxy(call.from_user.id, str(proxy))
    cfg = await get_user_gemini_proxy_config(call.from_user.id)

    if ok:
        await call.answer(constant_text.PROXY_CHECK_OK_TEXT)
    else:
        await call.answer(constant_text.PROXY_CHECK_FAIL_TEXT.format(reason=reason[:80]))

    await call.message.edit_text(_proxy_menu_text(cfg))


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.wait_proxy_manager))
async def save_proxy_handler(message: Message, state: FSMContext):
    text = (message.text or "").strip()

    if text in {"/start", "/cancel", constant_text.ACTION_CANCEL_TEXT, constant_text.SETTINGS_BOT_KEYBOARD[2]}:
        await state.clear()
        await message.answer(constant_text.ACTION_CANCELLED_TEXT)
        return

    if text == "0":
        await disable_user_gemini_proxy(message.from_user.id, reason="manual_disable")
        cfg = await get_user_gemini_proxy_config(message.from_user.id)
        await message.answer(constant_text.PROXY_DISABLED_TEXT)
        await message.answer(_proxy_menu_text(cfg))
        await state.set_state(AdminStates.wait_proxy_manager)
        return

    proxy_url = normalize_http_proxy_input(text)
    if not proxy_url:
        await message.answer(constant_text.PROXY_INVALID_FORMAT_TEXT)
        await state.set_state(AdminStates.wait_proxy_manager)
        return

    await set_user_gemini_proxy(message.from_user.id, proxy_url)
    cfg = await get_user_gemini_proxy_config(message.from_user.id)

    await message.answer(constant_text.PROXY_SET_TEXT)
    await message.answer(_proxy_menu_text(cfg))
    await state.set_state(AdminStates.wait_proxy_manager)


