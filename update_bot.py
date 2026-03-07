import io
import os
import re
import shutil
import subprocess
import time
import traceback
import zipfile
from pathlib import Path

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
    ".editorconfig",
    ".gitattributes",
    "data/config.py",
    "data/proxy.txt",
    "data/session",
    "data/logs",
    "data/temp",
    "migrations",
}


def _is_protected(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").strip("/")
    return any(normalized == item or normalized.startswith(f"{item}/") for item in PROTECTED_PATHS)


def _safe_target_path(destination: Path, relative: str) -> Path:
    target_path = (destination / relative).resolve()
    destination_root = destination.resolve()
    if destination_root not in target_path.parents and target_path != destination_root:
        raise ValueError(f"Unsafe archive path: {relative}")
    return target_path


def _safe_extract_repo(zip_content: bytes, destination: Path) -> int:
    updated_files = 0

    with zipfile.ZipFile(io.BytesIO(zip_content)) as archive:
        names = archive.namelist()
        if not names:
            raise zipfile.BadZipFile("Archive is empty")

        first_member = names[0].strip("/")
        root_folder = first_member.split("/")[0]

        for member in names:
            if not member.startswith(f"{root_folder}/"):
                continue

            relative = member[len(root_folder) + 1 :].strip("/")
            if not relative or _is_protected(relative):
                continue

            target_path = _safe_target_path(destination, relative)

            if member.endswith("/"):
                target_path.mkdir(parents=True, exist_ok=True)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
                updated_files += 1

    return updated_files


def download_and_extract_github_repo() -> bool:
    try:
        zip_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{REPO_BRANCH}.zip"
        zip_url_with_ts = f"{zip_url}?t={int(time.time())}"
        response = requests.get(
            zip_url_with_ts,
            timeout=60,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        response.raise_for_status()

        project_root = Path(__file__).resolve().parent
        updated = _safe_extract_repo(response.content, project_root)
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
    download_and_extract_github_repo()
