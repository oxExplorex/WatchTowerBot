import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from db.repositories.runtime_health_repo import RuntimeHealthRepository


@pytest.mark.asyncio
async def test_samples_preserve_failures_and_separate_owners_and_old_parser_events(db_main):
    repo = RuntimeHealthRepository(db_main.get_session_factory)
    await repo.record([("bot", 0, 1, 1), ("userbot", 1001, 2, 1), ("userbot", 2002, 1, 1)], now=600)
    await repo.record([("userbot", 1001, 2, 2)], now=650)
    rows = await RuntimeHealthRepository(db_main.get_session_factory).get(1001, 0)
    assert {row.owner_id for row in rows} == {0, 1001}
    partial = next(row for row in rows if row.component == "userbot")
    assert partial.status == 2 and partial.available == 2  # Worst observation in this five-minute cell survives recovery.
    assert not await repo.get(2002, 1000)
    await repo.record([("bot", 0, 1, 1)], now=31 * 86400)
    assert len(await repo.get(1001, 0)) == 1  # Retention also removes obsolete per-owner samples.


@pytest.mark.asyncio
async def test_collection_uses_local_connection_state_without_extra_telegram_calls(db_main, offline_module):
    service = offline_module("services/runtime_health.py")
    repo = RuntimeHealthRepository(db_main.get_session_factory)
    client = SimpleNamespace(name="data/session/connected", get_me=AsyncMock())
    manager = SimpleNamespace(get_snapshot=AsyncMock(return_value=[client]), is_available=AsyncMock(return_value=True))
    polling = service.PollingHealth()
    accounts = [SimpleNamespace(admin_id=1001, number="connected", is_active=1),
                SimpleNamespace(admin_id=1001, number="failed", is_active=1),
                SimpleNamespace(admin_id=1001, number="disabled", is_active=0)]
    await service.collect_runtime_health(repo, manager, polling, accounts, now=600)
    rows = await repo.get(1001, 0)
    assert len(rows) == 1 and rows[0].component == "userbot"
    assert (rows[0].expected, rows[0].available, rows[0].status) == (2, 1, 2)
    client.get_me.assert_not_awaited()


@pytest.mark.asyncio
async def test_startup_failure_is_recorded_without_deleting_account_or_disclosing_error_values(db_main, offline_module, monkeypatch, caplog):
    await db_main.create_app_tg(1001, 12345, "synthetic", "app")
    app = (await db_main.get_app_tg_user_id(1001))[0][0]
    account = await db_main.create_account_tg(1001, 2002, app.uuid, "79000000001")
    runtime = offline_module("core/session_runtime.py")
    import sys
    monkeypatch.setitem(sys.modules, "db.main", db_main)
    monkeypatch.setattr(runtime, "start_client", AsyncMock(side_effect=sqlite3.OperationalError(
        "unable to open database file /secret/79000000001.session")))
    await runtime.start_all_clients([SimpleNamespace(name="data/session/79000000001")])
    events = await db_main.get_account_health_events(account.uuid, 0)
    assert len(events) == 1 and events[0].status == 0 and events[0].reason == "startup:sqlite_open"
    assert (await db_main.get_account_uuid(account.uuid, 1001)).is_active == 1
    assert "sqlite_open" in caplog.text and "/secret/" not in caplog.text and "79000000001" not in caplog.text
