from __future__ import annotations

import asyncio
import os
import sqlite3

from alembic import command
from alembic.script import ScriptDirectory
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("has_revision", [True, False])
async def test_existing_database_upgrades_and_preserves_accounts(database_module, monkeypatch, has_revision):
    from db import migrations
    from db.engine import load_database_settings

    settings = load_database_settings()
    assert settings.normalized_engine == "sqlite+aiosqlite"
    config = migrations._build_alembic_config(settings.connection_string)
    await asyncio.to_thread(command.upgrade, config, "20260308_01")
    path = os.environ["BOT_DB_PATH"]
    app_uuid = "1" * 32
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO user_db (uuid,user_id,username,full_name,timezone_offset,"
            "auto_update_enabled,gemini_proxy_enabled,gemini_proxy_status,gemini_proxy,gemini_proxy_last_error) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("2" * 32, 1001, "legacy_user", "Legacy User", 7, 1, 1, 0,
             "http://legacy_user:legacy_password@127.0.0.1:8080", "legacy proxy error"),
        )
        connection.execute(
            "INSERT INTO app_tg_db (uuid,user_id,app_id,api_hash,tag_name) VALUES (?,?,?,?,?)",
            (app_uuid, 1001, 12345, "synthetic_api_hash", "old-app"),
        )
        connection.execute(
            "INSERT INTO apps_db (uuid,admin_id,user_id,app_tg,number,alert_black_list,"
            "alert_black_list_id,alert_del_chat,alert_del_chat_id,alert_new_chat,alert_new_chat_id,"
            "alert_bot,alert_spoiler_media,is_active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("3" * 32, 1001, 9001, app_uuid, "79000000001", 0, 0, 0, 0, 0, 0, 0, 0, 1),
        )
        connection.execute(
            "INSERT INTO account_health_db (uuid,account_uuid,admin_id,user_id,status,date,reason) "
            "VALUES (?,?,?,?,?,?,?)",
            ("4" * 32, "3" * 32, 1001, 9001, 1, 1, "legacy-event"),
        )
        if not has_revision:
            connection.execute("DROP TABLE alembic_version")

    await database_module.connect_database()
    account = await database_module.get_account_by_number("79000000001")
    assert account is not None
    assert account.user_id == 9001
    user = await database_module.get_user(1001)
    assert user.username == "legacy_user"
    assert user.auto_update_enabled == 1
    assert user.timezone_offset == 7
    apps, count = await database_module.get_app_tg_user_id(1001)
    assert count == 1
    assert apps[0].api_hash == "synthetic_api_hash"
    assert (await database_module.get_app_tg_uuid_aio(apps[0].uuid)).api_hash == "synthetic_api_hash"
    proxy = await database_module.get_user_gemini_proxy_config(1001)
    assert proxy["proxy"] == "http://legacy_user:legacy_password@127.0.0.1:8080"
    assert proxy["last_error"] == "legacy proxy error" and proxy["enabled"] == 1
    await database_module.close_database()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == ScriptDirectory.from_config(config).get_current_head()
        assert connection.execute("SELECT COUNT(*) FROM apps_db").fetchone()[0] == 1
        assert connection.execute("SELECT number FROM apps_db").fetchone()[0].startswith("enc:v1:")
        assert connection.execute("SELECT api_hash FROM app_tg_db").fetchone()[0].startswith("enc:v1:")
        assert connection.execute("SELECT api_hash_index FROM app_tg_db").fetchone()[0]
        assert all(value.startswith("enc:v1:") for value in connection.execute(
            "SELECT gemini_proxy,gemini_proxy_last_error FROM user_db").fetchone())
        assert connection.execute("SELECT account_uuid,reason FROM account_health_db").fetchall() == [
            ("3" * 32, "legacy-event")
        ]

    # A fresh process runs the migration check again; no duplicate rows or changes.
    monkeypatch.setattr(migrations, "_MIGRATIONS_DONE", False)
    await database_module.connect_database()
    repeated = await database_module.get_account_by_number("79000000001")
    assert repeated.uuid == account.uuid
