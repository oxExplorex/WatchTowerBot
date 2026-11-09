"""Shared, dependency-free contract for published bot release assets."""
from dataclasses import dataclass
import re

MAX_ARCHIVE_BYTES = 64 * 1024**2
MAX_CHECKSUM_BYTES = 1024
MAX_METADATA_BYTES = 1024**2


def valid_version(value):
    return isinstance(value, str) and len(value) <= 40 and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is not None


def version_tuple(value):
    if not valid_version(value):
        raise ValueError("Invalid release version")
    return tuple(map(int, value.split(".")))


def repository_path(owner, repository):
    for value in (owner, repository):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError("Invalid release repository")
    return f"{owner}/{repository}"


def release_api_url(owner, repository, version=None):
    suffix = "latest"
    if version is not None:
        version_tuple(version)
        suffix = f"tags/v{version}"
    return f"https://api.github.com/repos/{repository_path(owner, repository)}/releases/{suffix}"


@dataclass(frozen=True)
class BotRelease:
    version: str
    size: int
    checksum_size: int

    @property
    def archive(self):
        return f"WatchTower-Bot-{self.version}.zip"

    def asset_url(self, owner, repository, *, checksum=False):
        filename = self.archive + (".sha256" if checksum else "")
        return f"https://github.com/{repository_path(owner, repository)}/releases/download/v{self.version}/{filename}"


def parse_release(payload, *, expected_version=None):
    if (not isinstance(payload, dict) or payload.get("draft") is not False
            or payload.get("prerelease") is not False):
        raise ValueError("Not a published stable release")
    tag = payload.get("tag_name")
    version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else None
    version_tuple(version)
    if expected_version is not None and version != expected_version:
        raise ValueError("Release version mismatch")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Release assets missing")
    name = f"WatchTower-Bot-{version}.zip"
    sizes = []
    for filename, limit in ((name, MAX_ARCHIVE_BYTES), (name + ".sha256", MAX_CHECKSUM_BYTES)):
        matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == filename]
        if len(matches) != 1:
            raise ValueError("Release asset missing or duplicated")
        asset = matches[0]
        size = asset.get("size")
        if asset.get("state") != "uploaded" or type(size) is not int or not 0 < size <= limit:
            raise ValueError("Release asset is incomplete or oversized")
        sizes.append(size)
    return BotRelease(version, *sizes)
