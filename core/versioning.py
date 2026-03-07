from __future__ import annotations

import base64
import re
import time
from pathlib import Path

import aiohttp

from core.logging import bot_logger
from scripts.update_bot import REPO_BRANCH, REPO_NAME, REPO_OWNER

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


def get_remote_version_api_url() -> str:
    return (
        f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/VERSION"
        f"?ref={REPO_BRANCH}"
    )


async def _fetch_remote_version_via_api(session: aiohttp.ClientSession) -> str | None:
    api_url = f"{get_remote_version_api_url()}&t={int(time.time())}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "gemini-message-manager-tg",
    }

    async with session.get(api_url, headers=headers) as response:
        if response.status != 200:
            return None

        payload = await response.json()
        encoded = payload.get("content")
        if not encoded:
            return None

        try:
            decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
        except Exception:
            return None

        version = decoded.strip()
        return version or None


async def _fetch_remote_version_via_raw(session: aiohttp.ClientSession) -> str | None:
    base_url = get_remote_version_url()
    cache_busted_url = f"{base_url}?t={int(time.time())}"
    headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "gemini-message-manager-tg",
    }

    async with session.get(cache_busted_url, headers=headers) as response:
        if response.status != 200:
            return None
        return (await response.text()).strip() or None


async def fetch_remote_version(timeout_sec: int = 15, log_prefix: str = "Version check") -> str | None:
    timeout = aiohttp.ClientTimeout(total=timeout_sec)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            version = await _fetch_remote_version_via_api(session)
            if version:
                return version

            version = await _fetch_remote_version_via_raw(session)
            if version:
                return version

            bot_logger.warning(
                f"{log_prefix} failed: no data from API/raw | "
                f"api={get_remote_version_api_url()} raw={get_remote_version_url()}"
            )
            return None
    except Exception as exc:
        bot_logger.warning(
            f"{log_prefix} error: {exc} | "
            f"api={get_remote_version_api_url()} raw={get_remote_version_url()}"
        )
        return None

