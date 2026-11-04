"""Limited self-service is not an administrator grant."""
from db.main import is_admin
from db.repositories.account_operations_repo import AccountOperationsRepository
from db.session import get_session_factory


async def has_limited_access(user_id):
    return await AccountOperationsRepository(get_session_factory).has_limited_access(user_id)


async def can_create_profile(user_id):
    if await is_admin(user_id):
        return True
    return bool(await AccountOperationsRepository(get_session_factory).self_accounts(user_id))


async def can_use_secret(user_id):
    return await is_admin(user_id) or await has_limited_access(user_id)
