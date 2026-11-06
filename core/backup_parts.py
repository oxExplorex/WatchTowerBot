"""Telegram-sized ciphertext parts; paths and filenames never come from the archive."""
from pathlib import Path
import re

from core.backup_format import InvalidBackup

PART_SIZE = 15 * 1024 * 1024  # Below both Bot API upload and getFile download limits.
MAX_PARTS = 512
PART_NAME = re.compile(r"watchtower-([0-9a-f]{32})-(\d{4})-of-(\d{4})\.wtb\Z")


def parse_part_name(name):
    match = PART_NAME.fullmatch(name or "")
    if not match:
        raise InvalidBackup("Invalid backup filename")
    identity, index, total = match.groups()
    index, total = int(index), int(total)
    if not 1 <= index <= total <= MAX_PARTS:
        raise InvalidBackup("Invalid backup part count")
    return identity, index, total


class PartsWriter:
    def __init__(self, root, identity):
        if not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise InvalidBackup("Invalid backup identity")
        self.root, self.identity = Path(root), identity
        self.root.mkdir(parents=True, exist_ok=True)
        self.files, self.stream = [], None

    def write(self, data):
        view = memoryview(data)
        while view:
            if self.stream is None or self.stream.tell() == PART_SIZE:
                if self.stream:
                    self.stream.close()
                if len(self.files) >= MAX_PARTS:
                    raise InvalidBackup("Backup exceeds size limit")
                path = self.root / f"{len(self.files) + 1:04d}.part"
                self.stream = path.open("xb")
                self.files.append(path)
            length = min(len(view), PART_SIZE - self.stream.tell())
            self.stream.write(view[:length])
            view = view[length:]

    def close(self):
        if self.stream:
            self.stream.close()

    def finish(self):
        self.close()
        total = len(self.files)
        result = []
        for index, path in enumerate(self.files, 1):
            final = self.root / f"watchtower-{self.identity}-{index:04d}-of-{total:04d}.wtb"
            path.rename(final)
            result.append(final)
        return result


class PartsReader:
    def __init__(self, paths):
        if not paths or len(paths) > MAX_PARTS:
            raise InvalidBackup("Missing backup parts")
        self.paths, self.index, self.stream = list(paths), 0, None

    def read(self, size):
        output = bytearray()
        while len(output) < size:
            if self.stream is None:
                if self.index == len(self.paths):
                    break
                self.stream = Path(self.paths[self.index]).open("rb")
                self.index += 1
            chunk = self.stream.read(size - len(output))
            if chunk:
                output.extend(chunk)
            else:
                self.stream.close()
                self.stream = None
        return bytes(output)

    def close(self):
        if self.stream:
            self.stream.close()
