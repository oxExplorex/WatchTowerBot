import sys
import types
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["tracked", "business-only-admin", "unknown", "disabled-account"])
async def test_business_archive_resolves_only_authorized_creators(monkeypatch, offline_module, mode):
    loader = types.ModuleType("loader")
    loader.bot = types.SimpleNamespace(get_business_connection=AsyncMock(return_value=
        types.SimpleNamespace(user=types.SimpleNamespace(id=456), is_enabled=True)))
    monkeypatch.setitem(sys.modules, "loader", loader)
    module = offline_module("services/business_messages.py")
    account = types.SimpleNamespace(admin_id=123, user_id=456, is_active=mode == "tracked",
                                    alert_new_chat=1, alert_bot=0)
    accounts = [account] if mode in {"tracked", "disabled-account"} else []
    monkeypatch.setattr(module, "get_accounts_for_user_id", AsyncMock(return_value=accounts))
    monkeypatch.setattr(module, "get_admin_ids", AsyncMock(return_value={456} if mode in {"business-only-admin", "disabled-account"} else set()))
    contexts = await module.business_contexts("offline")
    assert [context.owner_id for context in contexts] == (
        [123] if mode == "tracked" else [456] if mode == "business-only-admin" else [])
