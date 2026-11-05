from aiogram import F, Router, html
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import data.text as constant_text
from db.main import create_app_tg, get_app_tg_to_params_all
from filters.all_filters import CanCreateProfile, IsPrivate
from services.account_access import can_create_profile
from handlers.admin.states import AdminStates
from keyboards.inline.agree_inline import agree_inline
from keyboards.inline.back_inline import back_inline

from utils.others import not_warning_delete_message
from utils.panel import edit_panel, edit_input_panel, remember_panel

router = Router(name=__name__)


@router.callback_query(IsPrivate(), CanCreateProfile(), F.data == "apps_admin_menu_add", StateFilter("*"))
async def start_add_app_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    panel = await edit_panel(call.message,
        text=constant_text.APPS_ADD_APP_ID_TEXT,
        reply_markup=back_inline("panel:apps"),
    )
    await remember_panel(state, panel or call.message)
    await state.set_state(AdminStates.apps_add_app_id)
    await call.answer()


@router.message(IsPrivate(), CanCreateProfile(), StateFilter(AdminStates.apps_add_app_id))
async def receive_app_id_handler(message: Message, state: FSMContext):
    await not_warning_delete_message(message=message)

    try:
        app_id = int(message.text)
        if app_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return await edit_input_panel(message, state, constant_text.ERROR_FORMAT_TEXT, back_inline("panel:apps"))

    await edit_input_panel(message, state,
        text=constant_text.APPS_ADD_API_HASH_TEXT,
        reply_markup=back_inline("panel:apps"),
    )
    await state.update_data(app_id=app_id)
    await state.set_state(AdminStates.apps_add_api_hash)


@router.message(IsPrivate(), CanCreateProfile(), StateFilter(AdminStates.apps_add_api_hash))
async def receive_api_hash_handler(message: Message, state: FSMContext):
    await not_warning_delete_message(message=message)

    api_hash = (message.text or "").strip()
    if not api_hash:
        return await edit_input_panel(message, state, constant_text.ERROR_FORMAT_TEXT, back_inline("panel:apps"))

    await edit_input_panel(message, state,
        text=constant_text.APPS_ADD_NAME_TAG_TEXT,
        reply_markup=back_inline("panel:apps"),
    )
    await state.update_data(api_hash=api_hash)
    await state.set_state(AdminStates.apps_add_tag_name)


@router.message(IsPrivate(), CanCreateProfile(), StateFilter(AdminStates.apps_add_tag_name))
async def receive_tag_name_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    await not_warning_delete_message(message=message)

    tag_name = (message.text or "").strip()
    if not tag_name:
        return await edit_input_panel(message, state, constant_text.ERROR_FORMAT_TEXT, back_inline("panel:apps"))

    await edit_input_panel(message, state,
        text=constant_text.APPS_ADD_AGREE_TEXT.format(
            _app_id=data["app_id"],
            _api_hash=html.quote(data["api_hash"]),
            _tag_name=html.quote(tag_name),
        ),
        reply_markup=agree_inline(),
    )

    await state.update_data(tag_name=tag_name)
    await state.set_state(AdminStates.apps_add_agree)


@router.callback_query(IsPrivate(), CanCreateProfile(), F.data == "agree", StateFilter(AdminStates.apps_add_agree))
async def confirm_add_app_handler(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    user_id = call.from_user.id
    app_id = data["app_id"]
    api_hash = data["api_hash"]
    tag_name = data["tag_name"]

    if await get_app_tg_to_params_all(user_id=user_id, app_id=app_id, api_hash=api_hash):
        await edit_panel(call.message, constant_text.ERROR_ALREADY_APP_TEXT, back_inline("panel:apps"))
        return await call.answer()

    if not await can_create_profile(user_id):
        return await call.answer("Доступ администратора отозван.")
    await create_app_tg(
        user_id=user_id,
        app_id=app_id,
        api_hash=api_hash,
        tag_name=tag_name,
    )
    await edit_panel(call.message, constant_text.SUCCESS_ADD_APP_TEXT, back_inline("panel:apps"))
    await call.answer()
