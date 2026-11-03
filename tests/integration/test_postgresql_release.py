import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID
import zipfile

from alembic import command
from alembic.script import ScriptDirectory
import asyncpg
import pytest
from sqlalchemy import text


pytestmark = pytest.mark.asyncio


async def connection(db):
    settings = db.db_settings
    assert settings.host == "127.0.0.1" and settings.name.startswith("wt_test_") and settings.port != 5432
    return await asyncpg.connect(host=settings.host, port=settings.port, user=settings.user,
                                 password=settings.password, database=settings.name)


@pytest.mark.parametrize("has_revision", [True, False])
async def test_postgresql_legacy_schema_upgrade_preserves_data(database_module, postgres_cluster, monkeypatch, has_revision):
    if postgres_cluster is None:
        pytest.skip("Requires --database-backend=postgresql (disposable local server)")
    from db import migrations

    db = database_module
    config = migrations._build_alembic_config(db.db_settings.connection_string)
    await asyncio.to_thread(command.upgrade, config, "20260308_01")
    conn = await connection(db)
    try:
        await conn.execute("INSERT INTO user_db (uuid,user_id,username,full_name,roles,timezone_offset,auto_update_enabled,"
                           "gemini_proxy_enabled,gemini_proxy_status) VALUES ($1,1001,'legacy_user','Legacy User','admin',7,1,0,0)", UUID("2" * 32))
        await conn.execute("INSERT INTO app_tg_db (uuid,user_id,app_id,api_hash,tag_name) VALUES ($1,1001,12345,'legacy_hash','old-app')", UUID("1" * 32))
        await conn.execute("INSERT INTO apps_db (uuid,admin_id,user_id,app_tg,number,alert_black_list,alert_black_list_id,"
                           "alert_del_chat,alert_del_chat_id,alert_new_chat,alert_new_chat_id,alert_bot,alert_spoiler_media,is_active) "
                           "VALUES ($1,1001,9001,$2,'79000000001',0,0,0,0,0,0,0,0,1)", UUID("3" * 32), UUID("1" * 32))
        await conn.execute("INSERT INTO account_health_db (uuid,account_uuid,admin_id,user_id,status,date,reason) "
                           "VALUES ($1,$2,1001,9001,1,1,'legacy-event')", UUID("4" * 32), UUID("3" * 32))
        if not has_revision:
            await conn.execute("DROP TABLE alembic_version")
    finally:
        await conn.close()
    await db.connect_database()
    account = await db.get_account_by_number("79000000001")
    assert account.user_id == 9001
    user = await db.get_user(1001)
    assert user.username == "legacy_user" and user.timezone_offset == 7
    assert await db.is_admin(1001)
    apps, count = await db.get_app_tg_user_id(1001)
    assert count == 1 and apps[0].api_hash == "legacy_hash"
    async with db.get_session_factory()() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()
        assert (await session.scalar(text("SELECT api_hash FROM app_tg_db"))).startswith("enc:v1:")
        assert await session.scalar(text("SELECT reason FROM account_health_db")) == "legacy-event"
    await db.close_database()
    monkeypatch.setattr(migrations, "_MIGRATIONS_DONE", False)
    await db.connect_database()
    assert (await db.get_account_by_number("79000000001")).uuid == account.uuid


async def test_release_archive_update_and_real_process_crash_resume(database_module, postgres_cluster, tmp_path):
    if postgres_cluster is None:
        pytest.skip("Requires --database-backend=postgresql (disposable local server)")
    from scripts.update_bot import _safe_extract_repo

    root = Path(__file__).resolve().parents[2]
    installation = tmp_path / "installation"
    installation.mkdir()
    (installation / "main.py").write_text("# synthetic old version\n", encoding="utf-8")
    protected = [".env", "data/session/offline.session", ".local-notes/private.md", "data/media/marker"]
    for name in protected:
        target = installation / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic-local-data")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for directory in ("db", "core", "utils", "services", "migrations", "data"):
            for source in (root / directory).rglob("*.py"):
                relative = source.relative_to(root).as_posix()
                if relative == "data/config.py":
                    continue
                archive.writestr("release/" + relative, source.read_bytes())
        archive.writestr("release/alembic.ini", (root / "alembic.ini").read_bytes())
        archive.writestr("release/main.py", b"# synthetic updated entrypoint\n")
        for name in protected:
            archive.writestr("release/" + name, b"must-not-overwrite")
    assert _safe_extract_repo(output.getvalue(), installation) > 0
    assert all((installation / name).read_bytes() == b"synthetic-local-data" for name in protected)
    db = database_module
    marker = tmp_path / "crash-marker"
    media_root = installation / "data/media"

    async def run(phase, expected_code=0):
        result = await asyncio.to_thread(subprocess.run, [sys.executable, "-X", "utf8", str(root / "tests/release_archive_probe.py"),
            phase, str(installation), str(db.db_settings.port), db.db_settings.name, str(media_root), str(marker)],
            cwd=installation, capture_output=True, text=True, encoding="utf-8", timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == expected_code, (result.stdout + result.stderr)[-6000:]
        return json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else None

    assert (await run("seed"))["seeded"] == 7
    await run("abort", expected_code=23)
    assert marker.read_bytes() == b"interrupted-before-database-commit"
    conn = await connection(db)
    try:
        assert await conn.fetchval("SELECT migrated_revisions FROM owner_archive_key WHERE owner_id=123") == 0
        assert await conn.fetchval("SELECT count(*) FROM message_revision WHERE encryption_version=1") == 7
    finally:
        await conn.close()
    resumed = await run("resume")
    assert resumed == {"personal_revisions": 7, "other_owner_legacy": 1, "state": "complete", "migrated": 6, "files": 1}
    assert await run("verify") == resumed
    assert all((installation / name).read_bytes() == b"synthetic-local-data" for name in protected)
