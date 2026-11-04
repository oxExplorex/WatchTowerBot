from aiogram import BaseMiddleware

from db.main import is_admin


class AdminAccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, update, data):
        business = update.business_message or update.edited_business_message or update.deleted_business_messages
        if business is not None:
            from services.business_messages import business_contexts

            contexts = await business_contexts(business.business_connection_id)
            if not contexts:
                return None
            data["business_account_contexts"] = contexts
            return await handler(update, data)
        if update.business_connection is not None:
            return None
        user = data.get("event_from_user")
        if user is not None and await is_admin(user.id):
            return await handler(update, data)
        state = data.get("state")
        if user is not None and await self._limited_allowed(update, state, user.id):
            data["limited_account_access"] = True
            return await handler(update, data)
        if state is not None:
            from utils.others import close_state_pyrogram_client

            current = await state.get_state()
            if current and current.startswith("PersonalSecret:"):
                message = update.message or update.edited_message
                if message is not None:
                    try:
                        await message.delete()
                    except Exception:
                        # Revoked access must not forward or log the secret.
                        pass
            await close_state_pyrogram_client(state)
            await state.clear()
        return None

    @staticmethod
    async def _limited_allowed(update, state, user_id):
        from callbacks.personal_secret import SETUP_CALLBACK, VERIFY_CALLBACK
        from data.texts.account_ownership import MENU
        from services.account_access import has_limited_access

        call = update.callback_query
        message = update.message or update.edited_message or (call.message if call else None)
        if message is None or message.chat.type != "private" or message.chat.id != user_id:
            return False
        if not await has_limited_access(user_id):
            return False
        current = await state.get_state() if state else None
        if call:
            callback = call.data or ""
            return (callback.startswith("own:") or callback in {SETUP_CALLBACK, VERIFY_CALLBACK, "apps_admin_menu_add", "back_delete"}
                    or (callback == "agree" and current == "AdminStates:apps_add_agree")
                    or callback.startswith(("acc:e:", "acc:ts:", "acc:tn:", "acc:td:", "acc:tb:", "acc:tm:", "acc:chk:", "acc:del:")))
        return (bool(current and current.startswith(("PersonalSecret:", "AdminStates:apps_add_")))
                or (message.text or "").split("@", 1)[0] in {"/start", "/myaccount", "/secret", "/cancel", MENU}
                or bool(getattr(message, "reply_to_message", None)))
