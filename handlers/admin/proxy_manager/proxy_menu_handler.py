from aiogram import F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import data.text as constant_text
from filters.all_filters import IsAdmin, IsPrivate
from handlers.admin.states import AdminStates
from loader import router


@router.message(IsPrivate(), IsAdmin(), F.text.in_(constant_text.PROXY_USER_KEYBOARD), StateFilter("*"))
async def open_proxy_menu_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(constant_text.PROXY_MENU_PROMPT_TEXT)
    await state.set_state(AdminStates.wait_proxy_manager)


@router.message(IsPrivate(), IsAdmin(), StateFilter(AdminStates.wait_proxy_manager))
async def save_proxy_handler(message: Message, state: FSMContext):
    await state.clear()

    text = (message.text or "").strip()
    if text.count(":") == 3:
        with open("data/proxy.txt", "w", encoding="utf-8") as file:
            file.write(text)
        return await message.answer(constant_text.PROXY_SET_TEXT)

    if text == "0":
        with open("data/proxy.txt", "w", encoding="utf-8") as file:
            file.write("0")
        return await message.answer(constant_text.PROXY_DISABLED_TEXT)

    return await message.answer(constant_text.PROXY_INVALID_FORMAT_TEXT)
