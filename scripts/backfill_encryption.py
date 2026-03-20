from __future__ import annotations

import asyncio

from db.main import (
    connect_database,
    close_database,
    get_account_all,
    get_all_users,
    update_account_uuid,
    update_user,
)
from utils.crypto_store import encryption_enabled


async def main() -> None:
    if not encryption_enabled():
        raise RuntimeError("DB_ENCRYPTION_KEY is empty. Set it in environment/.env before backfill.")

    await connect_database()
    try:
        users = await get_all_users()
        for user in users:
            await update_user(int(user.user_id), user.username, user.full_name)

        accounts = await get_account_all(active_only=False)
        for account in accounts:
            if account.number:
                await update_account_uuid(account.uuid, int(account.admin_id or 0), number=account.number)
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
