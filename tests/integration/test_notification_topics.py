import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import CreateForumTopic, SendMessage, SendPhoto
from aiogram.types import FSInputFile
import pytest

from db.repositories.topics_repo import TopicsRepository


@pytest.mark.asyncio
async def test_startup_reporter_resolves_logs_instead_of_manual_update_panel(db_main, tmp_path):
    from scripts.startup_status import StartupReporter
    from services.notification_topics import TopicDelivery, configure_startup_reporter

    bot = fake_bot(True)
    bot.token = "123456:synthetic"
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    await repository.save(bot.id, 1001, "logs", 80)
    await repository.save(bot.id, 2002, "logs", 81)
    report = StartupReporter(root=tmp_path)  # No credentials: no real notification worker.
    report.thread_ids[2002] = 90
    report.configure = Mock()
    await configure_startup_reporter(bot, report, [1001, 2002])
    report.configure.assert_called_once_with(bot.token, [1001, 2002], thread_ids={1001: 80, 2002: 81})
    bot.create_forum_topic.assert_not_awaited()


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
async def test_update_announcement_survives_restart_in_logs_and_gets_close_button(db_main, tmp_path, monkeypatch):
    from scripts.startup_status import StartupReporter
    from services import startup_notifications as startup
    from services.notification_topics import TopicDelivery
    bot = fake_bot(True)
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    await repository.save(bot.id, 1001, "logs", 43)
    await repository.save(bot.id, 1001, "menu", 42)
    bot.send_message.return_value = SimpleNamespace(message_id=500, message_thread_id=43)
    bot.edit_message_text = AsyncMock()
    report = StartupReporter(root=tmp_path)
    report.recipients, report.operation = [1001], "Обновление"
    await startup.announce_update(bot, report, "2.1.2", "2.1.3")
    initial = bot.send_message.await_args.kwargs
    assert initial["message_thread_id"] == 43 and "Подождите" in initial["text"]
    assert report.message_ids == {1001: 500}
    report.prepare_restart()  # No token/worker: all transport is synthetic.
    (tmp_path / "VERSION").write_text("2.1.3", encoding="utf-8")
    after = StartupReporter(root=tmp_path)
    after.finish()
    monkeypatch.setattr(startup, "get_admin_ids", AsyncMock(return_value=[1001]))
    await startup.restore_startup_notifications(bot, after)
    result = bot.edit_message_text.await_args.kwargs
    assert result["message_id"] == 500
    assert "Запущен бот версии <code>2.1.3</code>" in result["text"]
    assert [b.callback_data for row in result["reply_markup"].inline_keyboard for b in row] == ["startup:close"]


@pytest.mark.asyncio
async def test_runtime_reporter_uses_aiogram_session_instead_of_early_http(db_main, tmp_path):
    from scripts.startup_status import StartupReporter
    from services.startup_notifications import use_runtime_transport
    bot = fake_bot(False)
    bot.send_message.return_value = SimpleNamespace(message_id=500)
    early = Mock(side_effect=AssertionError("Early HTTP must not be used after bootstrap"))
    report = StartupReporter("123456:synthetic", [1001], root=tmp_path, transport=early)
    report.thread_ids[1001] = 43
    use_runtime_transport(bot, report)
    report.finish()
    await asyncio.to_thread(report.close, 3)
    early.assert_not_called()
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["message_thread_id"] == 43
    assert report.message_ids == {1001: 500} and not report.running


@pytest.mark.asyncio
async def test_update_reuses_menu_after_restart_instead_of_leaving_progress_and_sending_duplicate(db_main, tmp_path, monkeypatch):
    from scripts.startup_status import StartupReporter
    from services import startup_notifications as startup
    from services.notification_topics import TopicDelivery, send_startup_menu
    bot = fake_bot(True)
    bot.edit_message_text = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=500, message_thread_id=43)
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    await repository.save(bot.id, 1001, "logs", 43)
    await repository.save(bot.id, 1001, "menu", 42)
    panel = SimpleNamespace(message_id=88, message_thread_id=42, bot=bot, chat=SimpleNamespace(id=1001),
        edit_text=AsyncMock(return_value=SimpleNamespace(message_id=88)))
    report = StartupReporter(root=tmp_path)
    report.recipients, report.operation = [1001], "Обновление"
    await startup.prepare_update_menu(panel, report)
    assert report.menu_ids == {1001: 88}
    assert "Обновление запущено" not in panel.edit_text.await_args.kwargs["text"]
    assert panel.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
    await startup.announce_update(bot, report, "2.1.4", "2.1.5")
    report.prepare_restart()
    after = StartupReporter(root=tmp_path)
    assert after.menu_ids == {1001: 88}
    after.finish()
    # Topic preparation may run before the final startup notification task.
    bot._watchtower_restart_menus = dict(after.menu_ids)
    await send_startup_menu(bot, 1001)
    monkeypatch.setattr(startup, "get_admin_ids", AsyncMock(return_value=[1001]))
    await startup.restore_startup_notifications(bot, after)
    assert [call.kwargs["message_id"] for call in bot.edit_message_text.await_args_list] == [88, 500]
    assert bot.send_message.await_count == 1  # Only the update log, never another menu.


@pytest.mark.asyncio
async def test_update_from_logs_never_turns_log_message_into_menu(db_main, tmp_path):
    from scripts.startup_status import StartupReporter
    from services.startup_notifications import prepare_update_menu
    from services.notification_topics import TopicDelivery
    bot = fake_bot(True)
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    await repository.save(bot.id, 1001, "menu", 42)
    panel = SimpleNamespace(message_id=88, message_thread_id=43, bot=bot,
                            chat=SimpleNamespace(id=1001), edit_text=AsyncMock())
    report = StartupReporter(root=tmp_path)
    await prepare_update_menu(panel, report)
    panel.edit_text.assert_not_awaited()
    assert report.menu_ids == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted", [True, False])
async def test_restart_menu_recovery_is_idempotent_for_deleted_or_unchanged_panel(db_main, deleted):
    from aiogram.methods import EditMessageText
    from services.notification_topics import TopicDelivery, send_startup_menu
    bot = fake_bot(True)
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    bot._watchtower_restart_menus = {1001: 88}
    await repository.save(bot.id, 1001, "menu", 42)
    bot.edit_message_text = AsyncMock(side_effect=TelegramBadRequest(
        method=EditMessageText(chat_id=1001, message_id=88, text="test"),
        message="message to edit not found" if deleted else "message is not modified"))
    await send_startup_menu(bot, 1001)
    await send_startup_menu(bot, 1001)
    assert bot.edit_message_text.await_count == 1
    assert bot.send_message.await_count == (1 if deleted else 0)
    if deleted:
        assert bot.send_message.await_args.kwargs["message_thread_id"] == 42


@pytest.mark.asyncio
async def test_available_update_notification_uses_logs_topic(db_main, offline_module, monkeypatch):
    import sys
    from services.notification_topics import TopicDelivery
    bot = fake_bot(True)
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    await repository.save(bot.id, 1001, "logs", 43)
    monkeypatch.setitem(sys.modules, "loader", SimpleNamespace(bot=bot))
    module = offline_module("aiotask/update_notifier.py")
    assert await module._safe_send(1001, "test update available", include_update=True)
    assert bot.send_message.await_args.kwargs["message_thread_id"] == 43


@pytest.mark.asyncio
@pytest.mark.parametrize("topics_enabled", [False, True])
async def test_restart_restores_existing_menu_when_bootstrap_delivery_failed(
        db_main, monkeypatch, tmp_path, topics_enabled):
    from scripts.startup_status import StartupReporter
    from services import startup_notifications as startup
    from services.notification_topics import TopicDelivery, prepare_notification_topics

    bot = fake_bot(topics_enabled)
    bot.edit_message_text = AsyncMock()
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    await repository.save(bot.id, 1001, "menu", 42)
    monkeypatch.setattr(startup, "get_admin_ids", AsyncMock(return_value=[1001]))
    monkeypatch.setattr(db_main, "get_admin_ids", AsyncMock(return_value=[1001]))
    monkeypatch.setattr(db_main, "get_account_all", AsyncMock(return_value=[]))
    monkeypatch.setattr(db_main, "get_configured_admin_ids", lambda: [])
    report = StartupReporter(root=tmp_path)
    report.recipients = [1001, 9999]  # A removed administrator gets no retry.
    report.message_ids[1001] = 500
    report.operation = "Обновление"
    report.finish()
    await startup.restore_startup_notifications(bot, report)
    await prepare_notification_topics(bot)
    menus = [call.kwargs for call in bot.send_message.await_args_list
             if "reply_markup" in call.kwargs]
    assert len(menus) == 1
    assert menus[0]["chat_id"] == 1001
    assert menus[0].get("message_thread_id") == (42 if topics_enabled else None)
    assert "panel:accounts" in {button.callback_data for row in
                               menus[0]["reply_markup"].inline_keyboard for button in row}
    bot.edit_message_text.assert_awaited_once()
    assert bot.edit_message_text.await_args.kwargs["message_id"] == 500
    assert "WatchTowerBot обновлён" in bot.edit_message_text.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_startup_result_replacement_uses_logs_when_original_panel_was_deleted(db_main, monkeypatch, tmp_path):
    from scripts.startup_status import StartupReporter
    from services import startup_notifications as startup
    from services.notification_topics import TopicDelivery
    from aiogram.methods import EditMessageText

    bot = fake_bot(True)
    bot.edit_message_text = AsyncMock(side_effect=TelegramBadRequest(
        method=EditMessageText(chat_id=1001, message_id=500, text="test"),
        message="message to edit not found"))
    repository = TopicsRepository(db_main.get_session_factory)
    bot._watchtower_topic_delivery = TopicDelivery(bot, repository)
    await repository.save(bot.id, 1001, "menu", 42)
    await repository.save(bot.id, 1001, "logs", 43)
    monkeypatch.setattr(startup, "get_admin_ids", AsyncMock(return_value=[1001]))
    report = StartupReporter(root=tmp_path)
    report.recipients = [1001]
    report.message_ids[1001] = 500
    report.finish()
    await startup.restore_startup_notifications(bot, report)
    assert [call.kwargs["message_thread_id"] for call in bot.send_message.await_args_list] == [42, 43]


@pytest.mark.asyncio
async def test_startup_prepares_topics_including_server_logs_only_for_configured_admins(db_main, monkeypatch):
    from services.notification_topics import TopicDelivery, prepare_notification_topics
    bot = fake_bot(True)
    bot._watchtower_topic_delivery = TopicDelivery(bot, TopicsRepository(db_main.get_session_factory))
    monkeypatch.setattr(db_main, "get_admin_ids", AsyncMock(return_value=[1001, 2002]))
    monkeypatch.setattr(db_main, "get_configured_admin_ids", lambda: [1001])
    accounts = [SimpleNamespace(admin_id=1001, user_id=456), SimpleNamespace(admin_id=1001, user_id=789)]
    monkeypatch.setattr(db_main, "get_account_all", AsyncMock(return_value=accounts))
    await prepare_notification_topics(bot)
    assert {(c.kwargs["chat_id"], c.kwargs["name"]) for c in bot.create_forum_topic.call_args_list} == {
        (1001, "456"), (1001, "789"), (1001, "spoiler"), (2002, "spoiler"), (1001, "Меню"), (2002, "Меню"),
        (1001, "Логи"), (1001, "Бекапы")}
    assert bot.send_message.await_count == 2
    assert all(call.kwargs["reply_markup"].inline_keyboard for call in bot.send_message.call_args_list)
    await prepare_notification_topics(bot)
    assert bot.create_forum_topic.await_count == 8
    assert bot.send_message.await_count == 2
    await prepare_notification_topics(bot, owner_id=2002, account_user_id=999)
    assert bot.create_forum_topic.await_count == 9
    assert bot.create_forum_topic.call_args.kwargs == dict(chat_id=2002, name="999")


@pytest.mark.asyncio
async def test_preparation_respects_disabled_mode_and_flood_backoff(db_main):
    from services.notification_topics import TopicDelivery, prepare_notification_topics
    bot = fake_bot(False)
    bot._watchtower_topic_delivery = service = TopicDelivery(bot, TopicsRepository(db_main.get_session_factory))
    await prepare_notification_topics(bot, owner_id=1001, account_user_id=456)
    bot.create_forum_topic.assert_not_awaited()
    bot.get_me.return_value.has_topics_enabled = True
    service._checked_until = 0
    bot.create_forum_topic.side_effect = TelegramRetryAfter(
        method=CreateForumTopic(chat_id=1001, name="spoiler"), message="flood", retry_after=120)
    await prepare_notification_topics(bot, owner_id=1001, account_user_id=456)
    await prepare_notification_topics(bot, owner_id=1001, account_user_id=456)
    assert bot.create_forum_topic.await_count == 1  # FloodWait pauses creation of every destination.


@pytest.mark.asyncio
async def test_topic_worker_prepares_before_first_reminder(offline_module):
    module = offline_module("aiotask/topic_reminder.py")
    prepared = AsyncMock()
    module.prepare_notification_topics = prepared
    module.remind_missing_topics = AsyncMock(side_effect=asyncio.CancelledError)
    bot = SimpleNamespace()
    with pytest.raises(asyncio.CancelledError):
        await module.run_topic_reminders(bot)
    prepared.assert_awaited_once_with(bot)


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
async def test_creation_pause_does_not_disable_existing_topics(db_main):
    from services.notification_topics import TopicDelivery
    bot = fake_bot(True)
    service = TopicDelivery(bot, TopicsRepository(db_main.get_session_factory))
    await service.send(bot.send_message, 1001, "account:456", "456", text="before")
    service._topic_retry_until = float("inf")
    await service.send(bot.send_message, 1001, "account:456", "456", text="during pause")
    assert bot.send_message.call_args.kwargs["message_thread_id"] == 1
    bot.create_forum_topic.assert_awaited_once()


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
