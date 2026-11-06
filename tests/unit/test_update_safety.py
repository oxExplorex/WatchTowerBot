import io
from pathlib import Path
import zipfile

import pytest

from scripts import update_bot


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, content in files:
            member = zipfile.ZipInfo("release/placeholder")
            member.filename = f"release/{name}"
            bundle.writestr(member, content)
    return output.getvalue()


def test_all_archive_paths_are_validated_before_overwriting_code(tmp_path):
    (tmp_path / "main.py").write_bytes(b"original")
    content = archive([("main.py", b"new"), ("../escape.py", b"invalid")])
    with pytest.raises(ValueError):
        update_bot._safe_extract_repo(content, tmp_path)
    assert (tmp_path / "main.py").read_bytes() == b"original"


def test_bad_crc_does_not_partially_replace_code(tmp_path):
    (tmp_path / "main.py").write_bytes(b"original")
    content = archive([("main.py", b"new"), ("second.py", b"unique-payload")])
    damaged = content.replace(b"unique-payload", b"broken-payload", 1)
    with pytest.raises(zipfile.BadZipFile):
        update_bot._safe_extract_repo(damaged, tmp_path)
    assert (tmp_path / "main.py").read_bytes() == b"original"
    assert not (tmp_path / "second.py").exists()


def test_update_reports_validation_and_installation_without_touching_runtime_data(tmp_path):
    phases = []
    result = update_bot._safe_extract_repo(archive([("main.py", b"new"), ("data/temp/state.json", b"skip")]),
                                          tmp_path, progress=lambda phase, detail: phases.append(phase))
    assert result == 1
    assert phases == ["Проверка обновления", "Установка обновления"]
    assert (tmp_path / "main.py").read_bytes() == b"new"
    assert not (tmp_path / "data/temp/state.json").exists()


def test_apply_error_rolls_back_replaced_and_created_files(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_bytes(b"original")
    content = archive([("main.py", b"new"), ("new/module.py", b"created"), ("second.py", b"fail")])
    replace = update_bot.os.replace

    def fail(source, target):
        if "staged" in Path(source).parts and Path(target).name == "second.py":
            raise PermissionError("busy")
        return replace(source, target)

    monkeypatch.setattr(update_bot.os, "replace", fail)
    with pytest.raises(PermissionError):
        update_bot._safe_extract_repo(content, tmp_path)
    assert (tmp_path / "main.py").read_bytes() == b"original"
    assert not (tmp_path / "new").exists()
    assert not list(tmp_path.glob(".watchtower-update-*"))


@pytest.mark.parametrize("path", [".env", ".env.local", "data/session/account.session", "data/proxy.txt", ".local-notes/plan.md", "data/media/123/blob.wtm"])
def test_local_data_is_preserved(tmp_path, path):
    protected = tmp_path / path
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_bytes(b"synthetic-private")
    result = update_bot._safe_extract_repo(archive([(path, b"overwrite"), ("main.py", b"new")]), tmp_path)
    assert result == 1
    assert protected.read_bytes() == b"synthetic-private"


@pytest.mark.parametrize("path", ["./.env", "data/../main.py", "C:/outside.py", "data\\session\\x.session"])
def test_noncanonical_paths_are_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        update_bot._safe_extract_repo(archive([("main.py", b"new"), (path, b"invalid")]), tmp_path)
    assert not (tmp_path / "main.py").exists()


def test_duplicate_case_insensitive_targets_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        update_bot._safe_extract_repo(archive([("main.py", b"first"), ("MAIN.py", b"second")]), tmp_path)


def test_existing_link_cannot_redirect_updates(tmp_path):
    private = tmp_path / "data/session"
    private.mkdir(parents=True)
    try:
        (tmp_path / "alias").symlink_to(private, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links is unavailable")
    with pytest.raises(ValueError):
        update_bot._safe_extract_repo(archive([("alias/account.session", b"invalid")]), tmp_path)


def test_backup_is_retained_if_rollback_itself_fails(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_bytes(b"original")
    content = archive([("main.py", b"new"), ("second.py", b"fail")])
    replace = update_bot.os.replace

    def fail(source, target):
        if Path(target).name == "second.py" or "backup" in Path(source).parts:
            raise PermissionError("busy")
        return replace(source, target)

    monkeypatch.setattr(update_bot.os, "replace", fail)
    with pytest.raises(RuntimeError, match="backup retained"):
        update_bot._safe_extract_repo(content, tmp_path)
    backups = list(tmp_path.glob(".watchtower-update-*/backup/main.py"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"original"
