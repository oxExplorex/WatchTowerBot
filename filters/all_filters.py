from aiogram.enums import ChatType
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from db.main import is_admin


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


class CanCreateProfile(BaseFilter):
    async def __call__(self, event):
        from services.account_access import can_create_profile

        return await can_create_profile(event.from_user.id)


class IsAccountManager(BaseFilter):
    async def __call__(self, event):
        from db.main import get_account_uuid

        account = await get_account_uuid((event.data or "").split(":")[-1], event.from_user.id)
        return account is not None and await is_admin(event.from_user.id)
