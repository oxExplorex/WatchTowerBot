from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import data.text as constant_text
from db.main import del_app_tg_uuid
from filters.all_filters import IsAdmin, IsPrivate
from loader import router


@router.callback_query(IsPrivate(), IsAdmin(), F.data.startswith("apps_admin_menu_delete:"), StateFilter("*"))
async def delete_app_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        app_uuid = call.data.split(":")[1]
    except (TypeError, IndexError):
        return await call.answer(constant_text.ERROR_FORMAT_TEXT)

    user_id = call.from_user.id

    if await del_app_tg_uuid(app_uuid, user_id):
        return await call.message.answer(constant_text.SUCCESS_DEL_APP_TEXT)

    return await call.answer(constant_text.ERROR_DEL_APP_TEXT)
