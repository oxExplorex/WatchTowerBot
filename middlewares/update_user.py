from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message

from db.main import update_user


class UpdateUserMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
            message: Message,
            data: dict[str, Any]
    ) -> Any:

        if message.from_user is None:
            return await handler(message, data)
        _user_id = message.from_user.id
        _username = message.from_user.username
        _full_name = message.from_user.full_name

        await update_user(user_id=_user_id, username=_username, full_name=_full_name)

        return await handler(message, data)


