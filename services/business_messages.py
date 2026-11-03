from collections import OrderedDict
import time

from db.main import get_accounts_for_user_id, get_admin_ids
from loader import bot
from services.message_service import AccountContext

_connections: OrderedDict[str, tuple[int, float]] = OrderedDict()


async def business_contexts(connection_id: str) -> list[AccountContext]:
    cached = _connections.get(connection_id)
    if cached is not None and cached[1] > time.monotonic():
        user_id = cached[0]
    else:
        connection = await bot.get_business_connection(connection_id)
        user_id = int(connection.user.id)
        if getattr(connection, "is_enabled", True) is False:
            return []
        _connections[connection_id] = (user_id, time.monotonic() + 60)
        _connections.move_to_end(connection_id)
        if len(_connections) > 128:
            _connections.popitem(last=False)
    accounts = await get_accounts_for_user_id(user_id)
    contexts = [AccountContext.from_account(account) for account in accounts]
    contexts = [context for context in contexts if context is not None]
    # Business-only administrators need not create a Pyrogram session to archive.
    if not accounts and user_id in await get_admin_ids():
        contexts.append(AccountContext(user_id, user_id))
    return contexts


def business_event_key(message, event_update) -> str | None:
    if event_update is None:
        return None
    return f"{message.business_connection_id}:{event_update.update_id}"
