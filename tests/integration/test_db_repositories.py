from __future__ import annotations

import pytest
import asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_crud_app_and_account(db_main):
    await db_main.create_app_tg(user_id=1001, app_id=12345, api_hash="hash_a", tag_name="test-app")
    apps, count = await db_main.get_app_tg_user_id(user_id=1001)
    assert count == 1
    assert len(apps) == 1

    account = await db_main.create_account_tg(
        admin_id=5001,
        user_id=9001,
        app_tg=apps[0].uuid,
        number="79000000001",
    )
    assert account is not None

    by_number = await db_main.get_account_by_number("79000000001")
    assert by_number is not None
    assert int(by_number.user_id) == 9001

    deleted = await db_main.delete_account_by_number("79000000001")
    assert deleted is not None
    assert await db_main.get_account_by_number("79000000001") is None


@pytest.mark.asyncio
async def test_unique_constraint_for_telegram_app(db_main):
    await db_main.create_app_tg(user_id=1010, app_id=2222, api_hash="dup_hash", tag_name="a")

    with pytest.raises(IntegrityError):
        await db_main.create_app_tg(user_id=1010, app_id=2222, api_hash="dup_hash", tag_name="b")


@pytest.mark.asyncio
async def test_runtime_accounts_join_preserves_credentials_and_excludes_disabled(db_main):
    await db_main.create_app_tg(5001, 12345, "synthetic-app-hash", "runtime")
    apps, _ = await db_main.get_app_tg_user_id(5001)
    active = await db_main.create_account_tg(5001, 9001, apps[0].uuid, "79000000001")
    disabled = await db_main.create_account_tg(5001, 9002, apps[0].uuid, "79000000002")
    await db_main.update_account_uuid(disabled.uuid, 5001, is_active=0)
    rows = await db_main.get_active_accounts_with_apps()
    assert len(rows) == 1
    account, app = rows[0]
    assert account.uuid == active.uuid and account.number == "79000000001"
    assert app.uuid == apps[0].uuid and app.api_hash == "synthetic-app-hash"
    await db_main.update_user(9001, "runtime_user", "Runtime Name")
    assert await db_main.get_user_names_by_ids([9001, 9002]) == {9001: "Runtime Name"}
    assert await db_main.get_account_counts_by_apps([apps[0].uuid]) == {apps[0].uuid: 2}


@pytest.mark.asyncio
async def test_unit_of_work_rollback(db_main):
    with pytest.raises(RuntimeError):
        async with db_main.create_unit_of_work() as uow:
            assert uow.users is not None
            await uow.users.update_user(6001, username="rollback_user", full_name="Rollback User")
            raise RuntimeError("force rollback")

    user = await db_main.get_user(6001)
    assert user is None


@pytest.mark.asyncio
async def test_unit_of_work_commit(db_main):
    async with db_main.create_unit_of_work() as uow:
        assert uow.settings is not None
        await uow.settings.set_user_timezone_offset(7001, 5)
        await uow.settings.set_user_auto_update_enabled(7001, 1)

    tz = await db_main.get_user_timezone_offset(7001)
    auto_update = await db_main.get_user_auto_update_enabled(7001)
    assert tz == 5
    assert auto_update == 1


@pytest.mark.asyncio
async def test_concurrent_profile_and_settings_creation_preserves_all_changes(db_main):
    results = await asyncio.gather(
        db_main.update_user(6100, "concurrent_user", "Concurrent User"),
        db_main.set_user_timezone_offset(6100, 5),
        db_main.set_user_auto_update_enabled(6100, 1),
        return_exceptions=True,
    )
    assert not [type(result).__name__ for result in results if isinstance(result, BaseException)]
    user = await db_main.get_user(6100)
    assert user.username == "concurrent_user"
    assert user.timezone_offset == 5
    assert user.auto_update_enabled == 1


@pytest.mark.asyncio
async def test_unique_user_id_enforced(db_main):
    from db.models import User

    async with db_main.create_unit_of_work() as uow:
        assert uow.session is not None
        uow.session.add(User(user_id=8001))

    with pytest.raises(IntegrityError):
        async with db_main.create_unit_of_work() as uow:
            assert uow.session is not None
            uow.session.add(User(user_id=8001))

    async with db_main.create_unit_of_work() as uow:
        assert uow.session is not None
        rows = (await uow.session.execute(select(User).where(User.user_id == 8001))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("present", [True, False])
async def test_presence_history_are_atomic_and_duplicate_changes_are_ignored(db_main, monkeypatch, present):
    repository = db_main.accounts_repository
    if not present:
        await db_main.create_dump_chat_user(9001, 42)
    original = repository.add_chat_history_event

    async def failed_history(*args, **kwargs):
        raise RuntimeError("injected history failure")

    monkeypatch.setattr(repository, "add_chat_history_event", failed_history)
    with pytest.raises(RuntimeError, match="injected history failure"):
        await db_main.record_chat_presence(9001, 42, 5001, present=present, date=100)
    assert (await db_main.get_dump_chat_user(9001, 42) is not None) == (not present)
    assert await db_main.get_chat_history_events(5001, 42) == []

    monkeypatch.setattr(repository, "add_chat_history_event", original)
    assert await db_main.record_chat_presence(9001, 42, 5001, present=present, date=100)
    assert not await db_main.record_chat_presence(9001, 42, 5001, present=present, date=101)
    events = await db_main.get_chat_history_events(5001, 42)
    assert len(events) == 1
    assert events[0].action_id == (1 if present else 2)
    assert events[0].account_user_id == 9001
