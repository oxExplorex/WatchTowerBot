import io
import os
import shutil
import traceback
import zipfile
from pathlib import Path

import requests

REPO_OWNER = "oxExplorex"
REPO_NAME = "gemini_message_manager_tg"
REPO_BRANCH = "main"

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
        response = requests.get(zip_url, timeout=60)
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
