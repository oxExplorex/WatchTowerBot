from __future__ import annotations

import pytest
from sqlalchemy import inspect


@pytest.mark.asyncio
async def test_account_deletion_preserves_health_history_with_foreign_keys(db_main):
    from db.session import get_engine

    async with get_engine().connect() as connection:
        if connection.dialect.name == "sqlite":
            await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar() == 1

    await db_main.create_app_tg(1001, 12345, "synthetic", "app")
    apps, _ = await db_main.get_app_tg_user_id(1001)
    account = await db_main.create_account_tg(1001, 9001, apps[0].uuid, "79000000001")
    await db_main.add_account_health_event(account.uuid, 1001, 9001, 1, 1, "working")
    deleted = await db_main.delete_account_by_number("79000000001")
    assert deleted.uuid == account.uuid
    await db_main.add_account_health_event(account.uuid, 1001, 9001, 0, 2, "removed")
    events = await db_main.get_account_health_events(account.uuid, 0)
    assert {event.reason for event in events} == {"working", "removed"}
    assert await db_main.get_account_by_number("79000000001") is None

    async with get_engine().connect() as connection:
        references = await connection.run_sync(lambda sync: inspect(sync).get_foreign_keys("apps_db"))
        assert any(fk["referred_table"] == "app_tg_db" for fk in references)
