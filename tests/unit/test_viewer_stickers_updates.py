import gzip
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from archive_viewer.distribution import EXECUTABLE, WINDOWS_ARCHIVE
from archive_viewer.media_types import media_mime, preview_kind, sticker_data
from archive_viewer.updater import unpack_update, validate_manifest


def test_stickers_support_webp_webm_and_bounded_tgs():
    webp = b"RIFF\x00\x00\x00\x00WEBP"
    webm = b"\x1a\x45\xdf\xa3webm"
    assert media_mime(webp) == "image/webp" and sticker_data(webp)["format"] == "image"
    assert media_mime(webm) == "video/webm" and sticker_data(webm)["format"] == "video"
    animation = dict(v="5.5.2", w=512, h=512, fr=60, ip=0, op=180, layers=[])
    assert sticker_data(gzip.compress(json.dumps(animation).encode())) == {"format": "tgs", "animation": animation}
    for data in (gzip.compress(b"x" * (4 * 1024 * 1024 + 1)), gzip.compress(b"<script>bad</script>"), b"not a sticker"):
        with pytest.raises(ValueError):
            sticker_data(data)


@pytest.mark.parametrize("data,mime", [
    (b"\xff\xd8\xffphoto", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\nphoto", "image/png"),
    (b"GIF89aanimation", "image/gif"),
    (b"\x00\x00\x00\x18ftypisomvideo", "video/mp4"),
    (b"\x00\x00\x00\x18ftypM4A audio", "audio/mp4"),
    (b"OggSvoice", "audio/ogg"),
    (b"ID3music", "audio/mpeg"),
    (b"\xff\xfbMP3frames", "audio/mpeg"),
    (b"\xff\xf1AACframes", "audio/aac"),
    (b"RIFF\x00\x00\x00\x00WAVEaudio", "audio/wav"),
    (b"fLaCaudio", "audio/flac"),
    (b"<html>not-an-image</html>", "application/octet-stream"),
])
def test_native_media_content_types(data, mime):
    assert media_mime(data) == mime


@pytest.mark.parametrize("kind,mime,name,expected", [
    ("photo", None, None, "photo"), ("video_note", None, None, "video_note"),
    ("voice", None, None, "voice"), ("audio", None, None, "audio"),
    ("animation", "image/gif", "animation.gif", "photo"),
    ("animation", "video/mp4", "animation.mp4", "animation"),
    ("document", "image/jpeg", None, "photo"),
    ("document", None, "photo.PNG", "photo"),
    ("document", "video/mp4", "video.mp4", "video"),
    ("document", "audio/mpeg", "audio.mp3", "audio"),
    ("document", "image/svg+xml", "untrusted.svg", None),
    ("document", "text/html", "untrusted.html", None),
])
def test_native_previews_include_media_sent_as_document(kind, mime, name, expected):
    assert preview_kind(kind, mime, name) == expected


def test_native_players_receive_inline_media_and_seekable_ranges():
    import threading
    from types import SimpleNamespace
    from urllib.request import Request, build_opener, ProxyHandler
    from archive_viewer.server import ViewerServer
    samples = {"photo": (b"\xff\xd8\xffphoto", "image/jpeg"),
               "video": (b"\x00\x00\x00\x18ftypisomvideo", "video/mp4"),
               "audio": (b"ID3synthetic-music", "audio/mpeg")}
    with ViewerServer("unused-synthetic-path") as server:
        server.archive = SimpleNamespace(media=lambda identity: samples[identity][0], close=lambda: None)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            opener = build_opener(ProxyHandler({}))
            for identity, (data, mime) in samples.items():
                request = Request(server.origin + "/api/media/" + identity,
                    headers={"X-Viewer-Token": server.token, "Range": "bytes=0-3"})
                with opener.open(request, timeout=5) as response:
                    assert response.status == 206 and response.read() == data[:4]
                    assert response.headers["Content-Type"] == mime
                    assert response.headers["Content-Disposition"] is None
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_update_requires_newer_build_correct_repository_and_verified_executable(tmp_path):
    path = tmp_path / "update.zip"
    executable = b"MZsynthetic-executable-not-run"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(EXECUTABLE, executable)
        archive.writestr("../not-extracted", "outside")
    current = dict(repository="owner/repo", version="old", built_at=100)
    manifest = current | dict(version="new", built_at=200, archive=WINDOWS_ARCHIVE,
        size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert validate_manifest(manifest, current)
    assert not validate_manifest(manifest | {"built_at": 99}, current)
    with pytest.raises(ValueError):
        validate_manifest(manifest | {"repository": "other/repo"}, current)
    destination = tmp_path / "viewer.exe"
    unpack_update(path, destination, manifest)
    assert destination.read_bytes() == executable
    assert not (tmp_path.parent / "not-extracted").exists()
    with pytest.raises(ValueError, match="checksum"):
        unpack_update(path, tmp_path / "tampered.exe", manifest | {"sha256": "0" * 64})


@pytest.mark.parametrize("replace_fails", [False, True])
def test_update_handoff_preserves_backup_and_reopens_viewer(tmp_path, monkeypatch, replace_fails):
    import ctypes
    from types import SimpleNamespace
    from unittest.mock import Mock
    from archive_viewer import updater
    target, candidate = tmp_path / "installed.exe", tmp_path / "downloaded.exe"
    target.write_bytes(b"MZ-old")
    candidate.write_bytes(b"MZ-new")
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(candidate))
    # No real process is replaced or started; exercise the filesystem handoff itself.
    kernel = SimpleNamespace(OpenProcess=Mock(return_value=0), WaitForSingleObject=Mock(), CloseHandle=Mock())
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    start = Mock()
    monkeypatch.setattr(updater.subprocess, "Popen", start)
    if replace_fails:
        monkeypatch.setattr(updater.os, "replace", Mock(side_effect=OSError("synthetic replacement failure")))
    assert updater.apply_update(target, 0, "synthetic-backup.zip") == (not replace_fails)
    assert target.read_bytes() == (b"MZ-old" if replace_fails else b"MZ-new")
    assert target.with_suffix(".exe.previous").read_bytes() == b"MZ-old"
    assert start.call_args.args[0] == [str(target), "--no-update", "synthetic-backup.zip"]


def test_ui_update_locks_archive_before_starting_installer(monkeypatch):
    import threading
    from types import SimpleNamespace
    from unittest.mock import Mock
    from archive_viewer.update_status import UpdateStatus
    from archive_viewer import updater
    stopped = threading.Event()
    close = Mock()
    server = SimpleNamespace(path="synthetic.zip", lock=threading.RLock(),
                             archive=SimpleNamespace(close=close), shutdown=stopped.set)
    status = UpdateStatus(server)
    status.enabled = True
    status.value.update(available=True, state="available")
    def install(path):
        assert path == "synthetic.zip" and server.archive is None
        close.assert_called_once()
        return True
    monkeypatch.setattr(updater, "maybe_update", install)
    status.install()
    assert stopped.wait(2)


def test_downloaded_exe_is_not_renamed_after_self_test_and_each_attempt_is_isolated(tmp_path, monkeypatch, capsys):
    import io
    from unittest.mock import Mock
    from archive_viewer import updater

    current = dict(repository="owner/repo", version="old", built_at=100)
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr(EXECUTABLE, b"MZ-synthetic-new-exe")
    raw = packed.getvalue()
    manifest = current | dict(version="new", built_at=200, archive=WINDOWS_ARCHIVE,
        size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    target = tmp_path / "installed.exe"
    target.write_bytes(b"MZ-old")
    build = tmp_path / "build_info.json"
    build.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(updater, "BUILD_INFO", build)
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(target))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(updater, "build_info", lambda: current)
    monkeypatch.setattr(updater, "fetch_manifest", lambda _: manifest)
    monkeypatch.setattr(updater, "urlopen", lambda *args, **kwargs: io.BytesIO(raw))
    check, start = Mock(), Mock()
    monkeypatch.setattr(updater.subprocess, "run", check)
    monkeypatch.setattr(updater.subprocess, "Popen", start)
    rename = Mock(side_effect=PermissionError("Windows still holds the self-tested EXE"))
    monkeypatch.setattr(updater.os, "replace", rename)
    assert updater.maybe_update("synthetic-backup.zip")
    assert updater.maybe_update("synthetic-backup.zip")
    paths = [call.args[0][0] for call in start.call_args_list]
    assert len(set(paths)) == 2
    assert paths == [call.args[0][0] for call in check.call_args_list]
    assert all(Path(path).read_bytes() == b"MZ-synthetic-new-exe" for path in paths)
    assert target.read_bytes() == b"MZ-old"
    rename.assert_not_called()
    check.side_effect = PermissionError(13, "private-path-never-print")
    assert not updater.maybe_update()
    assert start.call_count == 2 and target.read_bytes() == b"MZ-old"
    output = capsys.readouterr().out
    assert "самопроверка нового EXE (PermissionError, код 13)" in output
    assert "private-path-never-print" not in output


def test_update_error_names_stage_and_os_code_without_leaking_paths(tmp_path, monkeypatch, capsys):
    from unittest.mock import Mock
    from archive_viewer import updater

    build = tmp_path / "build_info.json"
    build.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(updater, "BUILD_INFO", build)
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "build_info", lambda: dict(repository="owner/repo"))
    monkeypatch.setattr(updater, "fetch_manifest", Mock(side_effect=PermissionError(13, "private-user-path")))
    assert not updater.maybe_update()
    output = capsys.readouterr().out
    assert "проверка версии" in output and "PermissionError, код 13" in output
    assert "private-user-path" not in output


def test_update_cleanup_preserves_fresh_jobs_and_unmanaged_folders(tmp_path):
    import os
    import time
    from archive_viewer.updater import cleanup_downloads

    old, fresh, unmanaged = [tmp_path / name for name in ("download-old", "download-fresh", "other-folder")]
    for folder in (old, fresh, unmanaged):
        folder.mkdir()
        (folder / "synthetic.exe").write_bytes(b"MZ")
    expired = time.time() - 8 * 86400
    os.utime(old, (expired, expired))
    os.utime(unmanaged, (expired, expired))
    cleanup_downloads(tmp_path)
    assert not old.exists()
    assert fresh.exists() and unmanaged.exists()
