"""Optional startup update, before an archive or secret is opened. Windows EXE only."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.request import Request, urlopen
import zipfile

from archive_viewer.distribution import EXECUTABLE, RELEASE_TAG, WINDOWS_ARCHIVE

BUILD_INFO = Path(__file__).with_name("build_info.json")
MAX_DOWNLOAD = 100 * 1024 * 1024


def validate_manifest(value, current):
    if (not isinstance(value, dict) or value.get("repository") != current["repository"]
            or value.get("archive") != WINDOWS_ARCHIVE
            or type(value.get("built_at")) is not int
            or type(value.get("size")) is not int or not 0 < value["size"] <= MAX_DOWNLOAD
            or not isinstance(value.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            or not isinstance(value.get("version"), str) or not 1 <= len(value["version"]) <= 128):
        raise ValueError("Invalid viewer update manifest")
    return value["version"] != current["version"] and value["built_at"] > current["built_at"]


def unpack_update(path, destination, manifest):
    if path.stat().st_size != manifest["size"]:
        raise ValueError("Incomplete update")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["sha256"]:
            raise ValueError("Update checksum mismatch")
    with zipfile.ZipFile(path) as archive:
        entries = [item for item in archive.infolist() if item.filename == EXECUTABLE]
        if len(entries) != 1 or not 1 <= entries[0].file_size <= 150 * 1024 * 1024:
            raise ValueError("Missing executable")
        with archive.open(entries[0]) as source, destination.open("xb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
    with destination.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Invalid Windows executable")


def maybe_update(archive_path=None):
    if sys.platform != "win32" or not getattr(sys, "frozen", False) or not BUILD_INFO.is_file():
        return False
    target = Path(sys.executable).resolve()
    try:
        current = json.loads(BUILD_INFO.read_text(encoding="utf-8"))
        repository = current["repository"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            return False
        base = f"https://github.com/{repository}/releases/download/{RELEASE_TAG}/"
        with urlopen(Request(base + "viewer-update.json", headers={"User-Agent": "WatchTowerViewer"}), timeout=3) as response:
            raw = response.read(16385)
            if len(raw) > 16384:
                raise ValueError("Oversized update manifest")
            manifest = json.loads(raw)
        if not validate_manifest(manifest, current):
            return False
        print("Доступно обновление просмотрщика. Скачиваю и проверяю…", flush=True)
        cache = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "WatchTowerViewer" / "updates"
        cache.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="download-", dir=cache) as directory:
            root = Path(directory)
            download = root / WINDOWS_ARCHIVE
            with urlopen(Request(base + WINDOWS_ARCHIVE, headers={"User-Agent": "WatchTowerViewer"}), timeout=30) as response, download.open("xb") as output:
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > manifest["size"]:
                        raise ValueError("Oversized update")
                    output.write(chunk)
            candidate = root / EXECUTABLE
            unpack_update(download, candidate, manifest)
            flags = subprocess.CREATE_NO_WINDOW
            subprocess.run([str(candidate), "--self-test"], check=True, timeout=60,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            staging = cache / EXECUTABLE
            if staging.resolve() == target:
                return False
            os.replace(candidate, staging)
        command = [str(staging), "--apply-update", str(target), str(os.getpid())]
        if archive_path:
            command.append(str(Path(archive_path).resolve()))
        subprocess.Popen(command, close_fds=True, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as error:
        # Update connectivity is optional; never include user paths/secrets in output.
        print(f"Обновление недоступно ({type(error).__name__}). Открываю установленную версию.")
        return False


def apply_update(target, parent_pid, archive_path=None):
    """The downloaded EXE waits for the old process, atomically replaces it and reopens."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("Executable updates require Windows")
    target = Path(target).resolve(strict=True)
    source = Path(sys.executable).resolve(strict=True)
    if target == source or target.suffix.lower() != ".exe":
        raise ValueError("Invalid update target")
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    process = kernel.OpenProcess(0x00100000, False, int(parent_pid))
    if process:
        try:
            if kernel.WaitForSingleObject(process, 30000) == 0x102:
                return
        finally:
            kernel.CloseHandle(process)
    backup = target.with_suffix(".exe.previous")
    installed = False
    # PyInstaller's bootloader parent may hold the old file briefly after Python exits.
    for _ in range(30):
        try:
            with TemporaryDirectory(prefix="viewer-update-", dir=target.parent) as directory:
                candidate = Path(directory) / EXECUTABLE
                shutil.copy2(source, candidate)
                shutil.copy2(target, backup)
                os.replace(candidate, target)
            installed = True
            break
        except PermissionError:
            time.sleep(0.5)
        except OSError:
            break
    command = [str(target), "--no-update"]
    if archive_path:
        command.append(archive_path)
    subprocess.Popen(command, close_fds=True)
    return installed
