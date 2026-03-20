import re

from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import data.text as constant_text
from db.main import (
    find_user_ids_by_username,
    get_chat_history_events,
    get_chat_history_events_by_chat_ids,
    get_user,
    get_user_timezone_offset,
)
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.states import AdminStates
from loader import router
from utils.datetime_tools import DateTime


def _mask_account_id(value: int | None) -> str:
    if not value:
        return "unknown"

    raw = str(abs(int(value)))
    if len(raw) <= 4:
        return f"{raw[:2]}**"
    return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


def _action_label(action_id: int) -> str:
    if int(action_id) == 1:
        return "✅ чат найден"
    if int(action_id) == 2:
        return "🧹 чат очищен"
    return f"action:{action_id}"


def _extract_query(message_text: str) -> str:
    text = (message_text or "").strip()
    if text.startswith("/chat_history"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return ""
        return parts[1].strip()
    return text


async def _resolve_chat_ids(query: str) -> list[int]:
    if re.fullmatch(r"-?\d+", query):
        return [int(query)]
    return await find_user_ids_by_username(query)


async def _render_history(message: Message, query: str, admin_id: int) -> None:
    chat_ids = await _resolve_chat_ids(query)
    if not chat_ids:
        await message.answer(constant_text.CHAT_HISTORY_SEARCH_EMPTY_TEXT)
        return

    if len(chat_ids) == 1:
        events = await get_chat_history_events(admin_id=admin_id, chat_id=chat_ids[0], limit=250)
    else:
        events = await get_chat_history_events_by_chat_ids(admin_id=admin_id, chat_ids=chat_ids, limit=500)
    if not events:
        await message.answer(constant_text.CHAT_HISTORY_SEARCH_EMPTY_TEXT)
        return

    tz_offset = await get_user_timezone_offset(admin_id)
    dt = DateTime(tz_offset)

    lines: list[str] = [
        "<b>История чата</b>",
        f"query: <code>{query}</code>",
        f"matches: {len(chat_ids)}",
        "",
    ]

    account_cache: dict[int, str] = {}
    for item in events[-30:]:
        event_chat_id = int(item.chat_id or item.user_id)
        account_user_id = int(item.account_user_id or 0)
        if account_user_id and account_user_id not in account_cache:
            account_user = await get_user(account_user_id)
            account_name = (account_user.full_name if account_user else None) or (account_user.username if account_user else None)
            if account_name:
                account_cache[account_user_id] = f"{_mask_account_id(account_user_id)} ({account_name})"
            else:
                account_cache[account_user_id] = _mask_account_id(account_user_id)

        account_label = account_cache.get(account_user_id, _mask_account_id(account_user_id))
        stamp = dt.convert_timestamp(int(item.date), "%d.%m.%Y %H:%M:%S")["str"]
        lines.append(
            f"{stamp} | {_action_label(int(item.action_id))} | user_id <code>{event_chat_id}</code> | account {account_label}"
        )
    await message.answer("\n".join(lines))


@router.message(IsPrivate(), IsAdmin(), StateFilter("*"), F.text == constant_text.ACCOUNTS_USER_KEYBOARD[1])
async def open_chat_history_search_handler(message: Message, state: FSMContext):
    await state.set_state(AdminStates.wait_chat_history_search)
    await message.answer(constant_text.CHAT_HISTORY_SEARCH_PROMPT_TEXT)


@router.message(IsPrivate(), IsAdmin(), StateFilter("*"), F.text.startswith("/chat_history"))
async def chat_history_by_id_handler(message: Message, state: FSMContext):
    _ = state
    query = _extract_query(message.text or "")
    if not query:
        return await message.answer(constant_text.CHAT_HISTORY_SEARCH_USAGE_TEXT)
    await _render_history(message, query=query, admin_id=message.from_user.id)


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.wait_chat_history_search))
async def chat_history_search_input_handler(message: Message, state: FSMContext):
    query = _extract_query(message.text or "")
    if not query:
        return await message.answer(constant_text.CHAT_HISTORY_SEARCH_USAGE_TEXT)
    await _render_history(message, query=query, admin_id=message.from_user.id)
    await state.clear()
