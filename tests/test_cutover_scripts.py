from __future__ import annotations

import hashlib
import os
import runpy
import shlex
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
SSH_SCRIPT = PROJECT_ROOT / "scripts" / "migrate-ssh-hook.py"
INSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "install.sh"
UNINSTALL_SCRIPT = PROJECT_ROOT / "scripts" / "uninstall.sh"
RETIRE_SCRIPT = PROJECT_ROOT / "scripts" / "retire-classic.sh"
TEST_MIGRATION_ID = "a05a540e-15ef-4121-944c-fd02616ab938"


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


def make_install_simulation(
    tmp_path: Path,
    *,
    unmanaged: bool,
    rollback_fails: bool = False,
) -> tuple[dict[str, str], Path, Path, Path, Path]:
    home = tmp_path / "home"
    data = tmp_path / "data"
    current = home / "ws"
    current.parent.mkdir(parents=True)
    current.write_text("#!/bin/sh\nprintf 'classic\\n'\n", encoding="utf-8")
    current.chmod(0o700)
    target = home / ".local" / "bin" / "WF"
    target.parent.mkdir(parents=True)
    target.symlink_to(current)
    plan = tmp_path / "plan.json"
    plan.write_text("{}\n", encoding="utf-8")
    plan.chmod(0o600)
    log = tmp_path / "wf-dev.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python3 = fake_bin / "python3"
    python3.write_text(
        textwrap.dedent(
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "${1:-}" != '-m' || "${2:-}" != 'venv' || -z "${3:-}" ]]; then
              exit 64
            fi
            venv="$3"
            mkdir -p "$venv/bin"
            cat > "$venv/bin/python" <<'PYTHON'
            #!/usr/bin/env bash
            if [[ "${1:-}" == '-m' && "${2:-}" == 'pip' ]]; then
              exit 0
            fi
            exec __REAL_PYTHON__ "$@"
            PYTHON
            cat > "$venv/bin/WF" <<'WF'
            #!/bin/sh
            exit 0
            WF
            cat > "$venv/bin/wf-dev" <<'WFDEV'
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\n' "$*" >> "$WF_TEST_LOG"
            case "${1:-}" in
              doctor)
                ;;
              migrate)
                case "${2:-}" in
                  validate)
                    printf '%s\n' '{"valid":true,"plan_id":"__MIGRATION_ID__"}'
                    ;;
                  apply)
                    ;;
                  rollback)
                    if [[ "${WF_TEST_ROLLBACK_FAIL:-0}" == '1' ]]; then
                      exit 9
                    fi
                    ;;
                  *) exit 65 ;;
                esac
                ;;
              list)
                if [[ "${WF_TEST_UNMANAGED:-0}" == '1' ]]; then
                  printf '%s\n' '[{"owned":false,"legacy_metadata":true}]'
                else
                  printf '%s\n' '[]'
                fi
                ;;
              *) exit 66 ;;
            esac
            WFDEV
            chmod 700 "$venv/bin/python" "$venv/bin/WF" "$venv/bin/wf-dev"
            """
        )
        .lstrip()
        .replace("__REAL_PYTHON__", shlex.quote(sys.executable))
        .replace("__MIGRATION_ID__", TEST_MIGRATION_ID),
        encoding="utf-8",
    )
    python3.chmod(0o700)
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_DATA_HOME": str(data),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "WF_TEST_LOG": str(log),
        "WF_TEST_UNMANAGED": "1" if unmanaged else "0",
        "WF_TEST_ROLLBACK_FAIL": "1" if rollback_fails else "0",
    }
    return env, current, target, log, plan


def test_install_completes_simulated_transaction(tmp_path: Path) -> None:
    env, current, target, log, plan = make_install_simulation(tmp_path, unmanaged=False)

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            "--approve-cutover",
            "--migration-plan",
            str(plan),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    install_root = Path(env["XDG_DATA_HOME"]) / "wf-session-manager"
    assert target.resolve() == install_root / "venv" / "bin" / "WF"
    classic = Path(env["HOME"]) / ".local" / "libexec" / "wf-classic"
    assert classic.read_bytes() == current.read_bytes()
    marker = install_root / "classic-owner"
    assert marker.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(classic.read_bytes()).hexdigest() in marker.read_text(encoding="utf-8")
    assert f"migrate apply {plan} --approve" in log.read_text(encoding="utf-8")
    assert "migrate rollback" not in log.read_text(encoding="utf-8")
    assert "tmux processes were not restarted, renamed, or terminated" in result.stdout


def test_install_rolls_back_adoption_on_pre_cutover_failure(tmp_path: Path) -> None:
    env, current, target, log, plan = make_install_simulation(tmp_path, unmanaged=True)

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            "--approve-cutover",
            "--migration-plan",
            str(plan),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "Rolled back migration" in result.stderr
    assert target.resolve() == current
    assert f"migrate rollback {TEST_MIGRATION_ID} --approve" in log.read_text(encoding="utf-8")
    marker = Path(env["XDG_DATA_HOME"]) / "wf-session-manager" / "classic-owner"
    assert not marker.exists()


def test_install_reports_failed_automatic_rollback(tmp_path: Path) -> None:
    env, current, target, log, plan = make_install_simulation(
        tmp_path,
        unmanaged=True,
        rollback_fails=True,
    )

    result = subprocess.run(
        [
            "bash",
            str(INSTALL_SCRIPT),
            "--approve-cutover",
            "--migration-plan",
            str(plan),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "Automatic rollback failed" in result.stderr
    assert target.resolve() == current
    assert f"migrate rollback {TEST_MIGRATION_ID} --approve" in log.read_text(encoding="utf-8")


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
