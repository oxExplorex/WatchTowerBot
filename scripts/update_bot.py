import io
import os
import re
import shutil
import stat
import subprocess
import tempfile
import traceback
import zipfile
from pathlib import Path, PurePosixPath

import requests

DEFAULT_REPO_OWNER = "oxExplorex"
DEFAULT_REPO_NAME = "gemini_message_manager_tg"
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
}


def _is_protected(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").strip("/").casefold()
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
            if not relative or _is_protected(relative) or member.is_dir():
                continue
            target_path = _safe_target_path(destination, relative)
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


def _resolve_latest_commit_sha() -> str | None:
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/{REPO_BRANCH}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "gemini-message-manager-tg",
    }

    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        sha = str(payload.get("sha") or "").strip()
        return sha or None
    except Exception:
        return None


def download_and_extract_github_repo(*, progress=None) -> bool:
    try:
        if progress is not None:
            progress("Поиск сборки", "Получение актуальной версии из GitHub")
        sha = _resolve_latest_commit_sha()
        if sha:
            zip_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/zipball/{sha}"
        else:
            zip_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{REPO_BRANCH}.zip"

        if progress is not None:
            progress("Загрузка обновления", "Скачивание архива приложения из GitHub")
        response = requests.get(
            zip_url,
            timeout=60,
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "User-Agent": "gemini-message-manager-tg",
            },
        )
        response.raise_for_status()

        project_root = Path(__file__).resolve().parents[1]
        updated = _safe_extract_repo(response.content, project_root, progress=progress)
        print(f"Repository updated successfully. Files updated: {updated}")
        return True
    except requests.RequestException as exc:
        print(f"Download error: {exc}")
    except zipfile.BadZipFile as exc:
        print(f"Bad ZIP archive: {exc}")
    except Exception:
        print(f"Unexpected update error: {traceback.format_exc()}")

    return False


if __name__ == "__main__":
    raise SystemExit(0 if download_and_extract_github_repo() else 1)
