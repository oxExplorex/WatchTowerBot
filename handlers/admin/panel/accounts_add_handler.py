import asyncio
import re
import traceback
from pathlib import Path
from uuid import uuid4

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from pyrogram import Client
from pyrogram.errors import PhoneCodeExpired, SessionPasswordNeeded

import data.text as constant_text
from core.logging import bot_logger
from core.auth_sessions import auth_clients, discard_session_files
from core.session_files import replace_session_files, session_paths
from core.account_runtime import account_guard
from core.session_runtime import get_client_by_number, start_client, stop_and_remove_session
from db.main import create_unit_of_work, get_account_by_number, get_account_tg_to_user_id, get_app_tg_uuid, is_admin
from db.repositories.account_locks import AccountAlreadyConnected
from data.texts import account_ownership as ownership_text
from db.repositories.account_operations_repo import AccountOperationsRepository
from db.session import get_session_factory
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.states import AdminStates
from keyboards.main.start_keyboard import static_admin_keyboard
from keyboards.inline.back_inline import back_inline
from loader import session_manager

from utils.others import close_state_pyrogram_client, not_warning_delete_message

router = Router(name=__name__)


_session_locks: dict[str, asyncio.Lock] = {}


def _get_session_lock(number: str) -> asyncio.Lock:
    lock = _session_locks.get(number)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[number] = lock
    return lock


def _session_paths(session_name: str) -> list[str]:
    return [str(path) for path in session_paths(session_name)]


def _temp_session_name(owner_id: int, number: str) -> str:
    return f"data/session/_auth_{owner_id}_{number}_{uuid4().hex}"


async def _cleanup_session_files(session_name: str) -> None:
    await discard_session_files(session_name)


async def _save_authorized_session(data: dict, result, owner_id: int, *, update_profile: bool = False) -> None:
    number = data["number"]
    temporary_name = data["temp_session_name"]
    final_name = f"data/session/{number}"
    async with account_guard(("session", number)):
        if not await is_admin(owner_id):
            raise PermissionError("Доступ администратора отозван.")
        existing = await get_account_tg_to_user_id(result.id)
        if existing is not None and existing.admin_id != owner_id:
            raise AccountAlreadyConnected(ownership_text.ALREADY_CONNECTED)
        if await AccountOperationsRepository(get_session_factory).is_busy(result.id):
            raise AccountAlreadyConnected(ownership_text.ALREADY_CONNECTED)
        if not Path(f"{temporary_name}.session").is_file():
            raise FileNotFoundError("Authorized temporary session is missing")
        previous_client = await get_client_by_number(number)
        was_initialized = bool(getattr(previous_client, "is_initialized", False))
        was_connected = bool(getattr(previous_client, "is_connected", False))
        await stop_and_remove_session(number)
        try:
            with replace_session_files(temporary_name, final_name):
                async with create_unit_of_work() as uow:
                    if not await is_admin(owner_id):
                        raise PermissionError("Доступ администратора отозван.")
                    account = await uow.accounts.create_account_tg(owner_id, result.id, data["uuid_app"], number)
                    if account is None:
                        raise RuntimeError("Cannot save authorized account")
                    if update_profile:
                        await uow.users.update_user(result.id, result.username, result.full_name)
        except BaseException:
            if previous_client is not None:
                try:
                    await session_manager.add(previous_client)
                    if was_initialized:
                        await start_client(previous_client)
                    elif was_connected:
                        await start_client(previous_client, connect_only=True)
                except Exception as exc:
                    bot_logger.error("Failed to restore previous client: %s", type(exc).__name__)
            raise


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("account_admin_menu_add:"), StateFilter("*"))
async def start_add_account_handler(call: CallbackQuery, state: FSMContext):
    previous = await state.get_data()
    await close_state_pyrogram_client(state)
    if previous.get("temp_session_name"):
        await _cleanup_session_files(previous["temp_session_name"])
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

    if await get_account_by_number(number) is not None:
        await state.clear()
        return await message.answer(ownership_text.ALREADY_CONNECTED)

    app_info = await get_app_tg_uuid(data["uuid_app"], user_id)
    if not app_info:
        await close_state_pyrogram_client(state)
        await state.clear()
        return await message.answer(constant_text.ERROR_NOT_FOUND_APP_ID)

    temp_session_name = _temp_session_name(user_id, number)
    session_lock = _get_session_lock(number)
    async with session_lock:
        try:
            await _cleanup_session_files(temp_session_name)
        except PermissionError:
            await close_state_pyrogram_client(state)
            return await message.answer(constant_text.ACCOUNT_ADD_SESSION_BUSY_TEXT)

    bot_logger.debug("Starting account authorization for owner_id=%s", user_id)

    app_temp = Client(
        name=temp_session_name,
        phone_number=number,
        api_id=app_info.app_id,
        api_hash=app_info.api_hash,
    )
    auth_clients.register(app_temp, temp_session_name, state)

    try:
        await app_temp.connect()
        result = await app_temp.send_phone_number_code(phone_number=number)

        prompt_message = await message.answer(constant_text.ACCOUNT_INPUT_CODE_TEXT)
        await state.update_data(
            prompt_message=prompt_message,
            app_temp=app_temp,
            number=number,
            temp_session_name=temp_session_name,
            phone_hash=result.phone_code_hash,
        )
        await state.set_state(AdminStates.account_add_code)
    except BaseException as exc:
        if isinstance(exc, Exception):
            bot_logger.error(traceback.format_exc())
        await auth_clients.discard(app_temp)
        await _cleanup_session_files(temp_session_name)
        await state.clear()
        if not isinstance(exc, Exception):
            raise
        return await message.answer(f"{constant_text.ACCOUNT_ADD_ERROR_PREFIX}: {exc}")


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.account_add_code))
async def receive_account_code_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    auth_clients.track(data["app_temp"])
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
    temp_session_name = data["temp_session_name"]

    keep_client = False
    try:
        result = await app_temp.sign_in(
            phone_number=number,
            phone_code_hash=phone_hash,
            phone_code=code,
        )
        await auth_clients.disconnect(app_temp)
        await _save_authorized_session(data, result, user_id)
        await message.answer(constant_text.SUCCESS_ADD_ACCOUNT_TEXT)
        await state.clear()
    except SessionPasswordNeeded:
        prompt_message = await message.answer(constant_text.ACCOUNT_INPUT_PASSWORD_TEXT)
        await state.update_data(prompt_message=prompt_message)
        await state.set_state(AdminStates.account_add_password)
        keep_client = True
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
    finally:
        if not keep_client:
            await auth_clients.discard(app_temp)


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.account_add_password))
async def receive_account_password_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    auth_clients.track(data["app_temp"])
    app_temp = data["app_temp"]
    user_id = message.from_user.id
    number = data["number"]
    temp_session_name = data["temp_session_name"]
    password = (message.text or "").strip()

    await not_warning_delete_message(message=data.get("prompt_message"))
    await not_warning_delete_message(message=message)

    if not password:
        return await message.answer(constant_text.ERROR_FORMAT_TEXT)

    try:
        result = await app_temp.check_password(password)
        await auth_clients.disconnect(app_temp)
        await _save_authorized_session(data, result, user_id, update_profile=True)

        await message.answer(constant_text.SUCCESS_ADD_ACCOUNT_TEXT)
        await state.clear()
    except Exception as exc:
        await close_state_pyrogram_client(state)
        await message.answer(f"{constant_text.ACCOUNT_ADD_ERROR_PREFIX}: {exc}")
        await _cleanup_session_files(temp_session_name)
        await state.clear()
    finally:
        await auth_clients.discard(app_temp)
