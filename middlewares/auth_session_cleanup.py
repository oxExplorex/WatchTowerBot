from aiogram import BaseMiddleware

from core.auth_sessions import auth_clients


class AuthSessionCleanupMiddleware(BaseMiddleware):
    async def __call__(self, handler, update, data):
        state = data.get("state")
        if state is None or (update.message is None and update.callback_query is None):
            return await handler(update, data)
        previous = (await state.get_data()).get("app_temp")
        try:
            return await handler(update, data)
        finally:
            if previous is not None and auth_clients.contains(previous):
                current = (await state.get_data()).get("app_temp")
                if current is not previous:
                    await auth_clients.discard(previous)
