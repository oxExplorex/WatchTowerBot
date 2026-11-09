import hashlib
import io
import json
from types import SimpleNamespace
import zipfile

import pytest
import requests

from core.bot_release import MAX_ARCHIVE_BYTES, parse_release, release_api_url
from scripts import update_bot


def package(version="2.1.4", *, embedded_version=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in ("VERSION", "main.py", "loader.py", "requirements.txt", "alembic.ini",
                         "scripts/update_bot.py", "scripts/install_dependencies.py", ".env.production",
                         "data/backups/part.wtb"):
            content = (embedded_version or version).encode() if filename == "VERSION" else b"new"
            archive.writestr(f"WatchTower-Bot-{version}/{filename}", content)
    return data.getvalue()


def release_payload(content, version="2.1.4"):
    name = f"WatchTower-Bot-{version}.zip"
    checksum = f"{hashlib.sha256(content).hexdigest()}  {name}\n".encode()
    metadata = dict(tag_name=f"v{version}", draft=False, prerelease=False, assets=[
        dict(name=name, state="uploaded", size=len(content), browser_download_url="https://untrusted.invalid/file"),
        dict(name=name + ".sha256", state="uploaded", size=len(checksum)),
    ])
    return metadata, checksum


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]


def fake_downloads(monkeypatch, tmp_path, content, metadata, checksum):
    monkeypatch.setattr(update_bot, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(update_bot, "REPO_OWNER", "owner")
    monkeypatch.setattr(update_bot, "REPO_NAME", "repo")
    (tmp_path / "VERSION").write_text("2.0.0", encoding="utf-8")
    (tmp_path / "main.py").write_bytes(b"old")
    (tmp_path / ".env.production").write_bytes(b"synthetic-local-config")
    (tmp_path / "data/backups").mkdir(parents=True)
    (tmp_path / "data/backups/part.wtb").write_bytes(b"synthetic-local-backup")
    calls = []
    responses = iter((json.dumps(metadata).encode(), checksum, content))

    def get(url, **kwargs):
        calls.append(url)
        return Response(next(responses))
    monkeypatch.setattr(update_bot.requests, "get", get)
    return calls


def test_installs_pinned_release_with_hash_and_preserves_local_data(monkeypatch, tmp_path):
    content = package()
    metadata, checksum = release_payload(content)
    calls = fake_downloads(monkeypatch, tmp_path, content, metadata, checksum)
    phases = []
    assert update_bot.download_and_extract_github_repo(expected_version="2.1.4",
        progress=lambda phase, detail: phases.append(phase))
    assert calls == ["https://api.github.com/repos/owner/repo/releases/tags/v2.1.4",
        "https://github.com/owner/repo/releases/download/v2.1.4/WatchTower-Bot-2.1.4.zip.sha256",
        "https://github.com/owner/repo/releases/download/v2.1.4/WatchTower-Bot-2.1.4.zip"]
    assert (tmp_path / "main.py").read_bytes() == b"new"
    assert (tmp_path / "VERSION").read_text() == "2.1.4"
    assert (tmp_path / ".env.production").read_bytes() == b"synthetic-local-config"
    assert (tmp_path / "data/backups/part.wtb").read_bytes() == b"synthetic-local-backup"
    assert phases[-1] == "Установка обновления"
    assert not list(tmp_path.glob(".watchtower-update-*"))


@pytest.mark.parametrize("failure", ["hash", "truncated", "version", "draft", "prerelease", "missing",
                                     "duplicate", "tag", "checksum_name", "not_newer", "wrong_archive"])
def test_invalid_release_never_replaces_code_or_falls_back_to_main(monkeypatch, tmp_path, failure):
    content = package(embedded_version="2.1.5" if failure == "version" else None)
    metadata, checksum = release_payload(content)
    if failure == "hash":
        checksum = b"0" * 64 + checksum[64:]
    elif failure == "truncated":
        content = content[:-1]
    elif failure in {"draft", "prerelease"}:
        metadata[failure] = True
    elif failure == "missing":
        metadata["assets"].pop()
    elif failure == "duplicate":
        metadata["assets"].append(metadata["assets"][0])
    elif failure == "tag":
        metadata["tag_name"] = "v2.1.5"
    elif failure == "checksum_name":
        checksum = checksum.replace(b"WatchTower-Bot", b"WatchTower-Not")
    elif failure == "wrong_archive":
        content = b"not-a-zip"
        metadata, checksum = release_payload(content)
    calls = fake_downloads(monkeypatch, tmp_path, content, metadata, checksum)
    if failure == "not_newer":
        (tmp_path / "VERSION").write_text("2.1.4", encoding="utf-8")
    assert not update_bot.download_and_extract_github_repo(expected_version="2.1.4")
    assert (tmp_path / "main.py").read_bytes() == b"old"
    assert not (tmp_path / "loader.py").exists()
    assert all("raw.githubusercontent.com" not in url and "zipball" not in url for url in calls)


def test_network_failure_does_not_download_unpublished_source(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("synthetic-private-url")
    monkeypatch.setattr(update_bot.requests, "get", unavailable)
    assert not update_bot.download_and_extract_github_repo(expected_version="2.1.4")


@pytest.mark.parametrize("installed,success", [("2.1.4", True), ("2.1.5", False)])
def test_manual_script_can_retry_current_release_but_never_downgrades(monkeypatch, tmp_path, installed, success):
    content = package()
    metadata, checksum = release_payload(content)
    fake_downloads(monkeypatch, tmp_path, content, metadata, checksum)
    (tmp_path / "VERSION").write_text(installed, encoding="utf-8")
    assert update_bot.download_and_extract_github_repo(allow_current=True) is success
    assert (tmp_path / "VERSION").read_text() == ("2.1.4" if success else installed)
    assert (tmp_path / "main.py").read_bytes() == (b"new" if success else b"old")


def test_download_size_is_bounded_and_asset_metadata_is_checked(monkeypatch):
    monkeypatch.setattr(update_bot.requests, "get", lambda *args, **kwargs: Response(b"oversized"))
    with pytest.raises(ValueError):
        update_bot._download("https://github.com/synthetic", 3)
    metadata, _ = release_payload(package())
    metadata["assets"][0]["size"] = MAX_ARCHIVE_BYTES + 1
    with pytest.raises(ValueError):
        parse_release(metadata)
    with pytest.raises(ValueError):
        release_api_url("../outside", "repo")


@pytest.mark.asyncio
@pytest.mark.parametrize("published", [True, False])
async def test_version_check_uses_complete_published_release_only(monkeypatch, offline_module, published):
    module = offline_module("core/versioning.py")
    metadata, _ = release_payload(package())
    metadata["draft"] = not published
    urls = []

    class Content:
        async def iter_chunked(self, size):
            yield json.dumps(metadata).encode()

    class Session:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        def get(self, url, **kwargs):
            urls.append(url)
            class Result:
                async def __aenter__(self):
                    return SimpleNamespace(status=200, content=Content())
                async def __aexit__(self, *args):
                    pass
            return Result()

    monkeypatch.setattr(module.aiohttp, "ClientSession", Session)
    assert await module.fetch_remote_version() == ("2.1.4" if published else None)
    assert len(urls) == 1 and urls[0].endswith("/releases/latest")
