from __future__ import annotations

import pytest
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
