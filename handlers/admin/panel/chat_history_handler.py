import re

from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import data.text as constant_text
from db.main import (
    find_user_ids_by_username,
    get_account_all,
    get_chat_history_events,
    get_chat_history_events_by_chat_ids,
    get_dump_chat_user,
    get_user,
    get_user_timezone_offset,
)
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.states import AdminStates
from loader import router
from utils.datetime_tools import DateTime


def _mask_account_id(value: int | None) -> str:
    if not value:
        return constant_text.CHAT_HISTORY_UNKNOWN_TEXT

    raw = str(abs(int(value)))
    if len(raw) <= 4:
        return f"{raw[:2]}**"
    return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


def _action_label(action_id: int) -> str:
    if int(action_id) == 1:
        return constant_text.CHAT_HISTORY_ACTION_FOUND_TEXT
    if int(action_id) == 2:
        return constant_text.CHAT_HISTORY_ACTION_CLEARED_TEXT
    return constant_text.CHAT_HISTORY_ACTION_FORMAT_TEXT.format(action_id=action_id)


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


async def _send_chunked(message: Message, text: str, chunk_size: int = 3800) -> None:
    lines = text.splitlines()
    buf: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + 1
        if buf and (size + extra) > chunk_size:
            await message.answer("\n".join(buf))
            buf = []
            size = 0
        buf.append(line)
        size += extra

    if buf:
        await message.answer("\n".join(buf))


async def _current_presence_lines(admin_id: int, chat_ids: list[int]) -> list[str]:
    accounts = [x for x in await get_account_all(active_only=False) if int(x.admin_id or 0) == int(admin_id)]
    account_names: dict[int, str] = {}
    for account in accounts:
        user_id = int(account.user_id or 0)
        if user_id <= 0:
            continue
        owner_user = await get_user(user_id)
        account_names[user_id] = (
            (owner_user.full_name if owner_user else None)
            or (owner_user.username if owner_user else None)
            or str(user_id)
        )

    lines = [constant_text.CHAT_HISTORY_PRESENCE_TITLE_TEXT]
    for chat_id in chat_ids:
        holders: list[str] = []
        for account in accounts:
            owner_user_id = int(account.user_id or 0)
            if owner_user_id <= 0:
                continue
            if await get_dump_chat_user(owner_user_id, int(chat_id)):
                holders.append(f"{account_names.get(owner_user_id, str(owner_user_id))} [{_mask_account_id(owner_user_id)}]")

        chat_user = await get_user(int(chat_id))
        chat_label = (
            (chat_user.full_name if chat_user else None)
            or (chat_user.username if chat_user else None)
            or str(chat_id)
        )
        if holders:
            lines.append(
                constant_text.CHAT_HISTORY_PRESENCE_FOUND_FORMAT_TEXT.format(
                    chat_id=chat_id,
                    chat_label=chat_label,
                    holders=", ".join(holders),
                )
            )
        else:
            lines.append(
                constant_text.CHAT_HISTORY_PRESENCE_MISSING_FORMAT_TEXT.format(
                    chat_id=chat_id,
                    chat_label=chat_label,
                )
            )

    lines.append("")
    return lines


async def _render_history(message: Message, query: str, admin_id: int) -> None:
    chat_ids = await _resolve_chat_ids(query)
    if not chat_ids:
        await message.answer(constant_text.CHAT_HISTORY_SEARCH_EMPTY_TEXT)
        return

    presence_lines = await _current_presence_lines(admin_id=admin_id, chat_ids=chat_ids)

    if len(chat_ids) == 1:
        events = await get_chat_history_events(admin_id=admin_id, chat_id=chat_ids[0], limit=250)
    else:
        events = await get_chat_history_events_by_chat_ids(admin_id=admin_id, chat_ids=chat_ids, limit=500)

    tz_offset = await get_user_timezone_offset(admin_id)
    dt = DateTime(tz_offset)

    lines: list[str] = [
        constant_text.CHAT_HISTORY_BLOCK_TITLE_TEXT,
        constant_text.CHAT_HISTORY_QUERY_FORMAT_TEXT.format(query=query),
        constant_text.CHAT_HISTORY_MATCHES_FORMAT_TEXT.format(count=len(chat_ids)),
        "",
    ]
    lines.extend(presence_lines)
    if not events:
        lines.append(constant_text.CHAT_HISTORY_SEARCH_EMPTY_TEXT)
        await _send_chunked(message, "\n".join(lines))
        return

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
            constant_text.CHAT_HISTORY_EVENT_FORMAT_TEXT.format(
                stamp=stamp,
                action_label=_action_label(int(item.action_id)),
                chat_id=event_chat_id,
                account_label=account_label,
            )
        )
    await _send_chunked(message, "\n".join(lines))


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
