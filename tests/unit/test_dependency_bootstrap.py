from __future__ import annotations

import builtins
import json
from pathlib import Path
import runpy
import subprocess
from unittest.mock import Mock

import pytest

from scripts import install_dependencies as installer
from scripts import startup_status


@pytest.fixture(autouse=True)
def no_live_bootstrap_notifications(monkeypatch):
    monkeypatch.setattr(startup_status, "start_bootstrap_notifications", Mock(return_value=Mock()))


@pytest.fixture
def bootstrap(monkeypatch, tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(f"{installer.KURIGRAM_REQUIREMENT}\ngoogle-genai==2.34.0\n", encoding="utf-8")
    monkeypatch.setattr(installer, "PROJECT_ROOT", tmp_path)
    versions = {"Kurigram": installer.KURIGRAM_VERSION, "google-genai": "1.0.0"}
    monkeypatch.setattr(installer, "_installed_version", lambda name: versions.get(name, "1.2.5"))

    class Distribution:
        def __init__(self, name, version):
            self.metadata = {"Name": name}
            self.version = version

    monkeypatch.setattr(
        installer.metadata, "distributions",
        lambda: [Distribution(name, version) for name, version in versions.items()],
    )
    telegram = Mock()
    monkeypatch.setattr(installer, "ensure_telegram_dependency", telegram)

    def install(*args):
        versions["google-genai"] = "2.34.0"

    pip = Mock(side_effect=install)
    monkeypatch.setattr(installer, "_pip", pip)
    return requirements, versions, telegram, pip


def test_old_updater_restart_installs_all_requirements_once(bootstrap):
    requirements, versions, telegram, pip = bootstrap
    assert installer.ensure_project_dependencies() is True
    telegram.assert_called_once_with()
    pip.assert_called_once()
    arguments = pip.call_args.args
    assert arguments[:3] == ("install", "--index-url", "https://pypi.org/simple")
    assert "--upgrade" not in arguments
    assert "--constraint" in arguments and arguments[-2] == "-r"
    marker = installer.PROJECT_ROOT / "data/temp/dependency-state.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["packages"]["google-genai"] == "2.34.0"
    assert versions["google-genai"] == "2.34.0"
    telegram.reset_mock()
    pip.reset_mock()
    assert installer.ensure_project_dependencies() is False
    telegram.assert_not_called()
    pip.assert_not_called()


@pytest.mark.parametrize("change", ["requirements", "package", "interpreter", "broken-marker"])
def test_changed_installation_is_reconciled_again(monkeypatch, bootstrap, change):
    requirements, versions, _, pip = bootstrap
    installer.ensure_project_dependencies()
    pip.reset_mock()
    if change == "requirements":
        requirements.write_text(requirements.read_text(encoding="utf-8") + "sqlmodel==0.0.48\n", encoding="utf-8")
    elif change == "package":
        versions.pop("google-genai")
    elif change == "interpreter":
        monkeypatch.setattr(installer.sys, "prefix", "another-environment")
    else:
        (installer.PROJECT_ROOT / "data/temp/dependency-state.json").write_text("broken", encoding="utf-8")
    assert installer.ensure_project_dependencies() is True
    pip.assert_called_once()


def test_failed_install_is_not_cached_and_can_be_retried(bootstrap):
    _, _, _, pip = bootstrap
    pip.side_effect = subprocess.CalledProcessError(1, "pip")
    with pytest.raises(subprocess.CalledProcessError):
        installer.ensure_project_dependencies()
    assert not (installer.PROJECT_ROOT / "data/temp/dependency-state.json").exists()
    pip.side_effect = None
    assert installer.ensure_project_dependencies() is True


def test_explicit_installer_reuses_valid_cache(monkeypatch, bootstrap):
    installer.ensure_project_dependencies()
    bootstrap[-1].reset_mock()
    monkeypatch.setattr(installer.sys, "argv", ["install_dependencies.py"])
    installer.install_project_dependencies()
    bootstrap[-1].assert_not_called()
    monkeypatch.setattr(installer.sys, "argv", ["install_dependencies.py", "--force"])
    installer.install_project_dependencies()
    bootstrap[-1].assert_called_once()


def test_failed_new_release_does_not_turn_old_marker_into_success(bootstrap):
    requirements, _, _, pip = bootstrap
    installer.ensure_project_dependencies()
    marker = installer.PROJECT_ROOT / "data/temp/dependency-state.json"
    old_marker = marker.read_bytes()
    requirements.write_text(requirements.read_text(encoding="utf-8") + "sqlmodel==0.0.48\n", encoding="utf-8")
    pip.side_effect = subprocess.CalledProcessError(1, "pip")
    with pytest.raises(subprocess.CalledProcessError):
        installer.ensure_project_dependencies()
    assert marker.read_bytes() == old_marker
    pip.side_effect = None
    assert installer.ensure_project_dependencies() is True
    assert marker.read_bytes() != old_marker


def test_no_native_wheel_uses_core_requirements_and_caches_fallback(monkeypatch, bootstrap):
    _, _, _, pip = bootstrap
    monkeypatch.setattr(installer, "_missing_fast_packages", lambda: ["tgcrypto>=1.2.2"])
    captured = []

    def install(*args):
        captured.append((Path(args[-1]).read_text(encoding="utf-8"),
                         Path(args[args.index("--constraint") + 1]).read_text(encoding="utf-8")))

    pip.side_effect = install
    assert installer.ensure_project_dependencies() is True
    requirements, constraints = captured[0]
    assert "kurigram" not in requirements
    assert f"kurigram=={installer.KURIGRAM_VERSION}" in constraints and "[fast]" not in constraints
    assert "google-genai==2.34.0" in requirements
    assert installer.ensure_project_dependencies() is False
    pip.assert_called_once()


def test_missing_accelerator_is_optional(monkeypatch):
    monkeypatch.setattr(installer, "_missing_fast_packages", lambda: ["tgcrypto>=1.2.2", "uvloop>=0.21.0"])
    pip = Mock(side_effect=subprocess.CalledProcessError(1, "pip"))
    monkeypatch.setattr(installer, "_pip", pip)
    installer._install_fast_dependencies()
    assert pip.call_count == 2
    assert all("--only-binary=:all:" in call.args for call in pip.call_args_list)


def test_one_resolver_pass_has_full_constraints_and_truthful_progress(monkeypatch, bootstrap):
    requirements, _, _, pip = bootstrap
    lines = [installer.KURIGRAM_REQUIREMENT] + [f"package{i}[extra]==1.0" for i in range(12)]
    requirements.write_text("\n".join(lines) + "\n", encoding="utf-8")
    batches, constraints, progress = [], [], []

    def install(*args):
        batches.append(Path(args[-1]).read_text(encoding="utf-8").splitlines())
        constraints.append(Path(args[args.index("--constraint") + 1]).read_text(encoding="utf-8"))

    pip.side_effect = install
    installer.ensure_project_dependencies(progress=lambda *args: progress.append(args))
    assert list(map(len, batches)) == [12]
    assert [item for batch in batches for item in batch] == lines[1:]
    assert all("kurigram==" in value and "[extra]" not in value for value in constraints)
    assert [entry[0] for entry in progress if len(entry) == 2] == [13]
    assert progress[-1] == (13, 13)


def test_main_bootstrap_runs_before_third_party_imports(monkeypatch):
    class BootstrapReached(Exception):
        pass

    def bootstrap(**kwargs):
        raise BootstrapReached

    monkeypatch.setattr(installer, "ensure_project_dependencies", bootstrap)
    original_import = builtins.__import__

    def guard(name, *args, **kwargs):
        assert name.split(".")[0] not in {"aiogram", "pyrogram", "sqlalchemy", "google"}
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    with pytest.raises(BootstrapReached):
        runpy.run_path(str(Path(__file__).resolve().parents[2] / "main.py"), run_name="__main__")


def test_main_does_not_continue_after_installation_failure(monkeypatch):
    failure = subprocess.CalledProcessError(1, "pip")
    monkeypatch.setattr(installer, "ensure_project_dependencies", Mock(side_effect=failure))
    with pytest.raises(subprocess.CalledProcessError) as caught:
        runpy.run_path(str(Path(__file__).resolve().parents[2] / "main.py"), run_name="__main__")
    assert caught.value is failure
