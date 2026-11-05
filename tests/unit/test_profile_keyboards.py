from types import SimpleNamespace
from uuid import UUID

import pytest

from keyboards.inline.account_manage.account_menu_inline import account_tg_admin_inline
from keyboards.inline.apps_manager.apps_menu_inline import apps_tg_admin_inline


@pytest.mark.asyncio
async def test_profile_keyboards_render_loaded_data_and_keep_existing_callbacks():
    identity = UUID("11111111-1111-1111-1111-111111111111")
    account = SimpleNamespace(uuid=identity, user_id=123, is_active=1)
    account_keyboard = await account_tg_admin_inline([account], 1, 2, names={123: "Owner"})
    button = next(button for row in account_keyboard.inline_keyboard for button in row
                  if button.callback_data == f"acc:e:{identity}")
    assert "Owner" in button.text and button.callback_data == f"acc:e:{identity}"
    app = SimpleNamespace(uuid=identity, app_id=12345, tag_name="App")
    app_keyboard = await apps_tg_admin_inline([app], 1, 2, linked_counts={identity: 3})
    callbacks = [button.callback_data for row in app_keyboard.inline_keyboard for button in row]
    assert f"account_admin_menu_add:{identity}" in callbacks
    assert f"apps_admin_menu_delete:{identity}" in callbacks
