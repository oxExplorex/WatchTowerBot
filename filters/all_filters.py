from typing import Union

from aiogram.enums import ChatType
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from db.main import is_admin


class ChatTypeFilter_example(BaseFilter):
    def __init__(self, chat_type: Union[str, list]):
        self.chat_type = chat_type

    async def __call__(self, message: Message) -> bool:
        if isinstance(self.chat_type, str):
            return message.chat.type == self.chat_type
        return message.chat.type in self.chat_type


class CheckBusinessConnectionId(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return True


class IsPrivate(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        content = message.message if isinstance(message, CallbackQuery) else message
        if not isinstance(content, Message):
            return False
        # Depending on union parsing, date=0 may also be a regular Message.
        if isinstance(message, CallbackQuery) and content.date.timestamp() == 0:
            return False
        return getattr(getattr(content, "chat", None), "type", None) == ChatType.PRIVATE


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user = getattr(message, "from_user", None)
        return user is not None and await is_admin(user.id)
