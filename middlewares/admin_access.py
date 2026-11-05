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
