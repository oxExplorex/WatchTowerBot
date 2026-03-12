import asyncio
import os
import re
import traceback
from pathlib import Path

from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from pyrogram import Client
from pyrogram.errors import PhoneCodeExpired, SessionPasswordNeeded

import data.text as constant_text
from core.logging import bot_logger
from core.session_runtime import stop_and_remove_session
from db.main import create_account_tg, get_app_tg_uuid, update_user
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.states import AdminStates
from keyboards.main.start_keyboard import static_admin_keyboard
from keyboards.inline.back_inline import back_inline
from loader import router
from utils.others import close_state_pyrogram_client, not_warning_delete_message


_session_locks: dict[str, asyncio.Lock] = {}


def _get_session_lock(number: str) -> asyncio.Lock:
    lock = _session_locks.get(number)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[number] = lock
    return lock


def _session_paths(session_name: str) -> list[str]:
    return [
        session_name,
        f"{session_name}.session",
        f"{session_name}.session-shm",
        f"{session_name}.session-wal",
    ]


def _temp_session_name(owner_id: int, number: str) -> str:
    return f"data/session/_auth_{owner_id}_{number}"


async def _cleanup_session_files(session_name: str) -> None:
    session_paths = _session_paths(session_name)

    for path in session_paths:
        for attempt in range(3):
            try:
                await asyncio.to_thread(os.remove, path)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.2)


async def _promote_session_files(temp_name: str, final_name: str) -> None:
    await _cleanup_session_files(final_name)
    for src_path in _session_paths(temp_name):
        dst_path = src_path.replace(temp_name, final_name, 1)
        src = Path(src_path)
        if not await asyncio.to_thread(src.exists):
            continue
        await asyncio.to_thread(os.replace, src_path, dst_path)


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("account_admin_menu_add:"), StateFilter("*"))
async def start_add_account_handler(call: CallbackQuery, state: FSMContext):
    await close_state_pyrogram_client(state)
    await state.clear()

    try:
        uuid_app = call.data.split(":")[-1]
    except (AttributeError, IndexError, TypeError):
        return await call.answer(constant_text.ERROR_FORMAT_TEXT)

    prompt_message = await call.message.answer(
        text=constant_text.ACCOUNT_INPUT_NUMBER_TEXT,
        reply_markup=back_inline(),
    )

    await state.update_data(prompt_message=prompt_message, uuid_app=uuid_app)
    await state.set_state(AdminStates.account_add_number)

@router.message(
    IsPrivate(),
    IsAdmin(),
    StateFilter(
        AdminStates.account_add_number,
        AdminStates.account_add_code,
        AdminStates.account_add_password,
    ),
    F.text.in_([constant_text.ACTION_CANCEL_TEXT, constant_text.ACTION_CANCEL_COMMAND]),
)
async def cancel_add_account_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    temp_session_name = data.get("temp_session_name")
    await close_state_pyrogram_client(state)
    await state.clear()
    if temp_session_name:
        await _cleanup_session_files(temp_session_name)

    await not_warning_delete_message(message=data.get("prompt_message"))
    await not_warning_delete_message(message=message)

    await message.answer(
        text=constant_text.ACTION_CANCELLED_TEXT,
        reply_markup=static_admin_keyboard(),
    )


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.account_add_number))
async def receive_account_number_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    await not_warning_delete_message(message=data.get("prompt_message"))

    number = "".join(re.findall(r"\d+", message.text or ""))
    await not_warning_delete_message(message=message)

    if not number:
        return await message.answer(constant_text.ERROR_FORMAT_TEXT)

    app_info = await get_app_tg_uuid(data["uuid_app"], user_id)
    if not app_info:
        await close_state_pyrogram_client(state)
        await state.clear()
        return await message.answer(constant_text.ERROR_NOT_FOUND_APP_ID)

    final_session_name = f"data/session/{number}"
    temp_session_name = _temp_session_name(user_id, number)
    session_lock = _get_session_lock(number)
    async with session_lock:
        await stop_and_remove_session(number)

        try:
            await _cleanup_session_files(final_session_name)
            await _cleanup_session_files(temp_session_name)
        except PermissionError:
            await close_state_pyrogram_client(state)
            return await message.answer(constant_text.ACCOUNT_ADD_SESSION_BUSY_TEXT)

    bot_logger.debug(f"{number} {app_info.app_id} {app_info.api_hash}")

    app_temp = Client(
        name=temp_session_name,
        phone_number=number,
        api_id=app_info.app_id,
        api_hash=app_info.api_hash,
    )

    try:
        await app_temp.connect()
        result = await app_temp.send_code(phone_number=number)

        prompt_message = await message.answer(constant_text.ACCOUNT_INPUT_CODE_TEXT)
        await state.update_data(
            prompt_message=prompt_message,
            app_temp=app_temp,
            number=number,
            temp_session_name=temp_session_name,
            phone_hash=result.phone_code_hash,
        )
        await state.set_state(AdminStates.account_add_code)
    except Exception as exc:
        bot_logger.error(traceback.format_exc())
        if app_temp.is_connected:
            await app_temp.disconnect()
        await _cleanup_session_files(temp_session_name)
        await state.clear()
        return await message.answer(f"{constant_text.ACCOUNT_ADD_ERROR_PREFIX}: {exc}")


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.account_add_code))
async def receive_account_code_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    temp_session_name = data.get("temp_session_name")
    await not_warning_delete_message(message=data.get("prompt_message"))

    code = "".join(re.findall(r"\d+", message.text or ""))
    await not_warning_delete_message(message=message)

    if not code:
        await close_state_pyrogram_client(state)
        await state.clear()
        if temp_session_name:
            await _cleanup_session_files(temp_session_name)
        return await message.answer(
            text=constant_text.ERROR_FORMAT_TEXT,
            reply_markup=static_admin_keyboard(),
        )

    app_info = await get_app_tg_uuid(data["uuid_app"], user_id)
    if not app_info:
        await close_state_pyrogram_client(state)
        await state.clear()
        return await message.answer(constant_text.ERROR_NOT_FOUND_APP_ID)

    number = data["number"]
    phone_hash = data["phone_hash"]
    app_temp = data["app_temp"]
    temp_session_name = data.get("temp_session_name") or _temp_session_name(user_id, number)
    final_session_name = f"data/session/{number}"
    session_lock = _get_session_lock(number)

    try:
        result = await app_temp.sign_in(
            phone_number=number,
            phone_code_hash=phone_hash,
            phone_code=code,
        )
        await app_temp.disconnect()
        async with session_lock:
            await _promote_session_files(temp_session_name, final_session_name)

        await create_account_tg(user_id, result.id, data["uuid_app"], number)
        await message.answer(constant_text.SUCCESS_ADD_ACCOUNT_TEXT)
        await state.clear()
    except SessionPasswordNeeded:
        prompt_message = await message.answer(constant_text.ACCOUNT_INPUT_PASSWORD_TEXT)
        await state.update_data(prompt_message=prompt_message)
        await state.set_state(AdminStates.account_add_password)
        return
    except PhoneCodeExpired:
        await close_state_pyrogram_client(state)
        await message.answer(constant_text.ACCOUNT_ADD_CODE_EXPIRED_TEXT)
        await _cleanup_session_files(temp_session_name)
        await state.set_state(AdminStates.account_add_number)
    except Exception as exc:
        bot_logger.error(traceback.format_exc())
        await close_state_pyrogram_client(state)
        await message.answer(f"{constant_text.ACCOUNT_ADD_ERROR_PREFIX}: {exc}")
        await _cleanup_session_files(temp_session_name)
        await state.clear()


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.account_add_password))
async def receive_account_password_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    app_temp = data["app_temp"]
    user_id = message.from_user.id
    number = data["number"]
    temp_session_name = data.get("temp_session_name") or _temp_session_name(user_id, number)
    final_session_name = f"data/session/{number}"
    session_lock = _get_session_lock(number)
    password = (message.text or "").strip()

    await not_warning_delete_message(message=data.get("prompt_message"))
    await not_warning_delete_message(message=message)

    if not password:
        return await message.answer(constant_text.ERROR_FORMAT_TEXT)

    try:
        result = await app_temp.check_password(password)
        await app_temp.disconnect()
        async with session_lock:
            await _promote_session_files(temp_session_name, final_session_name)

        await create_account_tg(user_id, result.id, data["uuid_app"], number)
        await update_user(result.id, result.username, result.full_name)

        await message.answer(constant_text.SUCCESS_ADD_ACCOUNT_TEXT)
        await state.clear()
    except Exception as exc:
        await close_state_pyrogram_client(state)
        await message.answer(f"{constant_text.ACCOUNT_ADD_ERROR_PREFIX}: {exc}")
        await _cleanup_session_files(temp_session_name)
        await state.clear()
