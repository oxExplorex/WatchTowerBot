import os
import logging
import sys

import pytest

from services.log_export import latest_log_file


def test_latest_log_is_selected_by_modification_time_without_reading_or_changing_it(tmp_path):
    old = tmp_path / "logs_05.11.2026.log"
    recent = tmp_path / "logs_04.11.2026.log"
    old.write_text("старый лог", encoding="utf-8")
    recent.write_text("последний лог", encoding="utf-8")
    (tmp_path / "ignored.env").write_text("not a log", encoding="utf-8")
    os.utime(old, (100, 100))
    os.utime(recent, (200, 200))
    assert latest_log_file(tmp_path) == recent
    assert recent.read_text(encoding="utf-8") == "последний лог"
    assert {entry.name for entry in tmp_path.iterdir()} == {old.name, recent.name, "ignored.env"}


def test_no_log_is_an_explicit_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        latest_log_file(tmp_path)


def test_each_run_has_its_own_log_and_export_prefers_active_file(tmp_path, monkeypatch, offline_module):
    import core.log_safety as safety

    monkeypatch.setattr(sys.modules["data.config"], "path_logs", str(tmp_path / "log_{d}.log"), raising=False)
    monkeypatch.setattr(safety, "route_library_errors", lambda _: None)
    logger = logging.Logger("offline-per-run")
    original_get_logger = logging.getLogger
    monkeypatch.setattr(logging, "getLogger", lambda name=None:
                        logger if name == "gemini_message_manager" else original_get_logger(name))
    module = offline_module("core/logging.py")
    monkeypatch.setattr(sys.modules["core.logging"], "bot_logger", logger)

    def close_handlers():
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    try:
        logger.info("первый запуск")
        first = latest_log_file()
        assert module._build_logger() is logger
        assert latest_log_file() == first  # Reusing the logger does not start another run.
        close_handlers()
        module._build_logger()
        logger.info("второй запуск")
        second = latest_log_file()
        assert second != first
        assert "первый запуск" in first.read_text(encoding="utf-8")
        assert "первый запуск" not in second.read_text(encoding="utf-8")
        assert "второй запуск" in second.read_text(encoding="utf-8")
        # Even a newer timestamp on a previous log must not change the button's selection.
        os.utime(first, (second.stat().st_mtime + 60, second.stat().st_mtime + 60))
        assert latest_log_file() == second
        assert len(list(tmp_path.glob("*.log"))) == 2
    finally:
        close_handlers()
