"""Prefer private-chat topics; retain ordinary delivery when unavailable."""
import time
from collections import OrderedDict

from aiogram.exceptions import TelegramBadRequest

from core.account_runtime import account_guard
from core.logging import bot_logger
from db.repositories.topics_repo import TopicsRepository
from db.session import get_session_factory


class TopicDelivery:
    def __init__(self, bot, repository=None):
        self.bot = bot
        self.repository = repository or TopicsRepository(get_session_factory)
        self._enabled = None
        self._checked_until = 0
        self._creation_backoff = OrderedDict()

    async def enabled(self):
        if time.monotonic() < self._checked_until:
            return self._enabled
        async with account_guard(("topic-capability", self.bot.id)):
            if time.monotonic() >= self._checked_until:
                try:
                    me = await self.bot.get_me()  # Bot.me() caches this flag indefinitely.
                    self._enabled = getattr(me, "has_topics_enabled", None) is True
                    self._checked_until = time.monotonic() + 60
                except Exception as error:
                    self._enabled = None
                    self._checked_until = time.monotonic() + 15
                    bot_logger.warning("Topic capability check deferred: %s", type(error).__name__)
        return self._enabled

    async def _thread(self, owner_id, key, title):
        async with account_guard(("notification-topic", self.bot.id, owner_id, key)):
            thread_id = await self.repository.get(self.bot.id, owner_id, key)
            if thread_id is None:
                topic = await self.bot.create_forum_topic(chat_id=owner_id, name=title)
                thread_id = topic.message_thread_id
                await self.repository.save(self.bot.id, owner_id, key, thread_id)
            return thread_id

    async def send(self, method, owner_id, key, title, **kwargs):
        thread_id = None
        identity = (owner_id, key)
        if await self.enabled() and self._creation_backoff.get(identity, 0) <= time.monotonic():
            try:
                thread_id = await self._thread(owner_id, key, title)
            except Exception as error:
                self._creation_backoff[identity] = time.monotonic() + max(60, getattr(error, "retry_after", 0))
                self._creation_backoff.move_to_end(identity)
                if len(self._creation_backoff) > 1024:
                    self._creation_backoff.popitem(last=False)
                bot_logger.warning("Topic creation unavailable; using private chat: %s", type(error).__name__)
        if thread_id is None:
            return await method(chat_id=owner_id, **kwargs)
        try:
            return await method(chat_id=owner_id, message_thread_id=thread_id, **kwargs)
        except TelegramBadRequest as error:
            reason = error.message.casefold()
            if "topic_closed" in reason or "topic is closed" in reason:
                await self.bot.reopen_forum_topic(chat_id=owner_id, message_thread_id=thread_id)
                return await method(chat_id=owner_id, message_thread_id=thread_id, **kwargs)
            if any(marker in reason for marker in ("thread not found", "thread is not found",
                    "message_thread_invalid", "topic_id_invalid", "topic_deleted")):
                await self.repository.discard(self.bot.id, owner_id, key, thread_id)
                thread_id = await self._thread(owner_id, key, title)
                return await method(chat_id=owner_id, message_thread_id=thread_id, **kwargs)
            if "not a forum" in reason or "topics are not enabled" in reason:
                self._enabled, self._checked_until = False, time.monotonic() + 60
                return await method(chat_id=owner_id, **kwargs)
            raise


def delivery(bot):
    service = getattr(bot, "_watchtower_topic_delivery", None)
    if not isinstance(service, TopicDelivery):
        service = TopicDelivery(bot)
        bot._watchtower_topic_delivery = service
    return service


async def send_account_log(bot, owner_id, account_user_id, text, **kwargs):
    return await delivery(bot).send(bot.send_message, owner_id, f"account:{account_user_id}",
                                    str(account_user_id), text=text, **kwargs)


async def send_spoiler(bot, method, owner_id, **kwargs):
    return await delivery(bot).send(method, owner_id, "spoiler", "spoiler", **kwargs)
