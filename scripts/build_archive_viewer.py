"""Build on Windows with a dedicated environment; publish no files automatically."""
import argparse
import hashlib
import platform
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archive_viewer.distribution import EXECUTABLE, WINDOWS_ARCHIVE


def main():
    parser = argparse.ArgumentParser(description="Build standalone Windows x64 archive viewer")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "archive-viewer")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Build the Windows x64 viewer using Windows x64 Python.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="watchtower-viewer-build-") as directory:
        build = Path(directory)
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
            "--noupx", "--name", Path(EXECUTABLE).stem, "--paths", str(ROOT),
            "--add-data", f"{ROOT / 'archive_viewer' / 'assets'}:archive_viewer/assets",
            "--distpath", str(build / "dist"), "--workpath", str(build / "work"),
            "--specpath", str(build), str(ROOT / "scripts" / "viewer_entry.py")], check=True, cwd=ROOT)
        executable = build / "dist" / EXECUTABLE
        # Run the frozen program outside the checkout: bundled assets and crypto must stand alone.
        subprocess.run([str(executable), "--self-test"], check=True, cwd=build, timeout=60)
        target = output / WINDOWS_ARCHIVE
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(executable, EXECUTABLE)
            archive.write(ROOT / "archive_viewer" / "README.md", "README.md")
        with target.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        target.with_suffix(".zip.sha256").write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
        print(f"Built and checked: {target}")


if __name__ == "__main__":
    main()
