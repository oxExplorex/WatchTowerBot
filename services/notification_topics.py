"""Prefer private-chat topics; retain ordinary delivery when unavailable."""
import time
import asyncio
from collections import OrderedDict

from aiogram.exceptions import TelegramBadRequest

from core.account_runtime import account_guard
from core.logging import bot_logger
from db.repositories.topics_repo import TopicsRepository
from db.session import get_session_factory
from data.texts.topics import LOGS_TITLE, MENU_TITLE


class TopicDelivery:
    def __init__(self, bot, repository=None):
        self.bot = bot
        self.repository = repository or TopicsRepository(get_session_factory)
        self._enabled = None
        self._checked_until = 0
        self._creation_backoff = OrderedDict()
        self._topic_retry_until = 0

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

    async def ensure_thread(self, owner_id, key, title):
        thread_id = None
        identity = (owner_id, key)
        if time.monotonic() < self._topic_retry_until:
            return await self.repository.get(self.bot.id, owner_id, key)
        if await self.enabled() and self._creation_backoff.get(identity, 0) <= time.monotonic():
            try:
                thread_id = await self._thread(owner_id, key, title)
            except Exception as error:
                if getattr(error, "retry_after", 0):
                    self._topic_retry_until = time.monotonic() + error.retry_after
                self._creation_backoff[identity] = time.monotonic() + max(60, getattr(error, "retry_after", 0))
                self._creation_backoff.move_to_end(identity)
                if len(self._creation_backoff) > 1024:
                    self._creation_backoff.popitem(last=False)
                bot_logger.warning("Topic creation unavailable; using private chat: %s", type(error).__name__)
        return thread_id

    async def send(self, method, owner_id, key, title, **kwargs):
        thread_id = await self.ensure_thread(owner_id, key, title)
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


async def send_log_file(bot, owner_id, **kwargs):
    return await delivery(bot).send(bot.send_document, owner_id, "logs", LOGS_TITLE, **kwargs)


async def configure_startup_reporter(bot, reporter, recipients):
    """Keep bootstrap delivery independent of the DB during the next restart."""
    from services.startup_notifications import use_runtime_transport

    use_runtime_transport(bot, reporter)
    routes = {}
    service = delivery(bot)
    for owner_id in recipients:
        try:
            thread_id = await service.ensure_thread(owner_id, "logs", LOGS_TITLE)
            if thread_id is not None:
                routes[owner_id] = thread_id
        except Exception as error:
            bot_logger.warning("Startup notification topic unavailable: %s", type(error).__name__)
    reporter.configure(bot.token, recipients, thread_ids=routes)


async def send_menu(bot, owner_id):
    from data.texts.common import START_MESSAGE_TEXT
    from keyboards.main.start_keyboard import static_admin_keyboard

    return await delivery(bot).send(bot.send_message, owner_id, "menu", MENU_TITLE,
        text=START_MESSAGE_TEXT, reply_markup=static_admin_keyboard(), parse_mode="HTML")


async def send_startup_menu(bot, owner_id):
    async with account_guard(("startup-menu", bot.id, owner_id)):
        sent = getattr(bot, "_watchtower_startup_menus", None)
        if sent is None:
            sent = bot._watchtower_startup_menus = set()
        if owner_id not in sent:
            panel = await send_menu(bot, owner_id)
            sent.add(owner_id)
            return panel


async def prepare_notification_topics(bot, *, owner_id=None, account_user_id=None):
    """Prepare destinations without holding a user's FSM lock or sending log text."""
    from db.main import get_account_all, get_admin_ids, get_configured_admin_ids

    service = delivery(bot)
    if await service.enabled() is not True:
        return
    if owner_id is not None:
        owners = {owner_id: {account_user_id} if account_user_id is not None else set()}
    else:
        owners = {user_id: set() for user_id in await get_admin_ids()}
        for account in await get_account_all(active_only=False):
            if account.admin_id is not None and account.user_id is not None:
                owners.setdefault(account.admin_id, set()).add(account.user_id)
    configured_admins = set(get_configured_admin_ids())
    for owner, accounts in owners.items():
        topics = [("menu", MENU_TITLE), ("spoiler", "spoiler")]
        if owner in configured_admins:
            topics.append(("logs", LOGS_TITLE))
            from data.texts.backups import TOPIC_TITLE
            topics.append(("backups", TOPIC_TITLE))
        topics.extend((f"account:{user_id}", str(user_id)) for user_id in sorted(accounts))
        for key, title in topics:
            try:
                async with account_guard(("topic-preparation", bot.id, owner, key)):
                    # Existing destinations require no Telegram API request.
                    if await service.repository.get(bot.id, owner, key) is not None:
                        continue
                    thread_id = await service.ensure_thread(owner, key, title)
                    if key == "menu" and thread_id is not None:
                        await send_startup_menu(bot, owner)
                    if time.monotonic() < service._topic_retry_until:
                        return
            except Exception as error:
                bot_logger.warning("Topic preparation deferred: %s", type(error).__name__)
            await asyncio.sleep(0.2)


def schedule_topic_preparation(bot, owner_id, account_user_id):
    from core.async_tools import create_logged_task

    create_logged_task(prepare_notification_topics(bot, owner_id=owner_id, account_user_id=account_user_id),
                       name=f"notification_topics:{owner_id}:{account_user_id}")
