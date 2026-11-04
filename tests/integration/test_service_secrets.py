import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import TelegramApp, User

API_HASH = "aA" * 16
PROXY = "http://synthetic_user:synthetic_password@127.0.0.1:8080"
ERROR = f"Connection failed through {PROXY}"


async def raw_values(db):
    async with db.create_unit_of_work() as uow:
        apps = list((await uow.session.execute(select(
            TelegramApp.uuid, TelegramApp.api_hash, TelegramApp.api_hash_index).order_by(TelegramApp.uuid))).all())
        users = list((await uow.session.execute(select(
            User.uuid, User.username, User.gemini_proxy, User.gemini_proxy_last_error).order_by(User.uuid))).all())
    return apps, users


@pytest.mark.asyncio
async def test_encrypted_api_hash_remains_searchable_unique_and_safe_in_unit_of_work(db_main):
    await db_main.create_app_tg(1001, 12345, API_HASH, "app")
    apps, _ = await db_main.get_app_tg_user_id(1001)
    app = apps[0]
    stored = (await raw_values(db_main))[0][0]
    assert stored.api_hash.startswith("enc:v1:") and API_HASH not in stored.api_hash
    assert stored.api_hash_index and stored.api_hash_index != API_HASH
    assert app.api_hash == API_HASH
    assert (await db_main.get_app_tg_uuid(app.uuid, 1001)).api_hash == API_HASH
    assert (await db_main.get_app_tg_uuid_aio(app.uuid)).api_hash == API_HASH
    assert (await db_main.get_app_tg_to_params_all(1001, 12345, API_HASH)).uuid == app.uuid
    assert await db_main.get_app_tg_to_params_all(1001, 12345, API_HASH.lower()) is None
    assert await db_main.get_app_tg_uuid(app.uuid, 2002) is None
    with pytest.raises(IntegrityError):
        await db_main.create_app_tg(1001, 12345, API_HASH, "duplicate")
    async with db_main.create_unit_of_work() as uow:
        hydrated = await uow.accounts.get_app_tg_uuid(app.uuid, 1001)
        assert hydrated.api_hash == API_HASH
        await uow.settings.set_user_timezone_offset(1001, 7)
    assert (await raw_values(db_main))[0][0] == stored
    await db_main.create_app_tg(2002, 12345, API_HASH, "another-owner")
    indexes = [row.api_hash_index for row in (await raw_values(db_main))[0]]
    assert len(set(indexes)) == 2


@pytest.mark.asyncio
async def test_proxy_and_diagnostics_are_encrypted_without_mutating_hydrated_models(db_main):
    async with db_main.create_unit_of_work() as uow:
        settings = await uow.settings.set_user_gemini_proxy(1001, PROXY)
        assert settings["proxy"] == PROXY
        failed = await uow.settings.set_user_gemini_proxy_health(1001, False, ERROR)
        assert failed["last_error"] == ERROR
    before = await raw_values(db_main)
    stored = before[1][0]
    assert stored.gemini_proxy.startswith("enc:v1:")
    assert stored.gemini_proxy_last_error.startswith("enc:v1:")
    assert "synthetic_password" not in str(stored)
    async with db_main.create_unit_of_work() as uow:
        user = await uow.users.get_user(1001)
        assert user.gemini_proxy == PROXY and user.gemini_proxy_last_error == ERROR
        assert (await uow.settings.get_user_gemini_proxy_config(1001))["proxy"] == PROXY
        await uow.settings.set_user_timezone_offset(1001, 5)
    assert await raw_values(db_main) == before
    disabled = await db_main.disable_user_gemini_proxy(1001, ERROR)
    assert disabled["enabled"] == 0 and disabled["last_error"] == ERROR
    successful = await db_main.set_user_gemini_proxy_health(1001, True)
    assert successful["last_error"] is None
    assert (await raw_values(db_main))[1][0].gemini_proxy_last_error is None


@pytest.mark.asyncio
async def test_legacy_service_fields_convert_once_and_legacy_lookup_still_works(db_main):
    async with db_main.create_unit_of_work() as uow:
        uow.session.add(TelegramApp(user_id=1001, app_id=12345, api_hash=API_HASH))
        uow.session.add(User(user_id=1001, gemini_proxy=PROXY, gemini_proxy_last_error=ERROR))
    assert (await db_main.get_app_tg_to_params_all(1001, 12345, API_HASH)).api_hash == API_HASH
    assert (await db_main.get_user_gemini_proxy_config(1001))["proxy"] == PROXY
    counts = await db_main.run_encryption_backfill()
    assert counts["applications"] == 1 and counts["proxy_settings"] == 1
    stored = await raw_values(db_main)
    assert stored[0][0].api_hash.startswith("enc:v1:") and stored[0][0].api_hash_index
    assert stored[1][0].gemini_proxy.startswith("enc:v1:")
    assert stored[1][0].gemini_proxy_last_error.startswith("enc:v1:")
    assert all(value == 0 for value in (await db_main.run_encryption_backfill()).values())
    assert await raw_values(db_main) == stored


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["api_hash", "gemini_proxy", "gemini_proxy_last_error"])
async def test_startup_rejects_wrong_key_even_without_encrypted_names(db_main, monkeypatch, field):
    if field == "api_hash":
        await db_main.create_app_tg(1001, 12345, API_HASH, "app")
    elif field == "gemini_proxy":
        await db_main.set_user_gemini_proxy(1001, PROXY)
    else:
        await db_main.set_user_gemini_proxy_health(1001, False, ERROR)
    before = await raw_values(db_main)
    await db_main.close_database()
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "wrong-key")
    monkeypatch.setattr(db_main, "_ENCRYPTION_BACKFILL_DONE", False)
    with pytest.raises(RuntimeError, match="decrypt") as caught:
        await db_main.connect_database()
    assert not db_main.is_connected()
    assert API_HASH not in str(caught.value) and PROXY not in str(caught.value)
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-encryption-key")
    await db_main.connect_database()
    assert await raw_values(db_main) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["app", "proxy"])
async def test_corrupt_service_secret_rolls_back_every_preceding_backfill(db_main, broken):
    async with db_main.create_unit_of_work() as uow:
        uow.session.add(TelegramApp(user_id=1001, app_id=12345,
                                   api_hash="enc:v1:broken" if broken == "app" else API_HASH))
        uow.session.add(User(user_id=1001, username="legacy", gemini_proxy=PROXY,
                             gemini_proxy_last_error="enc:v1:broken" if broken == "proxy" else ERROR))
    before = await raw_values(db_main)
    with pytest.raises(RuntimeError, match="decrypt"):
        await db_main.run_encryption_backfill()
    assert await raw_values(db_main) == before


@pytest.mark.asyncio
async def test_missing_key_never_saves_new_service_secrets_as_plaintext(db_main, monkeypatch):
    monkeypatch.delenv("DB_ENCRYPTION_KEY")
    with pytest.raises(RuntimeError):
        await db_main.create_app_tg(1001, 12345, API_HASH, "app")
    with pytest.raises(RuntimeError):
        await db_main.set_user_gemini_proxy(1001, PROXY)
    with pytest.raises(RuntimeError):
        await db_main.set_user_gemini_proxy_health(1001, False, ERROR)
    assert await raw_values(db_main) == ([], [])


@pytest.mark.asyncio
async def test_runtime_receives_decrypted_credentials_without_live_telegram_or_gemini(db_main, offline_module, monkeypatch):
    await db_main.create_app_tg(1001, 12345, API_HASH, "app")
    apps, _ = await db_main.get_app_tg_user_id(1001)
    await db_main.create_account_tg(1001, 456, apps[0].uuid, "79000000001")
    await db_main.set_user_gemini_proxy(1001, PROXY)
    runtime = offline_module("loader.py")
    monkeypatch.setattr(runtime, "get_active_accounts_with_apps", db_main.get_active_accounts_with_apps)
    constructor = Mock(return_value=SimpleNamespace(name="offline"))
    monkeypatch.setattr(runtime, "Client", constructor)
    try:
        assert len(await runtime._get_apps_user()) == 1
        assert constructor.call_args.kwargs["api_hash"] == API_HASH
    finally:
        await runtime.bot.session.close()
    loader = ModuleType("loader")
    loader.gemini_system_instruction = "offline"
    monkeypatch.setitem(sys.modules, "loader", loader)
    gemini = offline_module("handlers_app/user/gemini_handler.py")
    monkeypatch.setattr(gemini, "GEMINI_KEY", "offline")
    monkeypatch.setattr(gemini, "get_user_gemini_proxy_config", db_main.get_user_gemini_proxy_config)
    monkeypatch.setattr(gemini, "set_user_gemini_proxy_health", db_main.set_user_gemini_proxy_health)
    request = AsyncMock(return_value="offline answer")
    monkeypatch.setattr(gemini, "_request_gemini", request)
    assert await gemini._generate_with_gemini(1001, []) == "offline answer"
    assert request.await_args.kwargs["proxy_url"] == PROXY
