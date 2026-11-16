import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "no_app", "no_app_large", "all"])
async def test_dump_worker_reports_sending_and_completion_or_failure(offline_module, monkeypatch, tmp_path, outcome):
    module = offline_module("handlers/admin/backups.py")
    monkeypatch.setattr(sys.modules["db.main"], "get_app_tg_user_id", AsyncMock(
        return_value=([] if outcome.startswith("no_app") else [SimpleNamespace()], 1)))
    (tmp_path / "archive.zip").write_bytes(b"synthetic zip")
    if outcome == "no_app_large":
        monkeypatch.setattr(module, "BOT_API_ZIP_SIZE", 1)
    monkeypatch.setattr(module.uploads, "BACKUP_ROOT", tmp_path)
    monkeypatch.setattr(module, "create_chat_dump", AsyncMock(return_value=(tmp_path / "archive.zip",
        dict(messages=1, revisions=2, media=0, pending=0))))
    monkeypatch.setattr(module, "create_all_chats_dump", AsyncMock(return_value=(tmp_path / "archive.zip",
        dict(messages=1, revisions=2, media=0, pending=0))))
    monkeypatch.setattr(module, "send_chat_dump", AsyncMock(side_effect=(
        RuntimeError() if outcome == "error" else module.ApiProfileRequired() if outcome == "no_app_large" else None)))
    monkeypatch.setattr(module, "chat_history_status", AsyncMock(return_value=""))
    monkeypatch.setattr(module, "_notice", AsyncMock())
    progress = AsyncMock()
    module._busy.add(123)
    await module._dump(SimpleNamespace(), 123, None if outcome == "all" else 456,
                       None if outcome == "all" else 789, progress=progress)
    assert 123 not in module._busy
    assert progress.await_args.kwargs == {"done": True}
    assert progress.await_args.args[0] == (
        module.text.DUMP_ALL_DONE if outcome == "all" else module.text.DUMP_DONE.format(chat_id=789) if outcome in {"success", "no_app"} else
        module.text.DUMP_FAILED if outcome == "error" else module.text.DUMP_NEEDS_APP)
    assert "Отправляю ZIP" in progress.await_args_list[0].args[0]
    if outcome == "no_app":
        assert module.send_chat_dump.await_args.args[-1] is None
