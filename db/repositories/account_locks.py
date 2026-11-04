"""One lock order for account registration, ingestion and ownership changes."""
import hashlib

from sqlalchemy import BigInteger, func, literal, select, update

from db.models import Account


class AccountAlreadyConnected(ValueError):
    pass


async def lock_account(session, account_user_id: int):
    if session.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(hashlib.sha256(f"account:{account_user_id}".encode()).digest()[:8], "big", signed=True)
        await session.execute(select(func.pg_advisory_xact_lock(literal(key, type_=BigInteger))))
    else:
        await session.execute(update(Account).where(Account.user_id == account_user_id).values(user_id=account_user_id))


async def unique_account(session, account_user_id: int):
    rows = list((await session.scalars(select(Account).where(Account.user_id == account_user_id)
                                     .execution_options(populate_existing=True))).all())
    if len(rows) > 1:
        raise AccountAlreadyConnected("Multiple legacy account owners require explicit resolution")
    return rows[0] if rows else None
