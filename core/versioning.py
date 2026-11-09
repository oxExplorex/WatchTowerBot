from __future__ import annotations

import json
import re
from pathlib import Path

import aiohttp

from core.logging import bot_logger
from scripts.update_bot import REPO_NAME, REPO_OWNER
from core.bot_release import MAX_METADATA_BYTES, parse_release, release_api_url

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
    return release_api_url(REPO_OWNER, REPO_NAME)


def get_remote_version_api_url() -> str:
    return get_remote_version_url()


async def fetch_remote_version(timeout_sec: int = 15, log_prefix: str = "Version check") -> str | None:
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    headers = {"Accept": "application/vnd.github+json", "Cache-Control": "no-cache",
               "User-Agent": "WatchTowerBot"}
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(get_remote_version_url(), headers=headers) as response:
                if response.status != 200:
                    bot_logger.warning("%s: published release unavailable, status=%s", log_prefix, response.status)
                    return None
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(64 * 1024):
                    size += len(chunk)
                    if size > MAX_METADATA_BYTES:
                        raise ValueError("Oversized release metadata")
                    chunks.append(chunk)
                return parse_release(json.loads(b"".join(chunks))).version
    except Exception as error:
        bot_logger.warning("%s: published release check failed: %s", log_prefix, type(error).__name__)
        return None
