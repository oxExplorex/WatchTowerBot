from types import SimpleNamespace
from uuid import uuid4

import pytest

from data.texts import account_ownership as text
from keyboards.inline.account_manage.account_edit_inline import account_edit_admin_inline
from keyboards.inline.account_ownership import delete_keyboard


@pytest.mark.asyncio
async def test_account_editor_has_two_distinct_deletion_modes():
    account = SimpleNamespace(uuid=uuid4(), is_active=0, alert_new_chat=1,
        alert_del_chat=1, alert_bot=0, alert_spoiler_media=1)
    keyboard = await account_edit_admin_inline(account)
    buttons = {button.callback_data: button.text for row in keyboard.inline_keyboard for button in row}
    assert buttons[f"acc:del:{account.uuid}"] == text.BTN_DISCONNECT
    assert buttons[f"acc:purge:{account.uuid}"] == text.BTN_DELETE_FULL
    assert all(len(value.encode("utf-8")) <= 64 for value in buttons)


@pytest.mark.parametrize("kind,expected", [("delete", text.BTN_CONFIRM_DELETE), ("delete_full", text.BTN_DELETE_FULL)])
def test_confirmation_matches_the_persisted_mode_and_has_only_cancel(kind, expected):
    keyboard = delete_keyboard(SimpleNamespace(uuid=uuid4(), kind=kind))
    assert [button.text for row in keyboard.inline_keyboard for button in row] == [expected, text.BTN_CANCEL]
