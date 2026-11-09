import io
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import requests

# Also support direct execution: python scripts/update_bot.py.
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.bot_release import (MAX_ARCHIVE_BYTES, MAX_CHECKSUM_BYTES, MAX_METADATA_BYTES,
                              parse_release, release_api_url, version_tuple)

DEFAULT_REPO_OWNER = "oxExplorex"
DEFAULT_REPO_NAME = "WatchTowerBot"
DEFAULT_REPO_BRANCH = "main"


def _detect_repo_from_git() -> tuple[str | None, str | None]:
    try:
        remote_url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None, None

    if not remote_url:
        return None, None

    # Supports:
    # - https://github.com/owner/repo(.git)
    # - git@github.com:owner/repo(.git)
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$", remote_url)
    if not match:
        return None, None

    return match.group("owner"), match.group("repo")


def _resolve_repo_settings() -> tuple[str, str, str]:
    git_owner, git_repo = _detect_repo_from_git()

    owner = os.getenv("BOT_UPDATE_REPO_OWNER") or git_owner or DEFAULT_REPO_OWNER
    repo = os.getenv("BOT_UPDATE_REPO_NAME") or git_repo or DEFAULT_REPO_NAME
    branch = os.getenv("BOT_UPDATE_REPO_BRANCH") or DEFAULT_REPO_BRANCH

    return owner, repo, branch


REPO_OWNER, REPO_NAME, REPO_BRANCH = _resolve_repo_settings()

# Files that must survive update and stay local.
PROTECTED_PATHS = {
    ".git",
    ".gitignore",
    ".venv",
    "venv",
    ".local-notes",
    ".editorconfig",
    ".gitattributes",
    ".env",
    ".env.local",
    "data/proxy.txt",
    "data/session",
    "data/logs",
    "data/temp",
    "data/media",
    "data/backups",
}


def _is_protected(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").strip("/").casefold()
    if (normalized.split("/")[0].startswith(".env") and normalized != ".env.example"
            or normalized.endswith((".db", ".sqlite", ".sqlite3", ".session", ".session-wal", ".session-shm"))):
        return True
    if normalized.split("/")[0].startswith(".watchtower-update-"):
        return True
    return any(normalized == item.casefold() or normalized.startswith(f"{item.casefold()}/") for item in PROTECTED_PATHS)


def _safe_target_path(destination: Path, relative: str) -> Path:
    destination_root = destination.resolve()
    candidate = destination_root
    for part in PurePosixPath(relative).parts:
        candidate = candidate / part
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError(f"Archive target uses a link: {relative}")
    target_path = candidate.resolve()
    if destination_root not in target_path.parents and target_path != destination_root:
        raise ValueError(f"Unsafe archive path: {relative}")
    return target_path


def _safe_extract_repo(zip_content: bytes, destination: Path, *, progress=None) -> int:
    destination = destination.resolve()
    with zipfile.ZipFile(io.BytesIO(zip_content)) as archive:
        members = archive.infolist()
        if not members:
            raise zipfile.BadZipFile("Archive is empty")
        root_folder = members[0].filename.split("/")[0]
        files = []
        seen = set()
        for member in members:
            name = member.orig_filename
            parts = name.rstrip("/").split("/")
            if not root_folder or parts[0] != root_folder or "\\" in name or any(
                part in {"", ".", ".."} or ":" in part for part in parts
            ):
                raise ValueError(f"Unsafe archive path: {name}")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Archive contains a link: {name}")
            relative = "/".join(parts[1:])
            if not relative or member.is_dir():
                continue
            target_path = _safe_target_path(destination, relative)
            if _is_protected(relative):
                continue
            identity = relative.casefold()
            if identity in seen:
                raise ValueError(f"Duplicate archive target: {relative}")
            if target_path.exists() and not target_path.is_file():
                raise ValueError(f"Archive file would replace a directory: {relative}")
            seen.add(identity)
            files.append((member, relative))
        if not files:
            raise zipfile.BadZipFile("Archive contains no application files")
        if progress is not None:
            progress("Проверка обновления", f"Распаковка и проверка {len(files)} файлов; подготовка резервной копии кода")

        # Fully extract (including CRC checks) and back up before changing code.
        workspace = Path(tempfile.mkdtemp(prefix=".watchtower-update-", dir=destination))
        applied = []
        created_directories = []
        preserve_backup = False
        try:
            for member, relative in files:
                staged = workspace / "staged" / relative
                backup = workspace / "backup" / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, staged.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                target = _safe_target_path(destination, relative)
                if target.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                    staged.chmod(stat.S_IMODE(target.stat().st_mode))
                else:
                    mode = stat.S_IMODE(member.external_attr >> 16) & 0o777
                    if mode:
                        staged.chmod(mode)
            if progress is not None:
                progress("Установка обновления", f"Замена {len(files)} файлов приложения")
            try:
                for _, relative in files:
                    target = _safe_target_path(destination, relative)
                    missing = []
                    parent = target.parent
                    while not parent.exists():
                        missing.append(parent)
                        parent = parent.parent
                    target.parent.mkdir(parents=True, exist_ok=True)
                    created_directories.extend(reversed(missing))
                    os.replace(workspace / "staged" / relative, target)
                    applied.append(relative)
            except BaseException:
                try:
                    for relative in reversed(applied):
                        target = _safe_target_path(destination, relative)
                        backup = workspace / "backup" / relative
                        if backup.exists():
                            os.replace(backup, target)
                        else:
                            target.unlink(missing_ok=True)
                    for directory in reversed(created_directories):
                        directory.rmdir()
                except Exception:
                    preserve_backup = True
                    raise RuntimeError(f"Update rollback failed; backup retained in {workspace}") from None
                raise
        finally:
            if not preserve_backup:
                shutil.rmtree(workspace, ignore_errors=True)
    return len(files)


def _download(url, limit):
    headers = {"Accept": "application/vnd.github+json", "Cache-Control": "no-cache",
               "User-Agent": "WatchTowerBot"}
    with requests.get(url, timeout=(10, 60), headers=headers, stream=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError("Release download exceeds size limit")
            chunks.append(chunk)
        return b"".join(chunks)


def _validate_bot_archive(content, version):
    prefix = f"WatchTower-Bot-{version}/"
    required = {"VERSION", "main.py", "loader.py", "requirements.txt", "alembic.ini",
                "scripts/update_bot.py", "scripts/install_dependencies.py"}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(item.file_size for item in members) > 256 * 1024**2:
            raise ValueError("Expanded release exceeds size limit")
        if any(not item.orig_filename.startswith(prefix) for item in members):
            raise ValueError("Unexpected bot release folder")
        names = {item.filename[len(prefix):] for item in members if not item.is_dir()}
        if not required <= names:
            raise ValueError("Bot release is missing required files")
        if any(name.startswith("archive_viewer/") or name.lower().endswith(".exe") for name in names):
            raise ValueError("Bot release contains viewer files")
        version_file = archive.getinfo(prefix + "VERSION")
        if version_file.file_size > 128 or archive.read(version_file).decode("utf-8-sig").strip() != version:
            raise ValueError("Archive VERSION does not match release")


def download_and_extract_github_repo(*, progress=None, expected_version=None, allow_current=False) -> bool:
    """Compatibility entry point: install only a verified published bot ZIP."""
    try:
        if progress is not None:
            progress("Поиск сборки", "Проверка опубликованного релиза GitHub")
        metadata = _download(release_api_url(REPO_OWNER, REPO_NAME, expected_version), MAX_METADATA_BYTES)
        release = parse_release(json.loads(metadata), expected_version=expected_version)
        current = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8-sig").strip()
        target_version, current_version = version_tuple(release.version), version_tuple(current)
        if target_version < current_version or target_version == current_version and not allow_current:
            raise ValueError("Release is not newer than the installed version")
        if progress is not None:
            progress("Загрузка обновления", f"Скачивание готовой сборки {release.version}")
        checksum = _download(release.asset_url(REPO_OWNER, REPO_NAME, checksum=True), MAX_CHECKSUM_BYTES)
        if len(checksum) != release.checksum_size:
            raise ValueError("Incomplete checksum file")
        match = re.fullmatch(r"([a-fA-F0-9]{64})[ \t]+\*?" + re.escape(release.archive) + r"\s*",
                             checksum.decode("ascii"))
        if match is None:
            raise ValueError("Invalid release checksum file")
        content = _download(release.asset_url(REPO_OWNER, REPO_NAME), MAX_ARCHIVE_BYTES)
        if len(content) != release.size or hashlib.sha256(content).hexdigest() != match[1].lower():
            raise ValueError("Release checksum or size mismatch")
        _validate_bot_archive(content, release.version)
        updated = _safe_extract_repo(content, PROJECT_ROOT, progress=progress)
        print(f"Release {release.version} installed. Files updated: {updated}")
        return True
    except (requests.RequestException, ValueError, OSError, zipfile.BadZipFile) as error:
        # Do not print HTTP URLs, credentials or local filesystem paths.
        print(f"Release update failed: {type(error).__name__}. Existing installation retained.")
    except Exception as error:
        print(f"Unexpected release update failure: {type(error).__name__}")
    return False


if __name__ == "__main__":
    # update.bat/update.sh can be retried after code was installed but dependency
    # preparation failed. Reinstalling the same verified release is safe here.
    raise SystemExit(0 if download_and_extract_github_repo(allow_current=True) else 1)
