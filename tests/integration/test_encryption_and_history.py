from __future__ import annotations

from sqlalchemy import select

import pytest

from db.models import Account, User, UsernameHistory
from utils.crypto_store import blind_index


@pytest.mark.asyncio
async def test_account_number_encrypted_and_searchable(db_main):
    await db_main.create_app_tg(user_id=1001, app_id=12345, api_hash="hash_a", tag_name="test-app")
    apps, _ = await db_main.get_app_tg_user_id(user_id=1001)
    number = "79000000001"
    account = await db_main.create_account_tg(
        admin_id=5001,
        user_id=9001,
        app_tg=apps[0].uuid,
        number=number,
    )
    assert account is not None

    raw_account = None
    async with db_main.create_unit_of_work() as uow:
        raw_account = (await uow.session.execute(select(Account).where(Account.uuid == account.uuid))).scalars().first()
    assert raw_account is not None
    assert raw_account.number is not None
    assert str(raw_account.number).startswith("enc:v1:")
    assert raw_account.number_hash == blind_index(number)

    found = await db_main.get_account_by_number(number)
    assert found is not None
    assert found.number == number


@pytest.mark.asyncio
async def test_delete_account_keeps_dump_and_history(db_main):
    await db_main.create_app_tg(user_id=1002, app_id=12346, api_hash="hash_b", tag_name="test-app")
    apps, _ = await db_main.get_app_tg_user_id(user_id=1002)
    number = "79000000002"
    account = await db_main.create_account_tg(
        admin_id=5002,
        user_id=9002,
        app_tg=apps[0].uuid,
        number=number,
    )
    assert account is not None

    await db_main.create_dump_chat_user(admin_id=9002, chat_id=777001)
    await db_main.add_chat_history_event(
        admin_id=5002,
        chat_id=777001,
        action_id=1,
        account_user_id=9002,
    )

    deleted = await db_main.delete_account_by_number(number)
    assert deleted is not None

    dump_entry = await db_main.get_dump_chat_user(admin_id=9002, chat_id=777001)
    assert dump_entry is not None
    history = await db_main.get_chat_history_events(admin_id=5002, chat_id=777001, limit=20)
    assert len(history) >= 1


@pytest.mark.asyncio
async def test_update_user_encrypts_and_username_lookup(db_main):
    await db_main.update_user(user_id=321001, username="TestUser", full_name="Test User")
    user = await db_main.get_user(321001)
    assert user is not None
    assert user.username == "TestUser"
    assert user.full_name == "Test User"

    async with db_main.create_unit_of_work() as uow:
        raw_user = (await uow.session.execute(select(User).where(User.user_id == 321001))).scalars().first()
        assert raw_user is not None
        assert raw_user.username is not None and str(raw_user.username).startswith("enc:v1:")
        assert raw_user.full_name is not None and str(raw_user.full_name).startswith("enc:v1:")
        assert raw_user.username_hash == blind_index("TestUser")

    found_ids = await db_main.find_user_ids_by_username("@testuser")
    assert 321001 in found_ids


@pytest.mark.asyncio
async def test_username_history_deduplicated_by_hash(db_main):
    uid = 654321
    await db_main.update_user(uid, "alpha_name", "Alpha")
    await db_main.update_user(uid, "beta_name", "Alpha")
    await db_main.update_user(uid, "alpha_name", "Alpha")

    async with db_main.create_unit_of_work() as uow:
        rows = (
            await uow.session.execute(
                select(UsernameHistory).where(UsernameHistory.user_id == uid)
            )
        ).scalars().all()

    alpha_hash = blind_index("alpha_name")
    beta_hash = blind_index("beta_name")
    alpha_count = sum(1 for x in rows if x.username_hash == alpha_hash)
    beta_count = sum(1 for x in rows if x.username_hash == beta_hash)
    assert alpha_count == 1
    assert beta_count == 1


@pytest.mark.asyncio
async def test_run_encryption_backfill_encrypts_plaintext_rows(db_main):
    async with db_main.create_unit_of_work() as uow:
        uow.session.add(
            User(
                user_id=700001,
                username="legacy_user",
                full_name="Legacy User",
                roles=None,
                timezone_offset=3,
                auto_update_enabled=0,
                gemini_proxy_enabled=0,
                gemini_proxy_status=0,
            )
        )
    await db_main.create_app_tg(user_id=700002, app_id=45555, api_hash="hash_c", tag_name="legacy")
    apps, _ = await db_main.get_app_tg_user_id(user_id=700002)
    account = await db_main.create_account_tg(
        admin_id=800002,
        user_id=700002,
        app_tg=apps[0].uuid,
        number="79000000999",
    )
    assert account is not None

    # Force a legacy-like plaintext state for account number.
    async with db_main.create_unit_of_work() as uow:
        raw_account = (await uow.session.execute(select(Account).where(Account.uuid == account.uuid))).scalars().first()
        raw_account.number = "79000000999"
        raw_account.number_hash = None

    result = await db_main.run_encryption_backfill()
    assert result["users"] >= 1
    assert result["accounts"] >= 1

    async with db_main.create_unit_of_work() as uow:
        user_row = (await uow.session.execute(select(User).where(User.user_id == 700001))).scalars().first()
        account_row = (await uow.session.execute(select(Account).where(Account.uuid == account.uuid))).scalars().first()
    assert user_row is not None and str(user_row.username).startswith("enc:v1:")
    assert account_row is not None and str(account_row.number).startswith("enc:v1:")
    assert account_row.number_hash == blind_index("79000000999")
