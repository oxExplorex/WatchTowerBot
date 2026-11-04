from pathlib import Path

import pytest

from core import session_files


def test_database_failure_restores_all_previous_session_files(tmp_path):
    old, new = str(tmp_path / "old"), str(tmp_path / "temporary")
    for name, content in [(old + ".session", b"old"), (old + ".session-wal", b"old-wal"), (new + ".session", b"new")]:
        Path(name).write_bytes(content)
    with pytest.raises(RuntimeError):
        with session_files.replace_session_files(new, old):
            assert Path(old + ".session").read_bytes() == b"new"
            raise RuntimeError("database unavailable")
    assert Path(old + ".session").read_bytes() == b"old"
    assert Path(old + ".session-wal").read_bytes() == b"old-wal"


def test_failed_rename_restores_original_without_deleting_it(monkeypatch, tmp_path):
    old, new = str(tmp_path / "old"), str(tmp_path / "temporary")
    Path(old + ".session").write_bytes(b"old")
    Path(new + ".session").write_bytes(b"new")
    replace = session_files.os.replace

    def fail(source, destination):
        if source == Path(new + ".session"):
            raise PermissionError("busy")
        replace(source, destination)

    monkeypatch.setattr(session_files.os, "replace", fail)
    with pytest.raises(PermissionError):
        with session_files.replace_session_files(new, old):
            pytest.fail("Must not save DB after failed replacement")
    assert Path(old + ".session").read_bytes() == b"old"
    assert Path(new + ".session").read_bytes() == b"new"


def test_missing_authorized_session_does_not_touch_old_file(tmp_path):
    old = str(tmp_path / "old")
    Path(old + ".session").write_bytes(b"old")
    with pytest.raises(FileNotFoundError):
        with session_files.replace_session_files(str(tmp_path / "missing"), old):
            pytest.fail("Missing authorization must not be installed")
    assert Path(old + ".session").read_bytes() == b"old"


def test_success_replaces_session_and_removes_stale_sidecars(tmp_path):
    old, new = str(tmp_path / "old"), str(tmp_path / "temporary")
    Path(old + ".session").write_bytes(b"old")
    Path(old + ".session-wal").write_bytes(b"old-wal")
    Path(new + ".session").write_bytes(b"new")
    with session_files.replace_session_files(new, old):
        pass
    assert Path(old + ".session").read_bytes() == b"new"
    assert not Path(old + ".session-wal").exists()
    assert not list(tmp_path.glob("_session_backup_*"))


def test_account_cleanup_preserves_other_numbers_and_unrelated_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data" / "session"
    root.mkdir(parents=True)
    own = root / "7901.session"
    sidecar = root / "7901.session-wal"
    other = root / "79012.session"
    backup = root / "7901.backup"
    for path in (own, sidecar, other, backup):
        path.write_bytes(b"synthetic-session")
    session_files.remove_account_session_files("7901")
    assert not own.exists() and not sidecar.exists()
    assert other.exists() and backup.exists()
    with pytest.raises(ValueError):
        session_files.remove_account_session_files("../79012")
    assert other.exists()
