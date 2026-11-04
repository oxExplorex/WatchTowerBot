import pytest
import pytest_asyncio
from sqlalchemy import select

from core.media_store import MediaStore
from core.personal_crypto import context, create_key_bundle, seal_text, unlock_private_key
from db.account_operation_models import AccountOperation, TransferRevision
from db.media_models import MessageAttachment
from db.message_models import MessageRevision, StoredMessage
from db.models import HistoryUser
from db.repositories.account_locks import AccountAlreadyConnected
from db.repositories.account_operations_repo import AccountOperationsRepository
from db.repositories.personal_repo import PersonalKeyRepository


@pytest_asyncio.fixture
async def account_data(db_main, tmp_path):
    await db_main.create_app_tg(1001, 12345, "synthetic-owner-api", "owner")
    await db_main.create_app_tg(2002, 23456, "synthetic-target-api", "target")
    source_app = (await db_main.get_app_tg_user_id(1001))[0][0]
    target_app = (await db_main.get_app_tg_user_id(2002))[0][0]
    account = await db_main.create_account_tg(1001, 2002, source_app.uuid, "79000000001")
    return dict(db=db_main, account=account, source_app=source_app, target_app=target_app,
                operations=AccountOperationsRepository(db_main.get_session_factory),
                keys=PersonalKeyRepository(db_main.get_session_factory),
                store=MediaStore(tmp_path / "media"))


async def record(data, message_id, *, account_id=2002, media=False):
    payload = {"text": f"synthetic private content {message_id}", "media": []}
    if media:
        payload["media"].append(dict(kind="document", file_id="offline-file-id", file_unique_id="offline-unique"))
    return await data["db"].messages_repository.record(owner_id=1001, account_user_id=account_id,
        chat_id=42, message_id=message_id, source="business", event_key=str(message_id),
        kind="new", payload=payload, sent_at=100 + message_id, require_account=True)


async def install_keys(data):
    first = create_key_bundle(1001, "Старыйсекрет527")
    second = create_key_bundle(2002, "Новыйсекрет938")
    await data["keys"].install(1001, first)
    await data["keys"].install(2002, second)
    return first, second, unlock_private_key(1001, first, "Старыйсекрет527"), unlock_private_key(2002, second, "Новыйсекрет938")


@pytest.mark.asyncio
async def test_transfer_survives_restart_keeps_originals_and_publishes_account_only(account_data):
    from services.account_transfer import prepare_batch, publish
    from services.personal_archive import migrate_batch

    data = account_data
    db, operations, store = data["db"], data["operations"], data["store"]
    await record(data, 1)  # Existing enc:v1 content before personal setup.
    old_bundle, new_bundle, old_private, new_private = await install_keys(data)
    await record(data, 2, media=True)
    other = await db.create_account_tg(1001, 3003, data["source_app"].uuid, "79000000002")
    untouched = await record(data, 90, account_id=other.user_id)
    with store.writer(1001, public_key=old_bundle["public_key"]) as writer:
        writer.write(b"synthetic encrypted attachment")
        old_blob, size = writer.finish()
    async with db.create_unit_of_work() as uow:
        attachment = await uow.session.scalar(select(MessageAttachment))
        attachment.status, attachment.blob_key, attachment.stored_size = "stored", old_blob, size
        from utils.crypto_store import decrypt_text
        attachment.sources = seal_text(old_bundle["public_key"], decrypt_text(attachment.sources), context(1001, f"sources:{attachment.uuid}"))
        attachment.sources_encryption_version, attachment.encryption_version = 2, 2
        attachment.state_version += 1
        # A previous owner may retain an empty identity of the same Telegram message.
        uow.session.add(StoredMessage(owner_id=2002, account_user_id=2002, chat_id=42, message_id=1, first_seen_at=1))
    operation = await operations.request_transfer(data["account"].uuid, 2002, data["target_app"].uuid)
    assert (await operations.request_transfer(data["account"].uuid, 2002, data["target_app"].uuid)).uuid == operation.uuid
    running = await operations.start_transfer(operation.uuid, 1001)
    assert await operations.start_transfer(operation.uuid, 1001) is None
    await prepare_batch(db.get_session_factory, operation.uuid, running.run_token, old_private, store, batch_size=1)
    assert (await db.get_account_uuid(data["account"].uuid, 1001)).admin_id == 1001
    assert store.path(1001, old_blob).is_file()
    await operations.recover_interrupted()
    resumed = await operations.get(operation.uuid, 1001)
    assert resumed.status == "needs_secret" and resumed.run_token is None
    assert "Старыйсекрет527" not in resumed.model_dump_json()
    running = await operations.start_transfer(operation.uuid, 1001)
    assert await record(data, 3) is not None  # Live capture continues during preparation.
    await migrate_batch(db.get_session_factory, 1001, store)  # Invalidates staged legacy ciphertext safely.
    for _ in range(20):
        if await prepare_batch(db.get_session_factory, operation.uuid, running.run_token, old_private, store, batch_size=1):
            assert await publish(db.get_session_factory, operation.uuid, running.run_token)
            assert (await operations.get(operation.uuid, 2002)).status == "activating"
            await operations.recover_interrupted()
            activation = await operations.claim_activation(operation.uuid)
            assert activation is not None
            await operations.finish_transfer(operation.uuid, activation.run_token)
            break
    else:
        pytest.fail("Transfer did not finish")
    assert (await operations.get(operation.uuid, 2002)).status == "complete"
    assert await db.get_account_uuid(data["account"].uuid, 1001) is None
    account = await db.get_account_uuid(data["account"].uuid, 2002)
    assert account.app_tg == data["target_app"].uuid and account.alert_new_chat_id == 2002
    async with db.create_unit_of_work() as uow:
        messages = (await uow.session.scalars(select(StoredMessage).where(StoredMessage.owner_id == 2002))).all()
        assert len(messages) == 3
        assert not list(await uow.session.scalars(select(TransferRevision)))
        attachment = await uow.session.scalar(select(MessageAttachment))
        assert attachment.owner_id == 2002 and attachment.sources_encryption_version == 2
        new_blob = attachment.blob_key
    for message in messages:
        revisions = await db.messages_repository.get_revisions(owner_id=2002, message_uuid=message.uuid)
        assert len(revisions) == 1
        decoded = db.messages_repository.decode_payload(revisions[0], owner_id=2002, private_key=new_private)
        assert decoded["text"] == f"synthetic private content {message.message_id}"
        with pytest.raises(ValueError):
            db.messages_repository.decode_payload(revisions[0], owner_id=2002, private_key=old_private)
    assert store.read(2002, new_blob, private_key=new_private) == b"synthetic encrypted attachment"
    other_revision = (await db.messages_repository.get_revisions(owner_id=1001, message_uuid=untouched.message_uuid))[0]
    assert db.messages_repository.decode_payload(other_revision, owner_id=1001, private_key=old_private)["text"].endswith("90")
    # A delayed producer with the old context is routed to the current owner.
    assert (await record(data, 4)).owner_id == 2002


@pytest.mark.asyncio
async def test_self_delete_erases_content_but_keeps_chat_history_and_shared_files(account_data, monkeypatch):
    from services import account_operations

    data = account_data
    db, operations, store = data["db"], data["operations"], data["store"]
    await record(data, 1, media=True)
    other = await db.create_account_tg(1001, 3003, data["source_app"].uuid, "79000000002")
    await record(data, 2, account_id=other.user_id, media=True)
    with store.writer(1001) as writer:
        writer.write(b"shared content")
        blob, size = writer.finish()
    async with db.create_unit_of_work() as uow:
        for attachment in await uow.session.scalars(select(MessageAttachment)):
            attachment.status, attachment.blob_key, attachment.stored_size = "stored", blob, size
            attachment.state_version += 1
        before = len(list(await uow.session.scalars(select(HistoryUser))))
    with pytest.raises(PermissionError):
        await operations.request_delete(data["account"].uuid, 9999)
    pending = await operations.request_delete(data["account"].uuid, 2002)
    restarted = AccountOperationsRepository(db.get_session_factory)
    assert (await restarted.get(pending.uuid, 2002)).status == "confirm_delete"
    await restarted.confirm_delete(pending.uuid, 2002)
    assert await record(data, 9) is None
    assert await restarted.erase_content(pending.uuid)
    await restarted.finish_delete(pending.uuid)
    async with db.create_unit_of_work() as uow:
        messages = (await uow.session.scalars(select(StoredMessage).where(StoredMessage.account_user_id == 2002))).all()
        assert len(messages) == 1 and messages[0].latest_revision_uuid is None
        assert not list(await uow.session.scalars(select(MessageRevision).where(MessageRevision.message_uuid == messages[0].uuid)))
        assert len(list(await uow.session.scalars(select(HistoryUser)))) == before
    assert await db.get_account_uuid(data["account"].uuid, 1001) is None
    assert await db.get_account_uuid(other.uuid, 1001) is not None
    monkeypatch.setattr(account_operations, "get_session_factory", db.get_session_factory)
    await account_operations.cleanup_blobs(store)
    assert store.read(1001, blob) == b"shared content"


@pytest.mark.asyncio
async def test_transfer_authorization_rejection_and_duplicate_registration(account_data):
    data = account_data
    db, operations = data["db"], data["operations"]
    await install_keys(data)
    for actor_id, profile in ((9999, data["target_app"]), (2002, data["source_app"])):
        with pytest.raises(PermissionError):
            await operations.request_transfer(data["account"].uuid, actor_id, profile.uuid)
    operation = await operations.request_transfer(data["account"].uuid, 2002, data["target_app"].uuid)
    with pytest.raises(PermissionError):
        await operations.start_transfer(operation.uuid, 2002)
    assert await operations.get(operation.uuid, 9999) is None
    assert (await operations.reject(operation.uuid, 1001)).status == "rejected"
    assert await operations.start_transfer(operation.uuid, 1001) is None
    assert (await db.get_account_uuid(data["account"].uuid, 1001)).admin_id == 1001
    with pytest.raises(AccountAlreadyConnected):
        await db.create_account_tg(2002, 2002, data["target_app"].uuid, "79000000001")


@pytest.mark.asyncio
async def test_failed_publication_rolls_back_ciphertext_and_can_resume(account_data, monkeypatch):
    from services import account_transfer

    data = account_data
    db, operations = data["db"], data["operations"]
    _, _, private, target_private = await install_keys(data)
    result = await record(data, 1)
    original = (await db.messages_repository.get_revisions(owner_id=1001, message_uuid=result.message_uuid))[0]
    operation = await operations.request_transfer(data["account"].uuid, 2002, data["target_app"].uuid)
    running = await operations.start_transfer(operation.uuid, 1001)
    while not await account_transfer.prepare_batch(db.get_session_factory, operation.uuid, running.run_token, private, data["store"]):
        pass
    # Force a failure after the ciphertext update, before ownership publication.
    from sqlalchemy.ext.asyncio import AsyncSession
    from db.models import AccountHealth
    execute = AsyncSession.execute

    async def fail_on_account_health(session, statement, *args, **kwargs):
        if getattr(getattr(statement, "table", None), "name", None) == AccountHealth.__tablename__:
            raise RuntimeError("synthetic publication failure")
        return await execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", fail_on_account_health)
    with pytest.raises(RuntimeError, match="synthetic publication failure"):
        await account_transfer.publish(db.get_session_factory, operation.uuid, running.run_token)
    monkeypatch.setattr(AsyncSession, "execute", execute)
    unchanged = (await db.messages_repository.get_revisions(owner_id=1001, message_uuid=result.message_uuid))[0]
    assert unchanged.payload == original.payload
    assert db.messages_repository.decode_payload(unchanged, owner_id=1001, private_key=private)["text"].endswith("1")
    assert (await db.get_account_uuid(data["account"].uuid, 1001)).admin_id == 1001
    await operations.pause(operation.uuid, running.run_token, "RuntimeError")
    running = await operations.start_transfer(operation.uuid, 1001)
    assert await account_transfer.publish(db.get_session_factory, operation.uuid, running.run_token)
    moved = (await db.messages_repository.get_revisions(owner_id=2002, message_uuid=result.message_uuid))[0]
    assert db.messages_repository.decode_payload(moved, owner_id=2002, private_key=target_private)["text"].endswith("1")


@pytest.mark.asyncio
async def test_delete_waits_for_media_lease_and_only_requester_can_cancel(account_data):
    import time

    data = account_data
    db, operations = data["db"], data["operations"]
    await record(data, 1, media=True)
    pending = await operations.request_delete(data["account"].uuid, 2002)
    with pytest.raises(PermissionError):
        await operations.reject(pending.uuid, 1001)
    async with db.create_unit_of_work() as uow:
        attachment = await uow.session.scalar(select(MessageAttachment))
        attachment.status, attachment.lease_until = "downloading", int(time.time()) + 600
    await operations.confirm_delete(pending.uuid, 2002)
    assert not await operations.erase_content(pending.uuid)
    assert await db.get_account_uuid(data["account"].uuid, 1001) is not None
    async with db.create_unit_of_work() as uow:
        attachment = await uow.session.scalar(select(MessageAttachment))
        attachment.lease_until = 0
    assert await operations.erase_content(pending.uuid)


@pytest.mark.asyncio
async def test_profile_selector_paginates_thousand_profiles_and_callbacks_fit(account_data):
    from db.models import TelegramApp
    from keyboards.inline.account_ownership import profiles_keyboard
    from callbacks.account_ownership import OwnAccount

    db = account_data["db"]
    async with db.create_unit_of_work() as uow:
        uow.session.add_all([TelegramApp(user_id=4004, app_id=i + 10000, api_hash="synthetic", tag_name=f"app-{i}")
                            for i in range(1000)])
    seen = set()
    for page in (0, 1, 199):
        profiles, count = await db.get_app_tg_user_id(4004, page * 5)
        assert count == 1000 and len(profiles) == 5
        assert not seen.intersection(p.uuid for p in profiles)
        seen.update(p.uuid for p in profiles)
        keyboard = profiles_keyboard(profiles, page, 200)
        for row in keyboard.inline_keyboard:
            for button in row:
                assert len(button.callback_data.encode("utf-8")) <= 64
        choices = [OwnAccount.unpack(row[0].callback_data) for row in keyboard.inline_keyboard[:5]]
        assert {choice.token for choice in choices} == {p.uuid.hex for p in profiles}


@pytest.mark.asyncio
async def test_recovered_activation_reuses_registered_client(account_data, monkeypatch):
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from services import account_operations

    data = account_data
    db = data["db"]
    monkeypatch.setitem(sys.modules, "db.main", db)
    manager = SimpleNamespace(add=AsyncMock())
    monkeypatch.setitem(sys.modules, "loader", SimpleNamespace(session_manager=manager))
    client = SimpleNamespace(api_id=1, api_hash="old")
    monkeypatch.setattr(account_operations, "get_session_factory", db.get_session_factory)
    monkeypatch.setattr(account_operations, "get_client_by_number", AsyncMock(return_value=client))
    start = AsyncMock()
    monkeypatch.setattr(account_operations, "start_client", start)
    await account_operations._restart_transferred_client(SimpleNamespace(account_uuid=data["account"].uuid, actor_id=1001), None)
    manager.add.assert_awaited_once_with(client)
    start.assert_awaited_once_with(client)
    assert client.api_id == data["source_app"].app_id


@pytest.mark.asyncio
async def test_completed_self_delete_sends_one_notification_without_repeating(account_data, monkeypatch):
    from unittest.mock import AsyncMock
    from services import account_operations

    data = account_data
    db, operations = data["db"], data["operations"]
    account = await db.create_account_tg(1001, 1001, data["source_app"].uuid, "79000000003")
    pending = await operations.request_delete(account.uuid, 1001)
    await operations.confirm_delete(pending.uuid, 1001)
    assert await operations.erase_content(pending.uuid)
    await operations.finish_delete(pending.uuid)
    monkeypatch.setattr(account_operations, "get_session_factory", db.get_session_factory)
    bot = AsyncMock()
    await account_operations.notify_operations(bot)
    await account_operations.notify_operations(bot)
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.args[0] == 1001
