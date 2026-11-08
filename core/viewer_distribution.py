"""Public download names shared by the bot and standalone build tooling."""

from pathlib import Path
import re

RELEASE_TAG = "archive-viewer"
WINDOWS_ARCHIVE = "WatchTowerViewer-windows-x64.zip"
EXECUTABLE = "WatchTowerViewer.exe"


def windows_archive(version):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid release version")
    return f"WatchTower-Viewer-{version}-Windows-x64.zip"


def download_url(owner, repository):
    version = Path(__file__).resolve().parents[1].joinpath("VERSION").read_text(encoding="utf-8-sig").strip()
    return f"https://github.com/{owner}/{repository}/releases/download/v{version}/{windows_archive(version)}"
