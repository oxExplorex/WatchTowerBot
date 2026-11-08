"""Public download names shared by the bot and standalone build tooling."""

RELEASE_TAG = "archive-viewer"
WINDOWS_ARCHIVE = "WatchTowerViewer-windows-x64.zip"
EXECUTABLE = "WatchTowerViewer.exe"


def download_url(owner, repository):
    return f"https://github.com/{owner}/{repository}/releases/download/{RELEASE_TAG}/{WINDOWS_ARCHIVE}"
