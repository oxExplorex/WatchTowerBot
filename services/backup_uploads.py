"""Durable ciphertext-only uploads, resumable after FSM/process restart."""
from pathlib import Path
import os
import shutil

from core.backup_format import InvalidBackup
from core.backup_parts import PART_SIZE, parse_part_name

BACKUP_ROOT = Path(__file__).resolve().parents[1] / "data" / "backups"


def upload_directory(owner_id, identity):
    if type(owner_id) is not int or owner_id <= 0:
        raise InvalidBackup("Invalid owner")
    # Reuse the filename parser for a strict hexadecimal identity check.
    parse_part_name(f"watchtower-{identity}-0001-of-0001.wtb")
    root = BACKUP_ROOT / "incoming" / str(owner_id) / identity
    if any(path.is_symlink() for path in (BACKUP_ROOT, root.parent.parent, root.parent, root)):
        raise InvalidBackup("Unsafe upload directory")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


class _LimitedWriter:
    def __init__(self, stream):
        self.stream, self.written = stream, 0

    def write(self, data):
        if self.written + len(data) > PART_SIZE:
            raise InvalidBackup("Backup part exceeds size limit")
        self.written += len(data)
        return self.stream.write(data)

    def flush(self):
        self.stream.flush()


async def receive_part(bot, owner_id, document):
    identity, index, total = parse_part_name(document.file_name)
    if document.file_size is None or not 0 < document.file_size <= PART_SIZE:
        raise InvalidBackup("Invalid backup part size")
    root = upload_directory(owner_id, identity)
    count_file = root / "total.txt"
    if count_file.is_symlink():
        raise InvalidBackup("Unsafe upload metadata")
    if count_file.exists() and count_file.read_text(encoding="ascii") != str(total):
        raise InvalidBackup("Conflicting part counts")
    if shutil.disk_usage(root).free < document.file_size + 128 * 1024 * 1024:
        raise InvalidBackup("Not enough disk space")
    count_file.write_text(str(total), encoding="ascii")
    temporary, target = root / f"{index:04d}.upload", root / f"{index:04d}.wtb"
    if temporary.is_symlink() or target.is_symlink() or count_file.is_symlink():
        raise InvalidBackup("Unsafe upload path")
    try:
        with temporary.open("wb") as stream:
            writer = _LimitedWriter(stream)
            await bot.download(document, destination=writer, seek=False, timeout=180)
            if writer.written != document.file_size:
                raise InvalidBackup("Incomplete upload")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    received = sum((root / f"{number:04d}.wtb").is_file() for number in range(1, total + 1))
    return identity, received, total


def collect_parts(owner_id, identity, total):
    root = upload_directory(owner_id, identity)
    if (root / "total.txt").is_symlink():
        raise InvalidBackup("Unsafe upload metadata")
    if (root / "total.txt").read_text(encoding="ascii") != str(total):
        raise InvalidBackup("Conflicting part counts")
    paths = [root / f"{index:04d}.wtb" for index in range(1, total + 1)]
    if not paths or any(path.is_symlink() or not path.is_file() for path in paths):
        raise InvalidBackup("Missing backup parts")
    return paths


def discard_upload(owner_id, identity):
    root = upload_directory(owner_id, identity)
    if root.resolve().parent != (BACKUP_ROOT / "incoming" / str(owner_id)).resolve():
        raise InvalidBackup("Unsafe cleanup path")
    shutil.rmtree(root)
