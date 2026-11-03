from __future__ import annotations

import pytest
from sqlalchemy import select

from db.models import Account, User, UsernameHistory


async def seed(db):
    await db.update_user(1001, "alice", "Alice")
    await db.create_app_tg(1001, 12345, "synthetic-hash", "app")
    apps, _ = await db.get_app_tg_user_id(1001)
    return await db.create_account_tg(1001, 9001, apps[0].uuid, "79000000001")


async def raw_values(db):
    async with db.create_unit_of_work() as uow:
        users = (await uow.session.execute(select(User.user_id, User.username, User.full_name, User.username_hash))).all()
        accounts = (await uow.session.execute(select(Account.uuid, Account.number, Account.number_hash))).all()
        history = (await uow.session.execute(select(UsernameHistory.uuid, UsernameHistory.username, UsernameHistory.username_hash))).all()
    return users, accounts, history


@pytest.mark.asyncio
async def test_reading_user_in_transaction_never_writes_plaintext(db_main):
    await seed(db_main)
    before = await raw_values(db_main)
    async with db_main.create_unit_of_work() as uow:
        user = await uow.users.get_user(1001)
        assert user.username == "alice"
        await uow.settings.set_user_timezone_offset(1001, 7)
    assert await raw_values(db_main) == before
    assert await db_main.get_user_timezone_offset(1001) == 7


@pytest.mark.asyncio
async def test_reading_account_then_updating_settings_keeps_number_encrypted(db_main):
    account = await seed(db_main)
    before = await raw_values(db_main)
    async with db_main.create_unit_of_work() as uow:
        result = await uow.accounts.get_account_by_number("79000000001")
        assert result.number == "79000000001"
        changed = await uow.accounts.update_account_uuid(account.uuid, 1001, alert_bot=1)
        assert changed is not None
        assert changed.alert_bot == 1
        stored = await uow.session.get(Account, account.uuid)
        assert stored.alert_bot == 1
    assert await raw_values(db_main) == before
    assert (await db_main.get_account_by_number("79000000001")).alert_bot == 1


@pytest.mark.asyncio
async def test_backfill_is_idempotent_and_preserves_existing_ciphertext(db_main):
    await seed(db_main)
    before = await raw_values(db_main)
    result = await db_main.run_encryption_backfill()
    assert result == {"users": 0, "accounts": 0, "username_history": 0, "applications": 0, "proxy_settings": 0}
    assert await raw_values(db_main) == before


@pytest.mark.asyncio
async def test_wrong_key_rolls_back_entire_backfill(db_main, monkeypatch):
    await seed(db_main)
    async with db_main.create_unit_of_work() as uow:
        uow.session.add(User(user_id=2002, username="legacy", full_name="Legacy"))
    before = await raw_values(db_main)
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "wrong-key")
    with pytest.raises(RuntimeError, match="decrypt"):
        await db_main.run_encryption_backfill()
    assert await raw_values(db_main) == before


@pytest.mark.asyncio
async def test_bad_history_rolls_back_preceding_plaintext_backfill(db_main):
    async with db_main.create_unit_of_work() as uow:
        uow.session.add(User(user_id=1001, username="legacy", full_name="Legacy"))
        uow.session.add(UsernameHistory(user_id=1001, username="enc:v1:broken", date=1))
    before = await raw_values(db_main)
    with pytest.raises(RuntimeError, match="decrypt"):
        await db_main.run_encryption_backfill()
    assert await raw_values(db_main) == before


@pytest.mark.asyncio
async def test_startup_with_wrong_key_disposes_engine(db_main, monkeypatch):
    await seed(db_main)
    before = await raw_values(db_main)
    await db_main.close_database()
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "wrong-key")
    monkeypatch.setattr(db_main, "_ENCRYPTION_BACKFILL_DONE", False)
    with pytest.raises(RuntimeError, match="decrypt"):
        await db_main.connect_database()
    assert not db_main.is_connected()
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-encryption-key")
    await db_main.connect_database()
    assert await raw_values(db_main) == before


@pytest.mark.asyncio
async def test_database_exceptions_hide_query_parameters(db_main):
    from sqlalchemy.exc import IntegrityError

    await db_main.create_app_tg(1001, 12345, "synthetic-private-api-hash", "app")
    with pytest.raises(IntegrityError) as caught:
        await db_main.create_app_tg(1001, 12345, "synthetic-private-api-hash", "duplicate")
    assert "synthetic-private-api-hash" not in str(caught.value)


@pytest.mark.asyncio
async def test_full_name_with_storage_prefix_survives_backfill(db_main):
    await db_main.update_user(1001, "alice", "enc:v1:literal name")
    assert (await db_main.get_user(1001)).full_name == "enc:v1:literal name"
    result = await db_main.run_encryption_backfill()
    assert result == {"users": 0, "accounts": 0, "username_history": 0, "applications": 0, "proxy_settings": 0}
