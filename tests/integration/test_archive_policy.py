from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from core.media_store import MediaStore
from core.personal_crypto import create_key_bundle
from db.avatar_models import ChatAvatar
from db.chat_policy_models import ArchiveChatPolicy
from db.media_models import MessageAttachment
from db.message_models import MessageReceipt, MessageRevision, PendingMessageDeletion, StoredMessage
from db.models import DumpChatUser, HistoryUser, User, UsernameHistory
from db.repositories.chat_policy_repo import ChatPolicyRepository
from db.repositories.ignored_chats_repo import purge_ignored_chats
from db.repositories.personal_repo import PersonalKeyRepository
from services.backup_snapshot import create_backup
from services.backup_restore import prepare_backup
from utils.archive_policy import archive_allowed


@pytest.mark.asyncio
async def test_all_sources_ignore_telegram_codes_and_excluded_chat_types(db_main, offline_module):
    module = offline_module("services/message_service.py")
    bot = SimpleNamespace(id=99999)
    context = module.AccountContext(123, 456)
    cases = [(777000, "private", None), (7001, "bot", None), (-1001, "channel", None),
             (-1002, "supergroup", 101), (-1003, "group", 2), (-1004, "group", None)]
    for chat_id, kind, count in cases:
        chat = SimpleNamespace(id=chat_id, type=kind, members_count=count)
        message = SimpleNamespace(id=1, chat=chat, text="must never be archived")
        for source in ("business", "userbot", "history"):
            assert await module.save_message(bot, context, message, source=source, kind="new") is None
            assert await module.delete_message(bot, context, 1, source=source, chat=chat) is None
    async with db_main.get_session_factory()() as session:
        for model in (StoredMessage, MessageRevision, MessageReceipt, MessageAttachment, DumpChatUser, ChatAvatar):
            assert not list(await session.scalars(select(model)))
        assert await session.get(ArchiveChatPolicy, (456, 777000)) is None
    assert archive_allowed(789, "private")
    assert not archive_allowed(-1003, "group")


@pytest.mark.asyncio
async def test_groups_are_rejected_without_fetching_member_counts(db_main):
    from services.archive_policy import assess_chat
    for size in (None, 2, 100, 101):
        chat = SimpleNamespace(id=-50, type="group", members_count=size)
        assert await assess_chat(456, chat) is None
    assert await assess_chat(456, SimpleNamespace(id=789, type="private")) == "private"


@pytest.mark.asyncio
async def test_known_bot_update_is_rejected_before_any_message_is_stored(db_main, tmp_path):
    owner, account, secret = 123, 456, "АрхивСекрет123"
    await PersonalKeyRepository(db_main.get_session_factory).install(owner, create_key_bundle(owner, secret))
    await db_main.messages_repository.record(owner_id=owner, account_user_id=account, chat_id=789,
        message_id=1, source="business", kind="new", event_key="original", payload={"text": "text", "media": []})
    await ChatPolicyRepository(db_main.get_session_factory).remember(account, 790, "bot")
    assert await db_main.messages_repository.record(owner_id=owner, account_user_id=account, chat_id=790,
        message_id=2, source="business", kind="new", event_key="partial", chat_kind="private",
        payload={"text": "must not be saved", "media": []}) is None
    paths, counts = await create_backup(owner, tmp_path / "parts", uuid4().hex,
        session_factory=db_main.get_session_factory, store=MediaStore(tmp_path / "media"))
    assert counts["messages"] == 1
    prepared = prepare_backup(paths, tmp_path / "prepared", owner, secret)
    assert {row.chat_id for table, row in prepared.rows if table == "messages"} == {789}


@pytest.mark.asyncio
async def test_backup_does_not_hide_unclassified_legacy_messages(db_main, tmp_path):
    secret = "АрхивСекрет123"
    await PersonalKeyRepository(db_main.get_session_factory).install(123, create_key_bundle(123, secret))
    async with db_main.get_session_factory()() as session, session.begin():
        session.add(StoredMessage(owner_id=123, account_user_id=456, chat_id=789,
                                  message_id=1, first_seen_at=1))
    paths, counts = await create_backup(123, tmp_path / "parts", uuid4().hex,
        session_factory=db_main.get_session_factory, store=MediaStore(tmp_path / "media"))
    assert counts["messages"] == 1
    prepared = prepare_backup(paths, tmp_path / "prepared", 123, secret)
    assert {row.chat_id for table, row in prepared.rows if table == "messages"} == {789}


@pytest.mark.asyncio
@pytest.mark.parametrize("removed_chat,kind", [(777000, None), (7001, "bot"), (-7002, "group"), (-1007003, "channel")])
async def test_forbidden_chat_cleanup_is_idempotent_and_preserves_shared_media(
        db_main, tmp_path, offline_module, removed_chat, kind):
    store = MediaStore(tmp_path / "media")
    keys = []
    for content in (b"shared-image", b"only-codes-chat"):
        with store.writer(123) as writer:
            writer.write(content)
            keys.append(writer.finish()[0])
    doomed = []
    for message_id, chat_id in ((1, 888), (2, 888), (3, 789)):
        item = await db_main.messages_repository.record(owner_id=123, account_user_id=456, chat_id=chat_id,
            message_id=message_id, source="userbot", kind="new", event_key=str(message_id),
            payload={"text": "synthetic", "media": [{"kind": "document", "file_id": str(message_id),
                "file_unique_id": str(message_id)}]})
        if chat_id == 888:
            doomed.append(item.message_uuid)
    async with db_main.get_session_factory()() as session, session.begin():
        await session.execute(update(StoredMessage).where(StoredMessage.uuid.in_(doomed)).values(chat_id=removed_chat))
        if kind:
            session.add(ArchiveChatPolicy(account_user_id=456, chat_id=removed_chat, kind=kind))
        attachments = list(await session.scalars(select(MessageAttachment).join(MessageRevision).join(StoredMessage)
                            .order_by(StoredMessage.message_id)))
        for attachment, key in zip(attachments, (keys[0], keys[1], keys[0])):
            attachment.blob_key, attachment.status = key, "stored"
        session.add(PendingMessageDeletion(owner_id=123, account_user_id=456, message_id=1,
                                          observed_at=1, resolved_message_uuid=doomed[0]))
        session.add_all([User(user_id=removed_chat), UsernameHistory(user_id=removed_chat, date=1),
            DumpChatUser(admin_id=456, chat_id=removed_chat), HistoryUser(admin_id=123, user_id=removed_chat, action_id=1, date=1),
            ChatAvatar(owner_id=123, account_user_id=456, user_id=removed_chat, photo_key="old", blob_key=keys[1], status="stored")])
    assert await purge_ignored_chats(db_main.get_session_factory) == 2
    assert await purge_ignored_chats(db_main.get_session_factory) == 0
    async with db_main.get_session_factory()() as session:
        assert {row.chat_id for row in await session.scalars(select(StoredMessage))} == {789}
        assert not list(await session.scalars(select(PendingMessageDeletion)))
        for model in (User, UsernameHistory, ChatAvatar):
            assert not list(await session.scalars(select(model).where(model.user_id == removed_chat)))
    cleanup = offline_module("services/account_operations.py").cleanup_blobs
    await cleanup(store)
    assert store.path(123, keys[0]).exists()
    assert not store.path(123, keys[1]).exists()


@pytest.mark.asyncio
async def test_legacy_type_discovery_purges_confirmed_bots_but_preserves_unknown_and_humans(db_main, offline_module):
    module = offline_module("services/archive_cleanup.py")
    await db_main.create_app_tg(123, 12345, "synthetic", "app")
    app = (await db_main.get_app_tg_user_id(123))[0][0]
    await db_main.create_account_tg(123, 456, app.uuid, "79000000001")
    for peer in (7001, 7002, 7003):
        await db_main.messages_repository.record(owner_id=123, account_user_id=456, chat_id=peer,
            message_id=1, source="userbot", kind="new", event_key=str(peer), payload={"text": "synthetic"})
    await db_main.messages_repository.record(owner_id=124, account_user_id=457, chat_id=7001,
        message_id=1, source="business", kind="new", event_key="other-owner", payload={"text": "synthetic"})
    async with db_main.get_session_factory()() as session, session.begin():
        await session.execute(delete(ArchiveChatPolicy).where(ArchiveChatPolicy.account_user_id == 456))
    client = SimpleNamespace(get_users=AsyncMock(return_value=[
        SimpleNamespace(id=7001, is_bot=True),
        SimpleNamespace(id=7002, is_bot=False, username="human_name_ends_in_bot"),
        SimpleNamespace(id=7003, is_bot=None)]))
    limits = SimpleNamespace(blocked_until=AsyncMock(return_value=0), defer=AsyncMock())
    await module.classify_legacy_chats(client, SimpleNamespace(user_id=456, admin_id=123), limits,
                                     repository=ChatPolicyRepository(db_main.get_session_factory))
    client.get_users.assert_awaited_once_with([7001, 7002, 7003])
    async with db_main.get_session_factory()() as session:
        assert {row.chat_id for row in await session.scalars(select(StoredMessage))} == {7002, 7003}
        pending = await session.get(ArchiveChatPolicy, (456, 7003))
        assert pending.kind == "unresolved" and pending.retry_at > 0
    assert await db_main.messages_repository.record(owner_id=124, account_user_id=457, chat_id=7001,
        message_id=2, source="business", kind="new", event_key="partial", payload={"text": "blocked"}) is None


@pytest.mark.asyncio
async def test_legacy_peer_lookup_isolates_invalid_ids_without_unbounded_requests(offline_module):
    from pyrogram.errors import PeerIdInvalid
    module = offline_module("services/archive_cleanup.py")
    async def lookup(peers):
        if 3 in peers:
            raise PeerIdInvalid()
        return [SimpleNamespace(id=peer, is_bot=False) for peer in peers]
    client = SimpleNamespace(get_users=AsyncMock(side_effect=lookup))
    found = await module._resolve_users(client, [1, 2, 3, 4], [5])
    assert {user.id for user in found} == {1, 2, 4}
    assert client.get_users.await_count == 5
