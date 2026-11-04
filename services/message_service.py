from dataclasses import dataclass, replace
import json

from aiogram import html

from core.logging import bot_logger
from db.main import messages_repository, update_user
from core.personal_crypto import live_fingerprint
from core.account_runtime import account_guard
from utils.message_payload import channel_namespace, message_payload, timestamp
from utils.chat_notifications import get_user_log_text
from utils.telegram_helpers import is_bot_or_channel


@dataclass(frozen=True)
class AccountContext:
    owner_id: int
    account_user_id: int
    alert_new_chat: bool = True
    alert_bot: bool = True
    require_account: bool = False

    @classmethod
    def from_account(cls, account):
        if not account.admin_id or not account.user_id or not account.is_active:
            return None
        return cls(int(account.admin_id), int(account.user_id), bool(account.alert_new_chat), bool(account.alert_bot), True)


async def _notify_new_chat(bot, context: AccountContext, chat) -> None:
    chat_id = chat.id
    name = getattr(chat, "full_name", None) or getattr(chat, "title", None) or "Unknown"
    username = getattr(chat, "username", None)
    try:
        await update_user(chat_id, username, name)
    except Exception as exc:
        # The archive is already committed; contact enrichment must not undo it.
        bot_logger.warning("Could not refresh observed contact: %s", type(exc).__name__)
    if not context.alert_new_chat:
        return
    if not context.alert_bot and (is_bot_or_channel(chat) or getattr(chat, "is_bot", False)):
        return
    try:
        await bot.send_message(context.owner_id, get_user_log_text(1, chat_id, username or "-", html.quote(name)))
    except Exception as exc:
        bot_logger.warning("Could not send new chat notification: %s", type(exc).__name__)


async def save_message(bot, context: AccountContext, message, *, source: str, kind: str,
                       event_key: str | None = None):
    async with account_guard(context.account_user_id):
        return await _save_message(bot, context, message, source=source, kind=kind, event_key=event_key)


async def _save_message(bot, context, message, *, source, kind, event_key):
    message_id = getattr(message, "message_id", None) or getattr(message, "id", None)
    if not message_id or getattr(message, "chat", None) is None:
        return None
    # Never archive passwords/login codes sent to the control bot itself.
    if message.chat.id == bot.id:
        return None
    payload = message_payload(message)
    sent_at = timestamp(getattr(message, "date", None))
    version_at = timestamp(getattr(message, "edit_date", None)) if kind == "edit" else sent_at
    if event_key is None:
        event_key = live_fingerprint(json.dumps([context.owner_id, kind, message_id, version_at, payload], sort_keys=True, ensure_ascii=False))
    result = await messages_repository.record(
        owner_id=context.owner_id, account_user_id=context.account_user_id,
        chat_id=message.chat.id, message_id=message_id, source=source,
        event_key=f"{event_key}:{message_id}", kind=kind, payload=payload,
        sent_at=sent_at, version_at=version_at,
        sender_id=getattr(getattr(message, "from_user", None), "id", None),
        channel_namespace=channel_namespace(message.chat), require_account=context.require_account)
    if result is not None and result.new_chat:
        await _notify_new_chat(bot, replace(context, owner_id=result.owner_id or context.owner_id), message.chat)
    return result


async def delete_message(bot, context: AccountContext, message_id: int, *, source: str,
                         chat=None, event_key: str | None = None):
    async with account_guard(context.account_user_id):
        return await _delete_message(bot, context, message_id, source=source, chat=chat, event_key=event_key)


async def _delete_message(bot, context, message_id, *, source, chat, event_key):
    if chat is not None and chat.id == bot.id:
        return None
    if chat is None:
        await messages_repository.record_unlocated_deletion(
            owner_id=context.owner_id, account_user_id=context.account_user_id, message_id=message_id,
            require_account=context.require_account)
        return None
    result = await messages_repository.record(
        owner_id=context.owner_id, account_user_id=context.account_user_id,
        chat_id=chat.id, message_id=message_id, source=source,
        event_key=f"{event_key or 'delete'}:{message_id}", kind="delete",
        channel_namespace=channel_namespace(chat), require_account=context.require_account)
    if result is not None and result.new_chat:
        await _notify_new_chat(bot, replace(context, owner_id=result.owner_id or context.owner_id), chat)
    return result
