"""Self-service never exposes another owner's API credentials or grants admin rights."""
from uuid import UUID

from aiogram import F, Router, html
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from callbacks.account_ownership import HOME_CALLBACK, OwnAccount
from data.texts import account_ownership as text
from db.main import get_app_tg_user_id, is_admin
from db.models import Account
from db.repositories.account_locks import AccountAlreadyConnected
from db.repositories.personal_repo import PersonalKeyRepository
from db.session import get_session_factory
from filters.all_filters import IsAdmin, IsPrivate
from keyboards.inline.account_ownership import (accounts_keyboard, delete_keyboard,
    detail_keyboard, profiles_keyboard, self_menu_keyboard, status_keyboard)
from keyboards.inline.personal_secret import setup_keyboard
from services.account_operations import repository
from utils.others import close_state_pyrogram_client
from utils.panel import edit_panel
from keyboards.inline.navigation import navigation_keyboard

router = Router(name=__name__)
PAGE_SIZE = 5


async def _self_account(actor_id, account_id=None):
    rows = await repository.self_accounts(actor_id)
    if account_id is None:
        if not rows:
            raise PermissionError("Account is not accessible")
        if len(rows) > 1:
            raise AccountAlreadyConnected(text.LEGACY_CONFLICT)
        return rows[0]
    return next((row for row in rows if row.uuid == UUID(str(account_id))), None)


async def _show_home(message, actor_id, state, *, edit=False):
    await close_state_pyrogram_client(state)
    await state.clear()
    accounts = await repository.self_accounts(actor_id)
    content = text.TITLE if accounts else text.EMPTY
    markup = accounts_keyboard(accounts) if accounts else self_menu_keyboard()
    if edit:
        await edit_panel(message, content, markup)
    else:
        await message.answer(content, reply_markup=markup)


@router.message(IsPrivate(), IsAdmin(), F.text == text.MENU, StateFilter("*"))
async def my_account(message: Message, state: FSMContext):
    await _show_home(message, message.from_user.id, state)


async def request_delete_warning(call, account_id):
    async with get_session_factory()() as session:
        account = await session.get(Account, UUID(str(account_id)))
    if account is None or not (account.user_id == call.from_user.id or
                              (account.admin_id == call.from_user.id and await is_admin(call.from_user.id))):
        raise PermissionError("Account is not accessible")
    operation = await repository.request_delete(account_id, call.from_user.id)
    parent = (f"acc:e:{account.uuid}" if (call.data or "").startswith("acc:del:") else
              OwnAccount(action="detail", token=account.uuid.hex).pack())
    await edit_panel(call.message, text.DELETE_WARNING.format(account_id=operation.account_user_id),
                     delete_keyboard(operation, back_callback=parent))


@router.callback_query(IsPrivate(), IsAdmin(), OwnAccount.filter(), StateFilter("*"))
async def own_account_callback(call: CallbackQuery, callback_data: OwnAccount, state: FSMContext,
                               personal_secret_dialog=None):
    actor_id, action, token = call.from_user.id, callback_data.action, callback_data.token
    try:
        if action == "home":
            await _show_home(call.message, actor_id, state, edit=True)
        elif action == "detail":
            account = await _self_account(actor_id, token)
            if account is None:
                raise PermissionError("Account is not accessible")
            async with get_session_factory()() as session:
                from db.account_operation_models import AccountOperation
                operation = await session.scalar(select(AccountOperation).where(AccountOperation.active_account_id == actor_id))
            await edit_panel(call.message, text.DETAIL.format(user_id=account.user_id, owner_id=account.admin_id,
                access=text.MANAGER if account.admin_id == actor_id else text.LIMITED),
                reply_markup=detail_keyboard(account, operation))
        elif action == "profiles":
            account = await _self_account(actor_id)
            if account.admin_id == actor_id:
                raise PermissionError("Account is already owned by requester")
            page = max(0, callback_data.page)
            profiles, count = await get_app_tg_user_id(actor_id, page * PAGE_SIZE)
            total = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
            if page >= total:
                page = total - 1
                profiles, count = await get_app_tg_user_id(actor_id, page * PAGE_SIZE)
            await edit_panel(call.message, text.PROFILES if count else text.NO_PROFILES,
                             profiles_keyboard(profiles, page, total, account_uuid=account.uuid))
        elif action == "pick":
            account = await _self_account(actor_id)
            if await PersonalKeyRepository(get_session_factory).get(actor_id) is None:
                await edit_panel(call.message, text.SECRET_REQUIRED, setup_keyboard())
            else:
                operation = await repository.request_transfer(account.uuid, actor_id, token)
                await edit_panel(call.message, text.REQUEST_CREATED, status_keyboard(operation, actor_id))
        elif action == "delete":
            await request_delete_warning(call, token)
        elif action == "erase":
            operation = await repository.get(token, actor_id)
            if operation is None or operation.kind != "delete":
                raise PermissionError("Delete request is not accessible")
            async with get_session_factory()() as session:
                account = await session.get(Account, operation.account_uuid)
            if account is not None and account.user_id != actor_id and not await is_admin(actor_id):
                raise PermissionError("Account management access was revoked")
            await repository.confirm_delete(operation.uuid, actor_id)
            parent = "panel:accounts" if operation.owner_id == actor_id else HOME_CALLBACK
            await edit_panel(call.message, text.DELETE_STARTED, navigation_keyboard(parent))
        elif action in {"approve", "reject", "status"}:
            operation = await repository.get(token, actor_id)
            if operation is None:
                raise PermissionError("Request is not accessible")
            if action == "approve":
                if operation.kind != "transfer" or operation.owner_id != actor_id or operation.status not in {"pending", "needs_secret"}:
                    raise PermissionError("Transfer cannot be approved")
                if await PersonalKeyRepository(get_session_factory).get(actor_id) is None:
                    from middlewares.personal_secret import prompt_setup
                    await prompt_setup(call.bot, actor_id, message=call.message)
                else:
                    if personal_secret_dialog is None:
                        raise RuntimeError("Personal-secret middleware is required")
                    await personal_secret_dialog.begin(call.message, state, transfer_request=operation.uuid)
            else:
                if action == "reject":
                    operation = await repository.reject(operation.uuid, actor_id)
                await edit_panel(call.message, text.STATUS.format(account_id=operation.account_user_id,
                    status=html.quote(text.STATUSES.get(operation.status, operation.status))),
                    reply_markup=status_keyboard(operation, actor_id))
        else:
            raise ValueError("Unknown action")
    except AccountAlreadyConnected:
        await edit_panel(call.message, text.LEGACY_CONFLICT, navigation_keyboard(HOME_CALLBACK))
    except (PermissionError, ValueError, TypeError):
        await call.answer(text.UNAVAILABLE, show_alert=True)
        return
    await call.answer()
