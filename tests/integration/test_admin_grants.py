import asyncio
import sqlite3

from alembic import command
import pytest
import pytest_asyncio
from sqlalchemy import select

from db.admin_models import AdminGrant
from db.models import User
from db.repositories.admins_repo import AdminsRepository


@pytest_asyncio.fixture
async def admins(db_main, monkeypatch):
    repository = AdminsRepository(db_main.get_session_factory, [1001])
    monkeypatch.setattr(db_main, "admins_repository", repository)
    monkeypatch.setattr(db_main.users_repository, "_admin_id_list", {1001})
    return repository


@pytest.mark.asyncio
async def test_grants_survive_contact_refresh_restart_and_revocation(db_main, admins):
    assert await admins.is_admin(1001)
    assert await admins.grant(1001, 2002)
    assert 2002 in {user.user_id for user in await db_main.get_admins()}
    await db_main.update_user(2002, "first", "Первое имя")
    await db_main.update_user(2002, "second", "Второе имя")
    assert await AdminsRepository(db_main.get_session_factory, [1001]).is_admin(2002)
    assert await admins.revoke(1001, 2002)
    await db_main.update_user(2002, "third", "Третье имя")
    assert not await admins.is_admin(2002)
    assert 2002 not in {user.user_id for user in await db_main.get_admins()}
    async with db_main.create_unit_of_work() as uow:
        uow.session.add(User(user_id=3003, roles="admin"))
    assert not await admins.is_admin(3003)  # Obsolete profile role is not authority.


@pytest.mark.asyncio
async def test_mutations_recheck_actor_and_protect_configured_and_self(admins):
    with pytest.raises(PermissionError):
        await admins.grant(9999, 2002)
    await admins.grant(1001, 2002)
    await admins.grant(2002, 3003)
    with pytest.raises(ValueError):
        await admins.revoke(2002, 1001)
    with pytest.raises(ValueError):
        await admins.revoke(2002, 2002)
    await admins.revoke(1001, 2002)
    with pytest.raises(PermissionError):
        await admins.grant(2002, 4004)
    with pytest.raises(PermissionError):
        await admins.revoke(2002, 3003)
    assert await admins.get_ids() == {1001, 3003}


@pytest.mark.asyncio
async def test_parallel_repeated_grants_are_idempotent(db_main, admins):
    results = await asyncio.gather(*(admins.grant(1001, 2002) for _ in range(5)))
    assert sum(results) == 1
    async with db_main.create_unit_of_work() as uow:
        grants = list(await uow.session.scalars(select(AdminGrant)))
    assert len(grants) == 1 and grants[0].granted_by == 1001


@pytest.mark.asyncio
async def test_administrator_status_does_not_expose_other_owners_objects(db_main, admins):
    await admins.grant(1001, 2002)
    await db_main.create_app_tg(1001, 12345, "synthetic", "private-app")
    applications, _ = await db_main.get_app_tg_user_id(1001)
    app = applications[0]
    account = await db_main.create_account_tg(1001, 456, app.uuid, "79000000001")
    assert not await admins.is_admin(456)  # An observed account does not grant access.
    assert await db_main.get_app_tg_uuid(app.uuid, 2002) is None
    assert not await db_main.del_app_tg_uuid(app.uuid, 2002)
    assert await db_main.get_account_uuid(account.uuid, 2002) is None
    assert await db_main.update_account_uuid(account.uuid, 2002, is_active=0) is None
    assert not await db_main.del_account_uuid(account.uuid, 2002)
    assert (await db_main.get_account_uuid(account.uuid, 1001)).is_active


@pytest.mark.asyncio
async def test_upgrade_preserves_legacy_grants_without_promoting_configured_ids(database_module, monkeypatch):
    from db import migrations
    from db.engine import load_database_settings

    settings = load_database_settings()
    config = migrations._build_alembic_config(settings.connection_string)
    await asyncio.to_thread(command.upgrade, config, "20261103_03")
    import os
    with sqlite3.connect(os.environ["BOT_DB_PATH"]) as connection:
        for user_id, role in [(1001, "admin"), (2002, "admin"), (3003, None)]:
            connection.execute(
                "INSERT INTO user_db (uuid,user_id,roles,timezone_offset,auto_update_enabled,"
                "gemini_proxy_enabled,gemini_proxy_status) VALUES (?,?,?,?,?,?,?)",
                (f"{user_id:032x}", user_id, role, 3, 0, 0, 0))
    monkeypatch.setattr(database_module, "admin_id_list", [1001])
    monkeypatch.setattr(database_module, "admins_repository", AdminsRepository(database_module.get_session_factory, [1001]))
    await database_module.connect_database()
    assert await database_module.get_admin_ids() == {1001, 2002}
    assert {row.user_id for row in await database_module.get_admin_grants()} == {2002}
    assert (await database_module.get_admin_grants())[0].granted_by is None
