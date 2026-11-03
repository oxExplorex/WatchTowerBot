from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from scripts import install_dependencies as migration


@pytest.fixture
def migration_environment(monkeypatch, tmp_path):
    (tmp_path / "requirements.txt").write_text(
        f"{migration.KURIGRAM_REQUIREMENT}\n", encoding="utf-8"
    )
    monkeypatch.setattr(migration, "PROJECT_ROOT", tmp_path)
    installed = {"pyrofork": "2.3.69"}
    calls = []
    wheel_content = b"reviewed-test-wheel"
    monkeypatch.setattr(migration, "KURIGRAM_WHEEL_SHA256", hashlib.sha256(wheel_content).hexdigest())
    monkeypatch.setattr(
        migration, "_installed_version",
        lambda name: "1.2.5" if name in {"tgcrypto", "uvloop"} else installed.get(name),
    )
    monkeypatch.delitem(migration.sys.modules, "pyrogram", raising=False)

    def fake_pip(*arguments):
        calls.append(arguments)
        if arguments[0] == "download":
            destination = Path(arguments[arguments.index("--dest") + 1])
            (destination / f"kurigram-{migration.KURIGRAM_VERSION}-py3-none-any.whl").write_bytes(wheel_content)
        elif arguments[0] == "uninstall":
            for name in arguments[2:]:
                installed.pop(name, None)
        elif "--force-reinstall" in arguments:
            installed["Kurigram"] = migration.KURIGRAM_VERSION

    monkeypatch.setattr(migration, "_pip", fake_pip)
    return installed, calls


def test_replacement_prepares_wheel_before_uninstall_and_installs_last(migration_environment):
    installed, calls = migration_environment
    assert migration.ensure_telegram_dependency() is True
    assert [call[0] for call in calls] == ["download", "install", "uninstall", "install"]
    assert calls[2] == ("uninstall", "-y", "pyrofork")
    assert "--force-reinstall" in calls[-1]
    assert installed == {"Kurigram": migration.KURIGRAM_VERSION}
    calls.clear()
    assert migration.ensure_telegram_dependency() is False
    assert calls == []


def test_overlapping_distributions_require_reinstallation(migration_environment):
    installed, calls = migration_environment
    installed.update(Kurigram=migration.KURIGRAM_VERSION, Pyrogram="2.0.106")
    assert migration.ensure_telegram_dependency() is True
    assert calls[2] == ("uninstall", "-y", "pyrofork", "Pyrogram")
    assert "--force-reinstall" in calls[-1]


def test_hash_mismatch_does_not_change_installed_packages(monkeypatch, migration_environment):
    installed, calls = migration_environment
    monkeypatch.setattr(migration, "KURIGRAM_WHEEL_SHA256", "0" * 64)
    with pytest.raises(RuntimeError, match="SHA-256"):
        migration.ensure_telegram_dependency()
    assert [call[0] for call in calls] == ["download"]
    assert installed == {"pyrofork": "2.3.69"}


def test_download_failure_does_not_uninstall(monkeypatch, migration_environment):
    installed, _ = migration_environment

    def fail_download(*arguments):
        raise subprocess.CalledProcessError(1, arguments)

    monkeypatch.setattr(migration, "_pip", fail_download)
    with pytest.raises(subprocess.CalledProcessError):
        migration.ensure_telegram_dependency()
    assert installed == {"pyrofork": "2.3.69"}


def test_imported_library_cannot_be_replaced(monkeypatch, migration_environment):
    _, calls = migration_environment
    monkeypatch.setitem(migration.sys.modules, "pyrogram", object())
    with pytest.raises(RuntimeError, match="Restart Python"):
        migration.ensure_telegram_dependency()
    assert calls == []


def test_pin_change_requires_review(migration_environment):
    _, calls = migration_environment
    (migration.PROJECT_ROOT / "requirements.txt").write_text("kurigram==9.9.9\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="reviewed migration version"):
        migration.ensure_telegram_dependency()
    assert calls == []


def test_missing_installation_is_repaired(migration_environment):
    installed, calls = migration_environment
    installed.clear()
    assert migration.ensure_telegram_dependency() is True
    assert all(call[0] != "uninstall" for call in calls)
    assert installed["Kurigram"] == migration.KURIGRAM_VERSION


def test_dependency_failure_keeps_legacy_installation(monkeypatch, migration_environment):
    installed, calls = migration_environment
    original_pip = migration._pip

    def fail_dependency_install(*arguments):
        if arguments[0] == "install":
            raise subprocess.CalledProcessError(1, arguments)
        original_pip(*arguments)

    monkeypatch.setattr(migration, "_pip", fail_dependency_install)
    with pytest.raises(subprocess.CalledProcessError):
        migration.ensure_telegram_dependency()
    assert installed == {"pyrofork": "2.3.69"}
    assert all(call[0] != "uninstall" for call in calls)


def test_interrupted_replacement_can_be_retried(monkeypatch, migration_environment):
    installed, _ = migration_environment
    original_pip = migration._pip

    def fail_wheel_install(*arguments):
        if "--force-reinstall" in arguments:
            raise subprocess.CalledProcessError(1, arguments)
        original_pip(*arguments)

    monkeypatch.setattr(migration, "_pip", fail_wheel_install)
    with pytest.raises(subprocess.CalledProcessError):
        migration.ensure_telegram_dependency()
    assert installed == {}
    monkeypatch.setattr(migration, "_pip", original_pip)
    assert migration.ensure_telegram_dependency() is True
    assert installed == {"Kurigram": migration.KURIGRAM_VERSION}


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_missing_fast_dependency_is_installed_without_replacing_core(monkeypatch, migration_environment, platform):
    installed, calls = migration_environment
    installed.clear()
    installed["Kurigram"] = migration.KURIGRAM_VERSION
    monkeypatch.setattr(migration.sys, "platform", platform)
    monkeypatch.setattr(migration, "_installed_version", installed.get)
    assert migration.ensure_telegram_dependency() is False
    assert calls == [
        ("install", "--index-url", "https://pypi.org/simple", "--only-binary=:all:", package)
        for package in migration._fast_packages()
    ]


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_uvloop_is_only_required_on_supported_platforms(monkeypatch, migration_environment, platform):
    installed, calls = migration_environment
    installed.clear()
    installed.update(Kurigram=migration.KURIGRAM_VERSION, tgcrypto="1.2.5")
    monkeypatch.setattr(migration.sys, "platform", platform)
    monkeypatch.setattr(migration, "_installed_version", installed.get)
    assert migration.ensure_telegram_dependency() is False
    assert bool(calls) is (platform in {"linux", "darwin"})
