from __future__ import annotations

import re
from pathlib import Path

from update_bot import REPO_BRANCH, REPO_NAME, REPO_OWNER

_VERSION_RE = re.compile(r"\d+")


def get_local_version() -> str:
    version_file = Path("VERSION")
    if not version_file.exists():
        return "0.0.0"

    version = version_file.read_text(encoding="utf-8").strip()
    return version or "0.0.0"


def normalize_version(version: str) -> tuple[int, ...]:
    numbers = [int(chunk) for chunk in _VERSION_RE.findall(version or "")]
    if not numbers:
        return (0,)
    return tuple(numbers)


def is_newer_version(current_version: str, latest_version: str) -> bool:
    left = normalize_version(current_version)
    right = normalize_version(latest_version)
    return right > left


def get_remote_version_url() -> str:
    return f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}/VERSION"