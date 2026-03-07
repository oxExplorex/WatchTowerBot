from __future__ import annotations

import re
from pathlib import Path

import aiohttp

from core.logging import bot_logger
from update_bot import REPO_BRANCH, REPO_NAME, REPO_OWNER

_VERSION_RE = re.compile(r"\d+")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = _PROJECT_ROOT / "VERSION"


def get_local_version() -> str:
    if not _VERSION_FILE.exists():
        return "0.0.0"

    version = _VERSION_FILE.read_text(encoding="utf-8").strip()
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


async def fetch_remote_version(timeout_sec: int = 15, log_prefix: str = "Version check") -> str | None:
    url = get_remote_version_url()
    timeout = aiohttp.ClientTimeout(total=timeout_sec)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    bot_logger.warning(f"{log_prefix} failed: HTTP {response.status} | {url}")
                    return None
                return (await response.text()).strip() or None
    except Exception as exc:
        bot_logger.warning(f"{log_prefix} error: {exc} | {url}")
        return None
