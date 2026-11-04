"""Real pip migration smoke test in a disposable Linux virtual environment.

Run explicitly with Python 3.14 on Linux; never uses the application's environment,
configuration, database or Telegram sessions. Network access to PyPI is required.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


def run(*args, cwd):
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def main():
    if sys.platform != "linux" or sys.version_info[:2] != (3, 14):
        raise SystemExit("Run this probe with Python 3.14 on Linux")
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="watchtower-linux-install-") as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv/bin/python"
        (root / "scripts").mkdir()
        shutil.copyfile(source / "requirements.txt", root / "requirements.txt")
        shutil.copyfile(source / "scripts/install_dependencies.py", root / "scripts/install_dependencies.py")
        verify = """
from importlib import metadata
import aiogram, pyrogram, sqlalchemy, sqlmodel, asyncpg, apscheduler, cryptography
from google import genai
from scripts import install_dependencies as installer
assert metadata.version('Kurigram') == installer.KURIGRAM_VERSION
for name in installer.LEGACY_DISTRIBUTIONS:
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError(f'Conflicting distribution still installed: {name}')
assert not installer.ensure_project_dependencies(), 'Unchanged startup must skip pip'
print('Imports, fork removal and cached restart: OK', flush=True)
"""
        for scenario in ("clean", "overlapping-legacy"):
            print(f"\nLinux installation: {scenario}", flush=True)
            if scenario == "overlapping-legacy":
                # Install overlapping files without importing/starting either old SDK.
                run(python, "-m", "pip", "install", "--index-url", "https://pypi.org/simple",
                    "--no-deps", "pyrofork==2.3.69", "Pyrogram==2.0.106", cwd=root)
            run(python, "scripts/install_dependencies.py", cwd=root)
            run(python, "-m", "pip", "check", cwd=root)
            run(python, "-X", "utf8", "-c", verify, cwd=root)
        print("Linux installation smoke test passed", flush=True)


if __name__ == "__main__":
    main()
