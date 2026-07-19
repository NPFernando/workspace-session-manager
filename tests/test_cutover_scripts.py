from __future__ import annotations

import hashlib
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
SSH_SCRIPT = PROJECT_ROOT / "scripts" / "migrate-ssh-hook.py"
INSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "install.sh"
UNINSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "uninstall.sh"
RETIRE_SCRIPT = PROJECT_ROOT / "scripts" / "retire-classic.sh"


@pytest.mark.parametrize(
    "script",
    (
        INSTALL_SCRIPT,
        UNINSTALL_SCRIPT,
        RETIRE_SCRIPT,
    ),
)
def test_shell_script_syntax(script: Path) -> None:
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_ssh_hook_migration_is_dry_run_then_exact_and_backed_up(tmp_path: Path) -> None:
    definitions = runpy.run_path(str(SSH_SCRIPT))
    old_hook = definitions["OLD_HOOK"]
    new_hook = definitions["NEW_HOOK"]
    profile = tmp_path / ".bashrc"
    original = f"export PATH=/bin\n\n{old_hook}\n# tail\n"
    profile.write_text(original, encoding="utf-8")
    profile.chmod(0o640)

    preview = subprocess.run(
        [sys.executable, str(SSH_SCRIPT), "--profile", str(profile)],
        capture_output=True,
        text=True,
    )
    assert preview.returncode == 0, preview.stderr
    assert "Dry run" in preview.stdout
    assert profile.read_text(encoding="utf-8") == original

    applied = subprocess.run(
        [
            sys.executable,
            str(SSH_SCRIPT),
            "--profile",
            str(profile),
            "--approve-cutover",
        ],
        capture_output=True,
        text=True,
    )
    assert applied.returncode == 0, applied.stderr
    assert new_hook in profile.read_text(encoding="utf-8")
    assert old_hook not in profile.read_text(encoding="utf-8")
    backups = list(tmp_path.glob(".bashrc.wf-pre-cutover.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert backups[0].stat().st_mode & 0o777 == 0o640


def test_ssh_hook_migration_refuses_unassessed_content(tmp_path: Path) -> None:
    profile = tmp_path / ".bashrc"
    profile.write_text("# different startup hook\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SSH_SCRIPT),
            "--profile",
            str(profile),
            "--approve-cutover",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Expected the assessed SSH hook" in result.stderr


def make_retirement_fixture(tmp_path: Path, *, age_days: int) -> tuple[dict[str, str], Path]:
    home = tmp_path / "home"
    data = tmp_path / "data"
    classic = home / ".local" / "libexec" / "wf-classic"
    classic.parent.mkdir(parents=True)
    classic.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    classic.chmod(0o700)
    marker = data / "wf-session-manager" / "classic-owner"
    marker.parent.mkdir(parents=True)
    digest = hashlib.sha256(classic.read_bytes()).hexdigest()
    marker.write_text(
        f"schema=1\ncutover_epoch={int(time.time()) - age_days * 24 * 60 * 60}\nsha256={digest}\n",
        encoding="utf-8",
    )
    marker.chmod(0o600)
    expected = data / "wf-session-manager" / "venv" / "bin" / "WF"
    expected.parent.mkdir(parents=True)
    expected.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    expected.chmod(0o700)
    target = home / ".local" / "bin" / "WF"
    target.parent.mkdir(parents=True)
    target.symlink_to(expected)
    env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(data)}
    return env, classic


def test_install_refuses_mismatched_existing_classic(tmp_path: Path) -> None:
    home = tmp_path / "home"
    data = tmp_path / "data"
    current = home / "ws"
    current.parent.mkdir(parents=True)
    current.write_text("#!/bin/sh\nprintf 'current\\n'\n", encoding="utf-8")
    current.chmod(0o700)
    target = home / ".local" / "bin" / "WF"
    target.parent.mkdir(parents=True)
    target.symlink_to(current)
    classic = home / ".local" / "libexec" / "wf-classic"
    classic.parent.mkdir(parents=True)
    classic.write_text("#!/bin/sh\nprintf 'different\\n'\n", encoding="utf-8")
    classic.chmod(0o700)
    env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(data)}

    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--approve-cutover"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "does not match current WF" in result.stderr
    assert target.resolve() == current
    assert "different" in classic.read_text(encoding="utf-8")
    assert not (data / "wf-session-manager" / "classic-owner").exists()


def test_uninstall_restores_only_checksum_verified_classic(tmp_path: Path) -> None:
    env, classic = make_retirement_fixture(tmp_path, age_days=1)
    target = Path(env["HOME"]) / ".local" / "bin" / "WF"

    restored = subprocess.run(
        ["bash", str(UNINSTALL_SCRIPT), "--restore-classic"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert restored.returncode == 0, restored.stderr
    assert target.resolve() == classic


def test_uninstall_refuses_modified_classic(tmp_path: Path) -> None:
    env, classic = make_retirement_fixture(tmp_path, age_days=1)
    target = Path(env["HOME"]) / ".local" / "bin" / "WF"
    expected = target.resolve()
    classic.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(UNINSTALL_SCRIPT), "--restore-classic"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "preserved executable changed" in result.stderr
    assert target.resolve() == expected


def test_uninstall_refuses_non_private_classic(tmp_path: Path) -> None:
    env, classic = make_retirement_fixture(tmp_path, age_days=1)
    target = Path(env["HOME"]) / ".local" / "bin" / "WF"
    expected = target.resolve()
    classic.chmod(0o755)

    result = subprocess.run(
        ["bash", str(UNINSTALL_SCRIPT), "--restore-classic"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "Classic executable is unavailable" in result.stderr
    assert target.resolve() == expected


def test_classic_retirement_archives_only_installer_owned_copy(tmp_path: Path) -> None:
    env, classic = make_retirement_fixture(tmp_path, age_days=8)
    preview = subprocess.run(["bash", str(RETIRE_SCRIPT)], capture_output=True, text=True, env=env)
    assert preview.returncode == 0, preview.stderr
    assert "Dry run" in preview.stdout
    assert classic.exists()

    applied = subprocess.run(
        ["bash", str(RETIRE_SCRIPT), "--approve-retirement"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert applied.returncode == 0, applied.stderr
    assert not classic.exists()
    archive_dir = Path(env["XDG_DATA_HOME"]) / "wf-session-manager" / "classic-archive"
    assert len(list(archive_dir.glob("*.tar.gz"))) == 1
    assert len(list(archive_dir.glob("*.tar.gz.sha256"))) == 1


def test_classic_retirement_enforces_soak_period(tmp_path: Path) -> None:
    env, classic = make_retirement_fixture(tmp_path, age_days=1)
    result = subprocess.run(
        ["bash", str(RETIRE_SCRIPT), "--approve-retirement"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "seven-day soak" in result.stderr
    assert classic.exists()


def test_classic_retirement_refuses_when_classic_is_active(tmp_path: Path) -> None:
    env, classic = make_retirement_fixture(tmp_path, age_days=8)
    target = Path(env["HOME"]) / ".local" / "bin" / "WF"
    target.unlink()
    target.symlink_to(classic)

    result = subprocess.run(
        ["bash", str(RETIRE_SCRIPT), "--approve-retirement"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "new WF installation is not active" in result.stderr
    assert classic.exists()


def test_classic_retirement_refuses_non_private_marker(tmp_path: Path) -> None:
    env, classic = make_retirement_fixture(tmp_path, age_days=8)
    marker = Path(env["XDG_DATA_HOME"]) / "wf-session-manager" / "classic-owner"
    marker.chmod(0o644)

    result = subprocess.run(
        ["bash", str(RETIRE_SCRIPT), "--approve-retirement"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "installer ownership marker" in result.stderr
    assert classic.exists()
