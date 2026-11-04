from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from data.texts import account_ownership as text
from filters.all_filters import IsAccountManager, IsPrivate
from handlers.user.account_ownership import request_delete_warning

router = Router(name=__name__)


@router.callback_query(IsPrivate(), IsAccountManager(), F.data.startswith("acc:del:"), StateFilter("*"))
async def account_delete_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await request_delete_warning(call, call.data.split(":")[-1])
    except (PermissionError, ValueError, TypeError):
        await call.answer(text.UNAVAILABLE, show_alert=True)
        return
    await call.answer()

