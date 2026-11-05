from uuid import uuid4

from aiogram import F, Router, html
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from data.texts import admins as text
from db.main import (get_admin_grants, get_admin_ids, get_configured_admin_ids,
                     get_user, grant_admin, is_admin, revoke_admin)
from db.repositories.admins_repo import telegram_user_id
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.states import AdminStates
from keyboards.inline.admins_inline import (admin_cancel_keyboard, admin_confirmation_keyboard,
                                            admin_detail_keyboard, admin_list_keyboard)
from keyboards.main.start_keyboard import static_admin_keyboard

from utils.others import close_state_pyrogram_client
from utils.panel import edit_panel, edit_input_panel, remember_panel
from keyboards.inline.navigation import navigation_keyboard

router = Router(name=__name__)

PAGE_SIZE = 8


def _can_manage(actor_id):
    return actor_id in get_configured_admin_ids()


async def _require_management(event, state):
    if _can_manage(event.from_user.id):
        return True
    if isinstance(event, CallbackQuery):
        await _clear_flow(state)
        await event.answer(text.MANAGEMENT_FORBIDDEN, show_alert=True)
    else:
        await edit_input_panel(event, state, text.MANAGEMENT_FORBIDDEN, navigation_keyboard("adm:list:0"))
        await _clear_flow(state)
    return False


async def _clear_flow(state):
    await close_state_pyrogram_client(state)
    await state.clear()


async def _edit(message, content, *, reply_markup=None):
    return await edit_panel(message, content, reply_markup)


def _target_and_page(data):
    parts = data.split(":")
    if len(parts) != 4:
        raise ValueError("Invalid administrator callback")
    user_id = telegram_user_id(int(parts[2]))
    page = int(parts[3])
    if page < 0:
        raise ValueError("Invalid administrator page")
    return user_id, page


async def _show_list(message, *, actor_id, page=0, edit=False):
    configured = get_configured_admin_ids()
    ids = sorted(await get_admin_ids(), key=lambda user_id: (user_id not in configured, user_id))
    pages = max(1, (len(ids) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    entries = []
    for user_id in ids[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        user = await get_user(user_id)
        name = (user.full_name or user.username or "") if user is not None else ""
        label = f"{'🔒 ' if user_id in configured else ''}{user_id}"
        if name:
            label += f" · {name[:30]}"
        entries.append((user_id, label))
    content = text.MENU_TEXT.format(count=len(ids), page=page + 1, pages=pages)
    keyboard = admin_list_keyboard(entries, page, pages, can_manage=_can_manage(actor_id))
    if edit:
        await _edit(message, content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


@router.message(IsPrivate(), IsAdmin(), F.text == text.MENU_BUTTON, StateFilter("*"))
async def open_admins_handler(message: Message, state: FSMContext):
    await _clear_flow(state)
    await _show_list(message, actor_id=message.from_user.id)


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("adm:list:"), StateFilter("*"))
async def list_admins_handler(call: CallbackQuery, state: FSMContext):
    try:
        page = int(call.data.split(":")[2])
        if page < 0:
            raise ValueError
    except (ValueError, IndexError):
        return await call.answer(text.EXPIRED)
    await _clear_flow(state)
    await _show_list(call.message, actor_id=call.from_user.id, page=page, edit=True)
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("adm:view:"), StateFilter("*"))
async def view_admin_handler(call: CallbackQuery, state: FSMContext):
    try:
        user_id, page = _target_and_page(call.data)
    except ValueError:
        return await call.answer(text.EXPIRED)
    await _clear_flow(state)
    if not await is_admin(user_id):
        return await call.answer(text.NO_ACCESS)
    configured = user_id in get_configured_admin_ids()
    user = await get_user(user_id)
    name = (user.full_name or user.username or text.NO_NAME) if user else text.NO_CONTACT
    grants = {grant.user_id: grant for grant in await get_admin_grants()}
    grant = grants.get(user_id)
    origin = text.CONFIGURED_ORIGIN if configured else (
        text.ASSIGNED_ORIGIN.format(user_id=grant.granted_by) if grant and grant.granted_by else text.LEGACY_ORIGIN)
    await _edit(call.message,
        text.DETAIL.format(name=html.quote(name), user_id=user_id, origin=origin),
        reply_markup=admin_detail_keyboard(user_id, page,
            can_revoke=_can_manage(call.from_user.id) and not configured and user_id != call.from_user.id))
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "adm:add", StateFilter("*"))
async def add_admin_handler(call: CallbackQuery, state: FSMContext):
    if not await _require_management(call, state):
        return
    await _clear_flow(state)
    await state.set_state(AdminStates.admin_add_id)
    panel = await _edit(call.message, text.INPUT_ID, reply_markup=admin_cancel_keyboard())
    await remember_panel(state, panel or call.message)
    await call.answer()


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.admin_add_id), F.text == text.CANCEL_BUTTON)
async def cancel_admin_input_handler(message: Message, state: FSMContext):
    await state.clear()
    await _show_list(message, actor_id=message.from_user.id)


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.admin_add_id))
async def receive_admin_id_handler(message: Message, state: FSMContext):
    if not await _require_management(message, state):
        return
    value = (message.text or "").strip()
    try:
        if not value.isascii() or not value.isdecimal():
            raise ValueError
        user_id = telegram_user_id(int(value))
    except ValueError:
        return await edit_input_panel(message, state, text.INVALID_ID, admin_cancel_keyboard())
    if await is_admin(user_id):
        return await edit_input_panel(message, state, text.ALREADY_ALLOWED, admin_cancel_keyboard())
    nonce = uuid4().hex
    await state.update_data(admin_target=user_id, admin_nonce=nonce)
    await state.set_state(AdminStates.admin_confirm_add)
    await edit_input_panel(message, state, text.GRANT_CONFIRM.format(user_id=user_id),
                           admin_confirmation_keyboard("grant", nonce))


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("adm:grant:"), StateFilter(AdminStates.admin_confirm_add))
async def confirm_admin_grant_handler(call: CallbackQuery, state: FSMContext):
    if not await _require_management(call, state):
        return
    data = await state.get_data()
    if not data.get("admin_nonce") or call.data != f"adm:grant:{data['admin_nonce']}":
        return await call.answer(text.EXPIRED)
    await state.clear()
    try:
        created = await grant_admin(call.from_user.id, data["admin_target"])
    except PermissionError:
        return await call.answer(text.ACCESS_REVOKED)
    await _show_list(call.message, actor_id=call.from_user.id, edit=True)
    await call.answer(text.GRANTED if created else text.ALREADY_GRANTED)


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("adm:revoke:"), StateFilter("*"))
async def request_admin_revoke_handler(call: CallbackQuery, state: FSMContext):
    if not await _require_management(call, state):
        return
    try:
        user_id, page = _target_and_page(call.data)
    except ValueError:
        return await call.answer(text.EXPIRED)
    if user_id in get_configured_admin_ids():
        return await call.answer(text.PROTECTED, show_alert=True)
    if user_id == call.from_user.id:
        return await call.answer(text.SELF_REVOKE, show_alert=True)
    if not await is_admin(user_id):
        return await call.answer(text.NO_ACCESS)
    await _clear_flow(state)
    nonce = uuid4().hex
    await state.update_data(admin_target=user_id, admin_nonce=nonce, admin_page=page)
    await state.set_state(AdminStates.admin_confirm_revoke)
    await _edit(call.message, text.REVOKE_CONFIRM.format(user_id=user_id),
        reply_markup=admin_confirmation_keyboard("remove", nonce, page=page))
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("adm:remove:"), StateFilter(AdminStates.admin_confirm_revoke))
async def confirm_admin_revoke_handler(call: CallbackQuery, state: FSMContext):
    if not await _require_management(call, state):
        return
    data = await state.get_data()
    if not data.get("admin_nonce") or call.data != f"adm:remove:{data['admin_nonce']}":
        return await call.answer(text.EXPIRED)
    await state.clear()
    try:
        removed = await revoke_admin(call.from_user.id, data["admin_target"])
    except PermissionError:
        return await call.answer(text.ACCESS_REVOKED)
    except ValueError:
        return await call.answer(text.EXPIRED)
    await _show_list(call.message, actor_id=call.from_user.id, page=data.get("admin_page", 0), edit=True)
    await call.answer(text.REVOKED if removed else text.NO_ACCESS)


@router.callback_query(IsPrivate(), IsAdmin(), F.data == "adm:close", StateFilter("*"))
async def close_admins_handler(call: CallbackQuery, state: FSMContext):
    await _clear_flow(state)
    await _edit(call.message, text.MAIN_MENU, reply_markup=static_admin_keyboard())
    await call.answer()


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("adm:"), StateFilter("*"))
async def expired_admin_button_handler(call: CallbackQuery):
    await call.answer(text.EXPIRED)
