import os

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
