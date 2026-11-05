"""Control-panel access requires an explicit administrator grant."""
from db.main import is_admin


async def can_create_profile(user_id):
    return await is_admin(user_id)


async def can_use_secret(user_id):
    return await is_admin(user_id)
