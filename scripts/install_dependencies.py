from __future__ import annotations

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KURIGRAM_VERSION = "2.2.26"
KURIGRAM_REQUIREMENT = f"kurigram[fast]=={KURIGRAM_VERSION}"
KURIGRAM_WHEEL_SHA256 = "f53cee6119a579b74620f45b5f83d543cd3bd510a8a6a1b4b3852e21603241e9"
LEGACY_DISTRIBUTIONS = ("pyrofork", "Pyrogram")


def _installed_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _pip(*arguments: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "--disable-pip-version-check", *arguments],
        check=True,
        cwd=PROJECT_ROOT,
    )


def _fast_packages() -> list[str]:
    packages = ["tgcrypto>=1.2.2"]
    if sys.platform in {"linux", "darwin"}:
        packages.append("uvloop>=0.21.0")
    return packages


def _missing_fast_packages() -> list[str]:
    return [package for package in _fast_packages() if _installed_version(package.split(">=")[0]) is None]


def _install_fast_dependencies() -> None:
    # Optional accelerators must not require a compiler on unattended updates.
    # Kurigram also supports pure-Python encryption and the standard asyncio loop.
    for package in _missing_fast_packages():
        try:
            _pip("install", "--index-url", "https://pypi.org/simple", "--only-binary=:all:", package)
        except subprocess.CalledProcessError:
            print(f"Optional accelerator {package} unavailable; continuing without it", flush=True)


def ensure_telegram_dependency() -> bool:
    """Keep this migration for installations updating directly from pyrofork.

    Both distributions own pyrogram files. Uninstalling pyrofork after installing
    Kurigram removes shared files, so the reviewed wheel must be installed last.
    This runs before pyrogram is imported, including after an old updater restart.
    """
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    if KURIGRAM_REQUIREMENT not in requirements:
        raise RuntimeError("Kurigram pin and reviewed migration version must be updated together")

    legacy = [name for name in LEGACY_DISTRIBUTIONS if _installed_version(name) is not None]
    if not legacy and _installed_version("Kurigram") == KURIGRAM_VERSION:
        _install_fast_dependencies()
        return False

    if "pyrogram" in sys.modules:
        raise RuntimeError("Restart Python before replacing the imported Telegram library")

    print(f"Migrating Telegram dependency to Kurigram {KURIGRAM_VERSION}", flush=True)
    with tempfile.TemporaryDirectory(prefix="watchtower_kurigram_") as directory:
        _pip(
            "download", "--index-url", "https://pypi.org/simple",
            "--no-deps", "--only-binary=:all:", "--dest", directory,
            f"kurigram=={KURIGRAM_VERSION}",
        )
        wheel = Path(directory) / f"kurigram-{KURIGRAM_VERSION}-py3-none-any.whl"
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != KURIGRAM_WHEEL_SHA256:
            raise RuntimeError("Kurigram wheel SHA-256 does not match the reviewed release")

        dependencies = ["pyaes>=1.2.0", "python-socks[asyncio]>=2.4.0"]
        _pip("install", "--index-url", "https://pypi.org/simple", *dependencies)
        _install_fast_dependencies()
        if legacy:
            _pip("uninstall", "-y", *legacy)
        _pip("install", "--no-deps", "--force-reinstall", str(wheel))

    if _installed_version("Kurigram") != KURIGRAM_VERSION:
        raise RuntimeError("Kurigram installation did not complete")
    return True


def _dependency_state() -> dict:
    requirements = (PROJECT_ROOT / "requirements.txt").read_bytes()
    installer = Path(__file__).read_bytes()
    return {
        "fingerprint": hashlib.sha256(requirements + b"\0" + installer).hexdigest(),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "python": sys.version,
        "packages": {
            distribution.metadata["Name"].lower().replace("_", "-"): distribution.version
            for distribution in metadata.distributions()
            if distribution.metadata["Name"]
        },
    }


def ensure_project_dependencies(*, force: bool = False) -> bool:
    """Bootstrap before importing the app, including after an old updater restart.

    Keep this bridge: older updaters only download source and exec main.py. They
    cannot install newly required packages themselves. Cache only a successful
    installation; a changed requirements file or environment triggers another run.
    """
    state_file = PROJECT_ROOT / "data" / "temp" / "dependency-state.json"
    current_state = _dependency_state()
    try:
        previous_state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous_state = None
    if not force and current_state == previous_state:
        return False

    print("Preparing project dependencies before application startup", flush=True)
    ensure_telegram_dependency()
    requirements = PROJECT_ROOT / "requirements.txt"
    if _missing_fast_packages():
        # Keep [fast] in the published requirements. On a platform without wheels,
        # install the same reviewed core without building optional native code.
        with tempfile.TemporaryDirectory(prefix="watchtower_requirements_") as directory:
            portable_requirements = Path(directory) / "requirements.txt"
            portable_requirements.write_text(
                requirements.read_text(encoding="utf-8").replace(
                    KURIGRAM_REQUIREMENT, f"kurigram=={KURIGRAM_VERSION}"
                ),
                encoding="utf-8",
            )
            _pip("install", "--upgrade", "--upgrade-strategy", "eager", "--index-url", "https://pypi.org/simple", "-r", str(portable_requirements))
    else:
        _pip("install", "--upgrade", "--upgrade-strategy", "eager", "--index-url", "https://pypi.org/simple", "-r", str(requirements))

    # Re-read versions after pip, and publish the marker atomically only on success.
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=state_file.parent, prefix="dependency-state-", suffix=".tmp", delete=False
    ) as stream:
        temporary_state = Path(stream.name)
        json.dump(_dependency_state(), stream, ensure_ascii=False, sort_keys=True)
    try:
        os.replace(temporary_state, state_file)
    finally:
        temporary_state.unlink(missing_ok=True)
    return True


def install_project_dependencies() -> None:
    ensure_project_dependencies(force=True)


if __name__ == "__main__":
    install_project_dependencies()
