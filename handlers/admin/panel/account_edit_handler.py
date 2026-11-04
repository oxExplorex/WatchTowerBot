import asyncio
from contextlib import suppress

from aiogram import F, Router, html
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import data.text as constant_text
from core.session_runtime import get_client_by_number, is_session_running, run_client_operation, stop_and_remove_session
from core.session_manager import SessionUnavailable
from core.telegram_errors import is_fatal_session_error as _is_fatal_session_error
from core.session_files import account_session_paths, remove_account_session_files
from db.models import Account
from db.main import (
    add_account_health_event,
    delete_account_by_number,
    get_account_health_events,
    get_account_user_id,
    get_account_uuid,
    get_app_tg_user_id,
    get_app_tg_uuid,
    get_user_timezone_offset,
    get_user_names_by_ids,
    update_account_uuid,
)
from filters.all_filters import IsAccountManager, IsPrivate
from keyboards.inline.account_manage.account_edit_inline import account_edit_admin_inline
from keyboards.inline.account_manage.account_menu_inline import account_tg_admin_inline

from utils.datetime_tools import DateTime
from utils.settings_formatting import build_hourly_rows_desc

router = Router(name=__name__)

PAGE_SIZE = 5


def _format_last_update(ts_value, dt: DateTime) -> str:
    if not ts_value:
        return constant_text.ACCOUNT_NO_DATA_TEXT
    try:
        return dt.convert_timestamp(int(ts_value))["str"]
    except Exception:
        return str(ts_value)


def _build_hourly_rows_desc(events, hours: int, dt: DateTime) -> list[str]:
    return build_hourly_rows_desc(events, hours, dt, label_format="%d.%m %H:00")


def _spoil(value) -> str:
    return f"<tg-spoiler>{html.quote(str(value))}</tg-spoiler>"


def _account_uuid_from_callback(call: CallbackQuery) -> str | None:
    try:
        return call.data.split(":")[-1]
    except (AttributeError, IndexError, TypeError):
        return None


def _session_files_exist(number: str | None) -> bool:
    if not number:
        return False
    return any(path.is_file() for path in account_session_paths(number))


async def _session_files_exist_async(number: str | None) -> bool:
    return await asyncio.to_thread(_session_files_exist, number)


async def _remove_session_files(number: str | None) -> None:
    if not number:
        return
    await asyncio.to_thread(remove_account_session_files, number)




async def _show_accounts_or_close(call: CallbackQuery) -> None:
    accounts, count = await get_account_user_id(call.from_user.id, 0)
    if count <= 0:
        with suppress(Exception):
            await call.message.delete()
        return

    tz_offset = await get_user_timezone_offset(call.from_user.id)
    dt = DateTime(tz_offset)

    _, apps_count = await get_app_tg_user_id(call.from_user.id)
    total_pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    names = await get_user_names_by_ids([account.user_id for account in accounts])
    keyboard = await account_tg_admin_inline(accounts, 1, total_pages, names=names)

    await call.message.edit_text(
        text=constant_text.ACCOUNT_COUNT_INFO_TEXT.format(
            _count=count,
            _count_apps=apps_count,
            date=dt.time_strftime("%d.%m.%Y %H:%M:%S.%f"),
        ),
        reply_markup=keyboard,
    )


async def _drop_dead_session_from_editor(call: CallbackQuery, account: Account, reason: str) -> None:
    await stop_and_remove_session(account.number)

    deleted = await delete_account_by_number(account.number)
    if not deleted:
        return

    now_ts = DateTime().timestamp()
    await add_account_health_event(
        account_uuid=deleted.uuid,
        admin_id=deleted.admin_id,
        user_id=deleted.user_id,
        status=0,
        date=now_ts,
        reason=f"manual_drop:{reason}",
    )

    await _remove_session_files(account.number)

    with suppress(Exception):
        await call.message.answer(constant_text.ACCOUNT_INVALID_REMOVED_TEXT)


async def _update_account_or_close(call: CallbackQuery, account: Account, **fields) -> Account | None:
    updated = await update_account_uuid(account.uuid, call.from_user.id, **fields)
    if updated is None:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        await _show_accounts_or_close(call)
        return None
    return updated


async def _render_account_editor(call: CallbackQuery, account: Account) -> None:
    app_tg = await get_app_tg_uuid(account.app_tg, call.from_user.id)
    if not app_tg:
        return await call.answer(constant_text.ERROR_NOT_FOUND_APP_ID)

    tz_offset = await get_user_timezone_offset(call.from_user.id)
    dt = DateTime(tz_offset)

    since_48h = dt.timestamp() - 60 * 60 * 48
    events_48h = await get_account_health_events(account.uuid, since_48h)
    rows_48h = _build_hourly_rows_desc(events_48h, hours=48, dt=dt)

    status_runtime = (
        constant_text.ACCOUNT_RUNTIME_ONLINE_TEXT
        if await is_session_running(account.number)
        else constant_text.ACCOUNT_RUNTIME_OFFLINE_TEXT
    )
    state_text = (
        constant_text.ACCOUNT_STATUS_ENABLED_TEXT
        if account.is_active
        else constant_text.ACCOUNT_STATUS_DISABLED_TEXT
    )

    await call.message.edit_text(
        text=constant_text.ACCOUNT_EDIT_INFO_TEXT.format(
            user_id=account.user_id,
            number=_spoil(account.number),
            app_id=_spoil(app_tg.app_id),
            api_hash=_spoil(app_tg.api_hash),
            last_update=_format_last_update(account.last_update, dt=dt),
            session_status=f"{state_text} | {status_runtime}",
            hours_chart="\n".join(rows_48h),
            date=dt.time_strftime("%d.%m.%Y %H:%M:%S"),
        ),
        reply_markup=await account_edit_admin_inline(account),
    )
    return None


async def _get_account_from_callback(call: CallbackQuery) -> Account | None:
    account_uuid = _account_uuid_from_callback(call)
    if account_uuid is None:
        return None
    return await get_account_uuid(account_uuid, call.from_user.id)


@router.callback_query(IsPrivate(), IsAccountManager(), F.data.startswith("acc:e:"), StateFilter("*"))
async def accounts_edit_menu_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    account = await _get_account_from_callback(call)
    if not account:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        return await _show_accounts_or_close(call)

    await _render_account_editor(call, account)


@router.callback_query(IsPrivate(), IsAccountManager(), F.data.startswith("acc:ts:"), StateFilter("*"))
async def account_toggle_session_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    account = await _get_account_from_callback(call)
    if not account:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        return await _show_accounts_or_close(call)

    new_active = 0 if account.is_active else 1
    account = await _update_account_or_close(call, account, is_active=new_active)
    if account is None:
        return

    if new_active == 0:
        await stop_and_remove_session(account.number)
    else:
        await call.answer(constant_text.ACCOUNT_SESSION_ENABLED_TOAST)

    await _render_account_editor(call, account)


@router.callback_query(IsPrivate(), IsAccountManager(), F.data.startswith("acc:tn:"), StateFilter("*"))
async def account_toggle_new_chat_alert_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    account = await _get_account_from_callback(call)
    if not account:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        return await _show_accounts_or_close(call)

    account = await _update_account_or_close(
        call,
        account,
        alert_new_chat=0 if account.alert_new_chat else 1,
    )
    if account is None:
        return
    await _render_account_editor(call, account)


@router.callback_query(IsPrivate(), IsAccountManager(), F.data.startswith("acc:td:"), StateFilter("*"))
async def account_toggle_deleted_chat_alert_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    account = await _get_account_from_callback(call)
    if not account:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        return await _show_accounts_or_close(call)

    account = await _update_account_or_close(
        call,
        account,
        alert_del_chat=0 if account.alert_del_chat else 1,
    )
    if account is None:
        return
    await _render_account_editor(call, account)


@router.callback_query(IsPrivate(), IsAccountManager(), F.data.startswith("acc:tb:"), StateFilter("*"))
async def account_toggle_bot_alert_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    account = await _get_account_from_callback(call)
    if not account:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        return await _show_accounts_or_close(call)

    account = await _update_account_or_close(
        call,
        account,
        alert_bot=0 if account.alert_bot else 1,
    )
    if account is None:
        return
    await _render_account_editor(call, account)


@router.callback_query(IsPrivate(), IsAccountManager(), F.data.startswith("acc:tm:"), StateFilter("*"))
async def account_toggle_media_spoiler_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    account = await _get_account_from_callback(call)
    if not account:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        return await _show_accounts_or_close(call)

    current = int(getattr(account, "alert_spoiler_media", 1) or 0)
    account = await _update_account_or_close(
        call,
        account,
        alert_spoiler_media=0 if current else 1,
    )
    if account is None:
        return
    await _render_account_editor(call, account)


@router.callback_query(IsPrivate(), IsAccountManager(), F.data.startswith("acc:chk:"), StateFilter("*"))
async def account_check_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    account = await _get_account_from_callback(call)
    if not account:
        await call.answer(constant_text.ERROR_NOT_FOUND_ACCOUNT_ID)
        return await _show_accounts_or_close(call)

    tz_offset = await get_user_timezone_offset(call.from_user.id)
    now_ts = DateTime(tz_offset).timestamp()
    client = await get_client_by_number(account.number)

    if client is None:
        await add_account_health_event(account.uuid, account.admin_id, account.user_id, 0, now_ts, "not_running")

        if account.is_active and not await _session_files_exist_async(account.number):
            await _drop_dead_session_from_editor(call, account, "not_running_no_session_file")
            await call.answer(constant_text.ACCOUNT_SESSION_REMOVED_NO_FILE_TOAST)
            return await _show_accounts_or_close(call)

        await call.answer(constant_text.ACCOUNT_SESSION_NOT_RUNNING_TOAST)
        return await _render_account_editor(call, account)

    try:
        await run_client_operation(client, client.get_me)
        await update_account_uuid(account.uuid, account.admin_id, last_update=now_ts)
        await add_account_health_event(account.uuid, account.admin_id, account.user_id, 1, now_ts, "manual_check")
        await call.answer(constant_text.ACCOUNT_SESSION_RESPONDS_TOAST)
    except SessionUnavailable:
        await call.answer(constant_text.ACCOUNT_SESSION_NOT_RUNNING_TOAST)
    except Exception as exc:
        await add_account_health_event(account.uuid, account.admin_id, account.user_id, 0, now_ts, exc.__class__.__name__)

        if _is_fatal_session_error(exc):
            await _drop_dead_session_from_editor(call, account, exc.__class__.__name__)
            await call.answer(constant_text.ACCOUNT_SESSION_INVALID_REMOVED_TOAST)
            return await _show_accounts_or_close(call)

        await call.answer(constant_text.ACCOUNT_CHECK_ERROR_TOAST.format(error=exc.__class__.__name__))

    account = await get_account_uuid(account.uuid, call.from_user.id)
    if not account:
        return await _show_accounts_or_close(call)

    await _render_account_editor(call, account)

