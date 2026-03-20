from __future__ import annotations

from typing import Any
from uuid import UUID

import data.config as config
import data.text as constant_text
import db.models  # noqa: F401
from db.engine import ensure_database_exists, load_database_settings
from db.migrations import run_db_migrations
from db.repositories.accounts_repo import AccountsRepository
from db.repositories.settings_repo import SettingsRepository
from db.repositories.users_repo import UsersRepository
from db.models import Account, AccountHealth, DumpChatUser, HistoryUser, TelegramApp, User
from db.session import (
    close_engine,
    connect_engine,
    get_session_factory,
    is_connected,
    session_scope as _session_scope,
)
from db.unit_of_work import UnitOfWork
from utils.crypto_store import blind_index, encryption_enabled, is_encrypted


def _cfg(name: str, default: Any = None) -> Any:
    return getattr(config, name, default)


admin_id_list = list(_cfg("admin_id_list", []) or [])
db_settings = load_database_settings()


def _normalize_timezone_offset(offset: Any, default: int = 3) -> int:
    try:
        value = int(offset)
    except (TypeError, ValueError):
        value = default
    return max(-12, min(14, value))


accounts_repository = AccountsRepository(_session_scope)
settings_repository = SettingsRepository(_session_scope, admin_id_list, _normalize_timezone_offset)
users_repository = UsersRepository(_session_scope, admin_id_list)
_ENCRYPTION_BACKFILL_DONE = False


async def connect_database() -> None:
    global _ENCRYPTION_BACKFILL_DONE
    if is_connected():
        return
    if not encryption_enabled():
        raise RuntimeError("DB_ENCRYPTION_KEY is required. Set it in .env before starting the bot.")

    await ensure_database_exists(db_settings)
    await run_db_migrations(db_settings=db_settings)
    await connect_engine(db_settings.connection_string)
    if not _ENCRYPTION_BACKFILL_DONE:
        await run_encryption_backfill()
        _ENCRYPTION_BACKFILL_DONE = True


async def close_database() -> None:
    await close_engine()


def create_unit_of_work() -> UnitOfWork:
    return UnitOfWork(
        session_factory=get_session_factory(),
        admin_id_list=admin_id_list,
        normalize_timezone_offset=_normalize_timezone_offset,
    )


async def get_version_state_cache(default_state: str = constant_text.VERSION_STATE_UNKNOWN) -> tuple[str, int, str | None]:
    return await settings_repository.get_version_state_cache(default_state=default_state)


async def set_version_state_cache(
    local_version: str,
    remote_version: str | None,
    state: str,
    checked_at: int | None = None,
) -> int:
    return await settings_repository.set_version_state_cache(
        local_version=local_version,
        remote_version=remote_version,
        state=state,
        checked_at=checked_at,
    )


async def get_user(user_id: int) -> User | None:
    return await users_repository.get_user(user_id=user_id)


async def get_user_timezone_offset(user_id: int, default: int = 3) -> int:
    return await settings_repository.get_user_timezone_offset(user_id=user_id, default=default)


async def set_user_timezone_offset(user_id: int, offset: int) -> int:
    return await settings_repository.set_user_timezone_offset(user_id=user_id, offset=offset)


async def get_user_auto_update_enabled(user_id: int, default: int = 0) -> int:
    return await settings_repository.get_user_auto_update_enabled(user_id=user_id, default=default)


async def set_user_auto_update_enabled(user_id: int, enabled: int) -> int:
    return await settings_repository.set_user_auto_update_enabled(user_id=user_id, enabled=enabled)


async def get_user_update_notification_state(user_id: int) -> tuple[int, int]:
    return await settings_repository.get_user_update_notification_state(user_id=user_id)


async def set_user_update_snooze_until(user_id: int, until_ts: int) -> int:
    return await settings_repository.set_user_update_snooze_until(user_id=user_id, until_ts=until_ts)


async def set_user_update_last_notified(user_id: int, ts_value: int) -> int:
    return await settings_repository.set_user_update_last_notified(user_id=user_id, ts_value=ts_value)


async def update_user(user_id: int, username: str | None, full_name: str | None) -> None:
    return await users_repository.update_user(user_id=user_id, username=username, full_name=full_name)


async def delete_user(user_id: int) -> None:
    return await users_repository.delete_user(user_id=user_id)


async def get_admins() -> list[User]:
    return await users_repository.get_admins()


async def find_user_ids_by_username(username: str) -> list[int]:
    return await users_repository.find_user_ids_by_username(username=username)


async def get_all_users() -> list[User]:
    return await users_repository.get_all_users()


async def run_encryption_backfill() -> dict[str, int]:
    users_touched = 0
    accounts_touched = 0

    users = await get_all_users()
    for user in users:
        before_username = user.username
        before_full_name = user.full_name
        before_hash = getattr(user, "username_hash", None)
        current_idx = None
        if before_username:
            current_idx = blind_index(before_username)

        needs = (
            (before_username and (not is_encrypted(before_username) or before_hash != current_idx))
            or (before_full_name and not is_encrypted(before_full_name))
        )
        if not needs:
            continue
        await update_user(int(user.user_id), before_username, before_full_name)
        users_touched += 1

    accounts = await get_account_all(active_only=False)
    for account in accounts:
        if not account.number:
            continue
        current_idx = blind_index(account.number)
        if is_encrypted(account.number) and getattr(account, "number_hash", None) == current_idx:
            continue

        admin_id = int(account.admin_id or 0)
        if admin_id <= 0:
            continue
        await update_account_uuid(account.uuid, admin_id, number=account.number)
        accounts_touched += 1

    history_touched = await users_repository.backfill_username_history_encryption()
    return {
        "users": users_touched,
        "accounts": accounts_touched,
        "username_history": history_touched,
    }


async def get_app_tg_user_id(user_id: int, offset: int = 0) -> tuple[list[TelegramApp], int]:
    return await accounts_repository.get_app_tg_user_id(user_id=user_id, offset=offset)


async def get_app_tg_uuid(uuid: Any, user_id: int) -> TelegramApp | None:
    return await accounts_repository.get_app_tg_uuid(uuid=uuid, user_id=user_id)


async def get_app_tg_uuid_aio(uuid: Any) -> TelegramApp | None:
    return await accounts_repository.get_app_tg_uuid_aio(uuid=uuid)


async def get_accounts_count_by_app_tg_uuid(app_tg_uuid) -> int:
    return await accounts_repository.get_accounts_count_by_app_tg_uuid(app_tg_uuid=app_tg_uuid)


async def del_app_tg_uuid(uuid: Any, user_id: int) -> bool:
    return await accounts_repository.del_app_tg_uuid(uuid=uuid, user_id=user_id)


async def get_app_tg_to_params_all(user_id: int, app_id: int, api_hash: str) -> TelegramApp | None:
    return await accounts_repository.get_app_tg_to_params_all(user_id=user_id, app_id=app_id, api_hash=api_hash)


async def create_app_tg(user_id: int, app_id: int, api_hash: str, tag_name: str | None) -> None:
    return await accounts_repository.create_app_tg(user_id=user_id, app_id=app_id, api_hash=api_hash, tag_name=tag_name)


async def get_account_user_id(admin_id: int, offset: int = 0) -> tuple[list[Account], int]:
    return await accounts_repository.get_account_user_id(admin_id=admin_id, offset=offset)


async def get_account_all(active_only: bool = False) -> list[Account]:
    return await accounts_repository.get_account_all(active_only=active_only)


async def get_account_tg_to_user_id(user_id: int, admin_id: int | None = None) -> Account | None:
    return await accounts_repository.get_account_tg_to_user_id(user_id=user_id, admin_id=admin_id)


async def get_account_uuid(uuid: Any, admin_id: int) -> Account | None:
    return await accounts_repository.get_account_uuid(uuid=uuid, admin_id=admin_id)


async def del_account_uuid(uuid: Any, admin_id: int) -> bool:
    return await accounts_repository.del_account_uuid(uuid=uuid, admin_id=admin_id)


async def update_account_uuid(uuid: Any, admin_id: int, **fields: Any) -> Account | None:
    return await accounts_repository.update_account_uuid(uuid=uuid, admin_id=admin_id, **fields)


async def create_account_tg(admin_id: int, user_id: int, app_tg: Any, number: str) -> Account | None:
    return await accounts_repository.create_account_tg(admin_id=admin_id, user_id=user_id, app_tg=app_tg, number=number)


async def get_dump_chat_admin_all(admin_id: int) -> list[DumpChatUser]:
    return await accounts_repository.get_dump_chat_admin_all(admin_id=admin_id)


async def get_dump_chat_user(admin_id: int, chat_id: int) -> DumpChatUser | None:
    return await accounts_repository.get_dump_chat_user(admin_id=admin_id, chat_id=chat_id)


async def del_dump_chat_user(admin_id: int, chat_id: int) -> bool:
    return await accounts_repository.del_dump_chat_user(admin_id=admin_id, chat_id=chat_id)


async def create_dump_chat_user(admin_id: int, chat_id: int) -> bool:
    return await accounts_repository.create_dump_chat_user(admin_id=admin_id, chat_id=chat_id)


async def add_chat_history_event(
    admin_id: int,
    chat_id: int,
    action_id: int,
    account_user_id: int | None = None,
    date: int | None = None,
) -> None:
    return await accounts_repository.add_chat_history_event(
        admin_id=admin_id,
        chat_id=chat_id,
        action_id=action_id,
        account_user_id=account_user_id,
        date=date,
    )


async def get_chat_history_events(admin_id: int, chat_id: int, limit: int = 100) -> list[HistoryUser]:
    return await accounts_repository.get_chat_history_events(
        admin_id=admin_id,
        chat_id=chat_id,
        limit=limit,
    )


async def get_chat_history_events_by_chat_ids(
    admin_id: int,
    chat_ids: list[int],
    limit: int = 200,
) -> list[HistoryUser]:
    return await accounts_repository.get_chat_history_events_by_chat_ids(
        admin_id=admin_id,
        chat_ids=chat_ids,
        limit=limit,
    )


async def get_account_by_number(number: str) -> Account | None:
    return await accounts_repository.get_account_by_number(number=number)


async def delete_account_by_number(number: str) -> Account | None:
    return await accounts_repository.delete_account_by_number(number=number)


async def add_account_health_event(
    account_uuid: UUID | str,
    admin_id: int | None,
    user_id: int | None,
    status: int,
    date: int | None = None,
    reason: str | None = None,
) -> None:
    return await accounts_repository.add_account_health_event(
        account_uuid=account_uuid,
        admin_id=admin_id,
        user_id=user_id,
        status=status,
        date=date,
        reason=reason,
    )


async def get_account_health_events(account_uuid: UUID | str, since_ts: int) -> list[AccountHealth]:
    return await accounts_repository.get_account_health_events(account_uuid=account_uuid, since_ts=since_ts)


async def get_admin_health_events(admin_id: int, since_ts: int) -> list[AccountHealth]:
    return await accounts_repository.get_admin_health_events(admin_id=admin_id, since_ts=since_ts)


async def get_accounts_overview(admin_id: int) -> dict[str, int]:
    return await accounts_repository.get_accounts_overview(admin_id=admin_id)


async def get_all_health_events(since_ts: int) -> list[AccountHealth]:
    return await accounts_repository.get_all_health_events(since_ts=since_ts)


async def get_user_gemini_proxy_config(user_id: int) -> dict[str, Any]:
    return await settings_repository.get_user_gemini_proxy_config(user_id=user_id)


async def set_user_gemini_proxy(user_id: int, proxy_value: str) -> dict[str, Any]:
    return await settings_repository.set_user_gemini_proxy(user_id=user_id, proxy_value=proxy_value)


async def disable_user_gemini_proxy(user_id: int, reason: str | None = None) -> dict[str, Any]:
    return await settings_repository.disable_user_gemini_proxy(user_id=user_id, reason=reason)


async def set_user_gemini_proxy_health(user_id: int, is_ok: bool, error: str | None = None) -> dict[str, Any]:
    return await settings_repository.set_user_gemini_proxy_health(user_id=user_id, is_ok=is_ok, error=error)


async def get_latest_admin_health_event(admin_id: int) -> AccountHealth | None:
    return await settings_repository.get_latest_admin_health_event(admin_id=admin_id)
