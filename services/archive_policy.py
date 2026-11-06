"""Reject non-personal conversations before any message content is written."""
from db.repositories.chat_policy_repo import ChatPolicyRepository
from db.session import get_session_factory
from utils.archive_policy import IGNORED_CHAT_IDS, archive_allowed, chat_kind


async def assess_chat(account_user_id, chat, *, sender=None):
    if chat.id in IGNORED_CHAT_IDS:
        return None
    kind = chat_kind(chat)
    if getattr(sender, "id", None) == chat.id and getattr(sender, "is_bot", False):
        kind = "bot"
    if not archive_allowed(chat.id, kind):
        await ChatPolicyRepository(get_session_factory).remember(account_user_id, chat.id, kind)
        return None
    return kind
