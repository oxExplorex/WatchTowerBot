"""Private-chat onboarding before ordinary handlers can inspect secret messages."""
import time

from aiogram import BaseMiddleware
from aiogram.types import InaccessibleMessage

from callbacks.personal_secret import CANCEL_CALLBACK, SETUP_CALLBACK, VERIFY_CALLBACK
from data.texts import personal_secret as texts
from data.texts import account_ownership as ownership_text
from data.texts.personal_secret import CONFIRM_PROMPT, INPUT_PROMPT, PROMPT
from db.repositories.personal_repo import PersonalKeyRepository
from db.session import get_session_factory
from handlers.admin.personal_secret import PersonalSecretDialog
from keyboards.inline.personal_secret import setup_keyboard
from keyboards.inline.navigation import navigation_keyboard
from utils.panel import edit_panel
from keyboards.main.start_keyboard import static_admin_keyboard
from data.texts.common import START_MESSAGE_TEXT
from states.personal_secret import (
    SECRET_CONFIRM, SECRET_INPUT, SECRET_STATES, SECRET_VERIFY,
)


async def prompt_setup(bot, owner_id, *, message=None):
    if message is not None:
        await edit_panel(message, PROMPT, setup_keyboard())
    else:
        await bot.send_message(owner_id, PROMPT, parse_mode="HTML", reply_markup=setup_keyboard())


async def notify_missing_secrets(bot):
    from core.logging import bot_logger
    from db.main import get_admin_ids

    repository = PersonalKeyRepository(get_session_factory)
    for owner_id in await get_admin_ids():
        if await repository.get(owner_id) is None:
            try:
                await prompt_setup(bot, owner_id)
            except Exception as exc:
                bot_logger.warning("Secret setup notification unavailable: owner=%s error=%s", owner_id, type(exc).__name__)


class PersonalSecretMiddleware(BaseMiddleware):
    """Admission and early interception; dialog owns its FSM and crypto work."""

    def __init__(self, repository=None, authorize=None):
        self.dialog = PersonalSecretDialog(repository, authorize)
        self.repository = self.dialog.repository

    async def __call__(self, handler, update, data):
        if update.business_message or update.edited_business_message or update.deleted_business_messages:
            return await handler(update, data)
        call = update.callback_query
        message = update.message or update.edited_message or (call.message if call else None)
        user = data.get("event_from_user")
        state = data.get("state")
        if message is None or user is None or state is None:
            return None
        if message.chat.type != "private" or message.chat.id != user.id:
            return None
        owner_id = user.id
        data["personal_secret_dialog"] = self.dialog
        key = await self.repository.get(owner_id)
        if call and isinstance(call.message, InaccessibleMessage):
            await state.clear()
            if key is None:
                await prompt_setup(data["bot"], owner_id)
            else:
                await data["bot"].send_message(owner_id, START_MESSAGE_TEXT, parse_mode="HTML",
                                              reply_markup=static_admin_keyboard())
            await call.answer(texts.MENU_UNAVAILABLE)
            return None
        current = await state.get_state()
        reply = getattr(message, "reply_to_message", None)
        if update.message and current not in SECRET_STATES and reply is not None:
            author = getattr(reply, "from_user", None)
            if (getattr(author, "id", None) == getattr(data["bot"], "id", None)
                    and getattr(reply, "text", None) in {INPUT_PROMPT, CONFIRM_PROMPT, *texts.LEGACY_INPUT_PROMPTS}):
                await self.dialog.delete_input(message)
                await message.answer(texts.INPUT_INTERRUPTED)
                return None
        if update.edited_message is not None and current in SECRET_STATES:
            await self.dialog.delete_input(message)
            return None
        callback = (call.data or "") if call else ""
        content = (message.text or "").strip() if update.message else ""
        command = content.split(maxsplit=1)[0].split("@", 1)[0] if content.startswith("/") else ""
        if callback == CANCEL_CALLBACK:
            if current not in SECRET_STATES:
                await call.answer(texts.CANCEL_UNAVAILABLE)
                return None
            await state.clear()
            await call.answer(texts.INPUT_CANCELLED)
            await edit_panel(call.message, texts.INPUT_CANCELLED, navigation_keyboard("panel:settings"))
            return None
        # Commands must never become wizard input or reach ordinary handlers.
        if command and command != "/start":
            if current in SECRET_STATES:
                await self.dialog.delete_input(message)
            return None
        if command == "/start" and current in SECRET_STATES:
            await state.clear()
            current = None
        if current in SECRET_STATES and callback in {"panel:home", "panel:settings", "set:back"}:
            await state.clear()
            current = None
        if update.message is not None and current in SECRET_STATES:
            await self.dialog.handle_input(message, state, owner_id, key, current)
            return None
        if callback in {SETUP_CALLBACK, VERIFY_CALLBACK}:
            if call:
                await call.answer()
            await self.dialog.begin(message, state, verify=key is not None)
            return None
        if callback.startswith("own:") or (message.text or "") == ownership_text.MENU:
            return await handler(update, data)
        if key is None:
            if call:
                await call.answer(texts.SETUP_REQUIRED)
            elif update.message and not (message.text or "").startswith("/"):
                await self.dialog.delete_input(message)
            await prompt_setup(data["bot"], owner_id, message=call.message if call else None)
            return None
        # A short-lived confirmation contains no decryption key and grants no
        # access to another owner's objects. Deletion does not require this step.
        addition = callback == "apps_admin_menu_add" or callback.startswith("account_admin_menu_add:")
        previous = await state.get_data()
        until = previous.get("personal_verified_until", 0)
        wizard_state = bool(current and (current.startswith("AdminStates:apps_add_") or current.startswith("AdminStates:account_add_")))
        adding = wizard_state and (callback == "agree" or (update.message is not None and not (message.text or "").startswith("/")))
        if (addition or adding) and until < int(time.time()):
            if call:
                await call.answer(texts.VERIFY_REQUIRED)
            await self.dialog.begin(message, state, verify=True)
            return None
        try:
            return await handler(update, data)
        finally:
            # Entry handlers clear FSM data before starting the add wizard.
            next_state = await state.get_state()
            if addition and next_state:
                await state.update_data(personal_verified_until=until)
