import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import CreateForumTopic, SendMessage, SendPhoto
from aiogram.types import FSInputFile
import pytest

from db.repositories.topics_repo import TopicsRepository


def fake_bot(enabled):
    serial = 0

    async def create(**kwargs):
        nonlocal serial
        serial += 1
        return SimpleNamespace(message_thread_id=serial)

    return SimpleNamespace(id=123456, get_me=AsyncMock(return_value=SimpleNamespace(has_topics_enabled=enabled)),
        create_forum_topic=AsyncMock(side_effect=create), reopen_forum_topic=AsyncMock(),
        send_message=AsyncMock(), send_photo=AsyncMock(return_value=SimpleNamespace(
            photo=[SimpleNamespace(file_id="instruction-photo")])))


@pytest.mark.asyncio
async def test_topics_are_scoped_persistent_and_created_once_for_concurrent_events(db_main):
    from services.notification_topics import TopicDelivery

    bot = fake_bot(True)
    repository = TopicsRepository(db_main.get_session_factory)
    service = TopicDelivery(bot, repository)
    await asyncio.gather(*(service.send(bot.send_message, 1001, "account:456", "456", text=str(i)) for i in range(10)))
    bot.create_forum_topic.assert_awaited_once_with(chat_id=1001, name="456")
    assert {call.kwargs["message_thread_id"] for call in bot.send_message.call_args_list} == {1}
    restarted = TopicDelivery(bot, TopicsRepository(db_main.get_session_factory))
    await restarted.send(bot.send_message, 1001, "account:456", "456", text="restart")
    assert bot.create_forum_topic.await_count == 1
    await restarted.send(bot.send_message, 2002, "account:456", "456", text="new owner")
    await restarted.send(bot.send_message, 1001, "spoiler", "spoiler", text="attachment")
    assert bot.create_forum_topic.await_count == 3
    assert await repository.get(bot.id, 2002, "account:456") == 2
    assert await repository.get(bot.id, 1001, "spoiler") == 3


@pytest.mark.asyncio
async def test_disabled_mode_and_failed_capability_check_keep_ordinary_delivery(db_main):
    from services.notification_topics import TopicDelivery

    bot = fake_bot(False)
    service = TopicDelivery(bot, TopicsRepository(db_main.get_session_factory))
    await service.send(bot.send_message, 1001, "account:456", "456", text="plain")
    bot.send_message.assert_awaited_once_with(chat_id=1001, text="plain")
    bot.create_forum_topic.assert_not_awaited()
    bot.get_me.side_effect = RuntimeError("offline")
    service._checked_until = 0
    await service.send(bot.send_message, 1001, "account:456", "456", text="still delivered")
    assert "message_thread_id" not in bot.send_message.call_args.kwargs
    assert await service.enabled() is None
    bot.get_me.side_effect = None
    bot.get_me.return_value.has_topics_enabled = True
    service._checked_until = 0
    await service.send(bot.send_message, 1001, "account:456", "456", text="enabled later")
    assert bot.send_message.call_args.kwargs["message_thread_id"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["message thread not found", "TOPIC_CLOSED"])
async def test_removed_or_closed_topic_recovers_without_plain_duplicate(db_main, reason):
    from services.notification_topics import TopicDelivery

    bot = fake_bot(True)
    bot.send_message.side_effect = [TelegramBadRequest(method=SendMessage(chat_id=1001, text="test"), message=reason), True]
    repository = TopicsRepository(db_main.get_session_factory)
    service = TopicDelivery(bot, repository)
    await service.send(bot.send_message, 1001, "account:456", "456", text="test")
    assert bot.send_message.await_count == 2
    assert all("message_thread_id" in call.kwargs for call in bot.send_message.call_args_list)
    if reason == "TOPIC_CLOSED":
        bot.reopen_forum_topic.assert_awaited_once_with(chat_id=1001, message_thread_id=1)
        assert bot.create_forum_topic.await_count == 1
    else:
        assert await repository.get(bot.id, 1001, "account:456") == 2


@pytest.mark.asyncio
async def test_network_failure_after_send_is_not_retried_by_topic_routing(db_main):
    from services.notification_topics import TopicDelivery

    bot = fake_bot(True)
    bot.send_message.side_effect = TelegramNetworkError(method=SendMessage(chat_id=1001, text="test"), message="offline")
    service = TopicDelivery(bot, TopicsRepository(db_main.get_session_factory))
    with pytest.raises(TelegramNetworkError):
        await service.send(bot.send_message, 1001, "account:456", "456", text="test")
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_topic_creation_flood_wait_falls_back_without_repeated_creation(db_main):
    from services.notification_topics import TopicDelivery

    bot = fake_bot(True)
    bot.create_forum_topic.side_effect = TelegramRetryAfter(
        method=CreateForumTopic(chat_id=1001, name="456"), message="flood", retry_after=120)
    service = TopicDelivery(bot, TopicsRepository(db_main.get_session_factory))
    await service.send(bot.send_message, 1001, "account:456", "456", text="first")
    await service.send(bot.send_message, 1001, "account:456", "456", text="second")
    bot.create_forum_topic.assert_awaited_once()
    assert bot.send_message.await_count == 2
    assert all("message_thread_id" not in call.kwargs for call in bot.send_message.call_args_list)


@pytest.mark.asyncio
async def test_midnight_reminder_is_durable_timezone_aware_and_stops_when_enabled(db_main, offline_module):
    from services.notification_topics import TopicDelivery

    module = offline_module("aiotask/topic_reminder.py")
    module.get_admin_ids = AsyncMock(return_value=[1001])
    module.get_user_timezone_offset = AsyncMock(return_value=3)
    bot = fake_bot(False)
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    before = int(datetime(2026, 11, 5, 20, 59, tzinfo=timezone.utc).timestamp())
    midnight = before + 60
    await module.remind_missing_topics(bot, now=before, repository=repository)
    bot.send_photo.assert_not_awaited()
    await module.remind_missing_topics(bot, now=midnight, repository=repository)
    bot.send_photo.assert_awaited_once()
    assert "Threaded Mode" in bot.send_photo.call_args.kwargs["caption"]
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    await module.remind_missing_topics(bot, now=midnight + 10, repository=TopicsRepository(db_main.get_session_factory))
    assert bot.send_photo.await_count == 1
    bot.get_me.return_value.has_topics_enabled = True
    bot._watchtower_topic_delivery._checked_until = 0
    await module.remind_missing_topics(bot, now=midnight + 86400, repository=repository)
    assert bot.send_photo.await_count == 1


@pytest.mark.asyncio
async def test_failed_reminder_delivery_has_persistent_backoff(db_main, offline_module):
    from services.notification_topics import TopicDelivery

    module = offline_module("aiotask/topic_reminder.py")
    module.get_admin_ids = AsyncMock(return_value=[1001])
    module.get_user_timezone_offset = AsyncMock(return_value=0)
    bot = fake_bot(False)
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    bot.send_photo.side_effect = RuntimeError("offline")
    before = int(datetime(2026, 11, 5, 23, 59, tzinfo=timezone.utc).timestamp())
    await module.remind_missing_topics(bot, now=before, repository=repository)
    await module.remind_missing_topics(bot, now=before + 60, repository=repository)
    await module.remind_missing_topics(bot, now=before + 61, repository=repository)
    assert bot.send_photo.await_count == 1
    bot.send_photo.side_effect = None
    await module.remind_missing_topics(bot, now=before + 360, repository=repository)
    assert bot.send_photo.await_count == 2


@pytest.mark.asyncio
async def test_reminder_photo_id_reused_across_users_and_restart_but_scoped_to_bot_and_image(db_main, offline_module, tmp_path):
    module = offline_module("aiotask/topic_reminder.py")
    module.TOPICS_IMAGE = tmp_path / "image.png"
    module.TOPICS_IMAGE.write_bytes(b"synthetic-image-v1")
    bot = fake_bot(False)
    repository = TopicsRepository(db_main.get_session_factory)
    await asyncio.gather(*(module.send_instruction_photo(bot, owner, repository) for owner in (1001, 2002)))
    photos = [call.kwargs["photo"] for call in bot.send_photo.call_args_list]
    assert sum(isinstance(photo, FSInputFile) for photo in photos) == 1
    assert photos.count("instruction-photo") == 1
    restarted_bot = fake_bot(False)
    await module.send_instruction_photo(restarted_bot, 3003, TopicsRepository(db_main.get_session_factory))
    assert restarted_bot.send_photo.call_args.kwargs["photo"] == "instruction-photo"
    other_bot = fake_bot(False)
    other_bot.id += 1
    await module.send_instruction_photo(other_bot, 1001, repository)
    assert isinstance(other_bot.send_photo.call_args.kwargs["photo"], FSInputFile)
    module.TOPICS_IMAGE.write_bytes(b"synthetic-image-v2")
    await module.send_instruction_photo(restarted_bot, 1001, repository)
    assert isinstance(restarted_bot.send_photo.call_args.kwargs["photo"], FSInputFile)


@pytest.mark.asyncio
async def test_rejected_photo_id_is_replaced_by_one_fresh_upload(db_main, offline_module, tmp_path):
    import hashlib

    module = offline_module("aiotask/topic_reminder.py")
    module.TOPICS_IMAGE = tmp_path / "image.png"
    module.TOPICS_IMAGE.write_bytes(b"synthetic-image")
    image_hash = hashlib.sha256(module.TOPICS_IMAGE.read_bytes()).hexdigest()
    bot = fake_bot(False)
    repository = TopicsRepository(db_main.get_session_factory)
    await repository.save_photo(bot.id, image_hash, "expired")
    bot.send_photo.side_effect = [TelegramBadRequest(
        method=SendPhoto(chat_id=1001, photo="expired"), message="wrong file identifier specified"),
        SimpleNamespace(photo=[SimpleNamespace(file_id="fresh")])]
    await module.send_instruction_photo(bot, 1001, repository)
    assert bot.send_photo.await_count == 2
    assert bot.send_photo.call_args_list[0].kwargs["photo"] == "expired"
    assert isinstance(bot.send_photo.call_args_list[1].kwargs["photo"], FSInputFile)
    assert await repository.get_photo(bot.id, image_hash) == "fresh"


@pytest.mark.asyncio
@pytest.mark.parametrize("network_error", [False, True])
async def test_other_send_errors_do_not_invalidate_photo_or_repeat_delivery(db_main, offline_module, tmp_path, network_error):
    import hashlib

    module = offline_module("aiotask/topic_reminder.py")
    module.TOPICS_IMAGE = tmp_path / "image.png"
    module.TOPICS_IMAGE.write_bytes(b"synthetic-image")
    image_hash = hashlib.sha256(module.TOPICS_IMAGE.read_bytes()).hexdigest()
    bot = fake_bot(False)
    repository = TopicsRepository(db_main.get_session_factory)
    await repository.save_photo(bot.id, image_hash, "valid")
    error_class = TelegramNetworkError if network_error else TelegramBadRequest
    bot.send_photo.side_effect = error_class(method=SendPhoto(chat_id=1001, photo="valid"), message="offline")
    with pytest.raises(error_class):
        await module.send_instruction_photo(bot, 1001, repository)
    bot.send_photo.assert_awaited_once()
    assert await repository.get_photo(bot.id, image_hash) == "valid"
