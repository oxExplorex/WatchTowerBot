import time
from typing import Union

from aiogram.enums import ChatType
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from data.config import admin_id_list
from db.main import get_admins


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
        message_type = message.message.chat.type if isinstance(message, CallbackQuery) else message.chat.type
        return ChatType.PRIVATE == message_type


_admin_cache = {
    "value": set(),
    "expires_at": 0.0,
}


async def _get_admin_ids_cached() -> set[int]:
    now = time.time()
    if now < _admin_cache["expires_at"]:
        return _admin_cache["value"]

    db_admins = {x.user_id for x in await get_admins()}
    ids = set(admin_id_list) | db_admins
    _admin_cache["value"] = ids
    _admin_cache["expires_at"] = now + 30
    return ids


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user_id = message.from_user.id
        return user_id in await _get_admin_ids_cached()
