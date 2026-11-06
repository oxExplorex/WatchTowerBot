import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "no_app"])
async def test_dump_worker_reports_sending_and_completion_or_failure(offline_module, monkeypatch, tmp_path, outcome):
    module = offline_module("handlers/admin/backups.py")
    monkeypatch.setattr(sys.modules["db.main"], "get_app_tg_user_id", AsyncMock(
        return_value=([] if outcome == "no_app" else [SimpleNamespace()], 1)))
    monkeypatch.setattr(module.uploads, "BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(module, "create_chat_dump", AsyncMock(return_value=(tmp_path / "archive.zip",
        dict(messages=1, revisions=2, media=0, pending=0))))
    monkeypatch.setattr(module, "send_chat_dump", AsyncMock(side_effect=RuntimeError() if outcome == "error" else None))
    monkeypatch.setattr(module, "chat_history_status", AsyncMock(return_value=""))
    monkeypatch.setattr(module, "_notice", AsyncMock())
    progress = AsyncMock()
    module._busy.add(123)
    await module._dump(SimpleNamespace(), 123, 456, 789, progress=progress)
    assert 123 not in module._busy
    assert progress.await_args.kwargs == {"done": True}
    assert progress.await_args.args[0] == (
        module.text.DUMP_DONE.format(chat_id=789) if outcome == "success" else
        module.text.DUMP_FAILED if outcome == "error" else module.text.DUMP_NEEDS_APP)
    if outcome != "no_app":
        assert "Отправляю ZIP" in progress.await_args_list[0].args[0]
