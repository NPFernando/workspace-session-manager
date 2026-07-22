"""Ambient VM health checks: apt updates, reboot flag, dirty repos, Docker.

Each check is isolated and non-fatal: a missing tool, a daemon that is not
running, or a permission error becomes an INFO/WARN `HealthCheck`, never an
exception. No check here is safe to call from a startup path — callers must
run these from a background worker, never synchronously on first paint.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from workspace_session_manager.models import HealthCheck, HealthStatus
from workspace_session_manager.tmux import Runner, subprocess_runner


def reboot_required_check(flag_path: Path = Path("/var/run/reboot-required")) -> HealthCheck:
    if flag_path.is_file():
        return HealthCheck(
            name="reboot-required",
            status=HealthStatus.WARN,
            detail=f"{flag_path} present",
            corrective_action="Reboot the host when convenient.",
        )
    return HealthCheck(name="reboot-required", status=HealthStatus.PASS, detail="no reboot pending")


def apt_updates_check(
    runner: Runner = subprocess_runner,
    *,
    timeout: float = 5.0,
    apt_check: Path = Path("/usr/lib/update-notifier/apt_check.py"),
) -> HealthCheck:
    if not apt_check.is_file():
        return HealthCheck(
            name="apt-updates",
            status=HealthStatus.INFO,
            detail="apt update-notifier not available on this system",
        )
    try:
        result = runner((str(apt_check),), capture=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return HealthCheck(
            name="apt-updates",
            status=HealthStatus.INFO,
            detail=f"apt check failed: {error}",
        )
    # apt_check.py writes its "updates;security_updates" counts to stderr, not stdout.
    parsed = _parse_apt_counts(result.stderr) or _parse_apt_counts(result.stdout)
    if parsed is None:
        raw = (result.stderr or result.stdout).strip()[:80]
        return HealthCheck(
            name="apt-updates",
            status=HealthStatus.INFO,
            detail=f"unrecognized apt_check.py output: {raw!r}",
        )
    total, security = parsed
    if total == 0:
        return HealthCheck(
            name="apt-updates", status=HealthStatus.PASS, detail="no updates pending"
        )
    if security > 0:
        return HealthCheck(
            name="apt-updates",
            status=HealthStatus.WARN,
            detail=f"{total} update(s) pending, {security} security",
            corrective_action="Run apt update && apt upgrade.",
        )
    return HealthCheck(
        name="apt-updates",
        status=HealthStatus.INFO,
        detail=f"{total} update(s) pending",
    )


def _parse_apt_counts(stdout: str) -> tuple[int, int] | None:
    parts = stdout.strip().split(";")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def docker_containers_check(
    runner: Runner = subprocess_runner,
    *,
    timeout: float = 5.0,
) -> HealthCheck:
    if shutil.which("docker") is None:
        return HealthCheck(
            name="docker-containers", status=HealthStatus.INFO, detail="docker not installed"
        )
    try:
        result = runner(("docker", "ps", "--format", "{{.Names}}"), capture=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return HealthCheck(
            name="docker-containers",
            status=HealthStatus.INFO,
            detail=f"docker unavailable: {error}",
        )
    if result.returncode != 0:
        return HealthCheck(
            name="docker-containers",
            status=HealthStatus.INFO,
            detail="docker unavailable (daemon not running or permission denied)",
        )
    names = [line for line in result.stdout.splitlines() if line.strip()]
    return HealthCheck(
        name="docker-containers",
        status=HealthStatus.INFO,
        detail=f"{len(names)} running" if names else "none running",
    )


def git_dirty_repos_check(
    scan_roots: Sequence[Path],
    *,
    runner: Runner = subprocess_runner,
    budget: int = 20,
    timeout: float = 5.0,
) -> HealthCheck:
    if shutil.which("git") is None:
        return HealthCheck(name="git-dirty", status=HealthStatus.INFO, detail="git not installed")

    repos: list[Path] = []
    for root in scan_roots:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if len(repos) >= budget:
                break
            if (child / ".git").exists():
                repos.append(child)
        if len(repos) >= budget:
            break

    dirty: list[str] = []
    for repo in repos:
        try:
            result = runner(
                ("git", "-C", str(repo), "status", "--porcelain"),
                capture=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.strip():
            dirty.append(repo.name)

    if not dirty:
        return HealthCheck(
            name="git-dirty", status=HealthStatus.PASS, detail=f"{len(repos)} repo(s) clean"
        )
    return HealthCheck(
        name="git-dirty",
        status=HealthStatus.WARN,
        detail=f"{len(dirty)} dirty repo(s): {', '.join(dirty[:5])}"
        + (f", and {len(dirty) - 5} more" if len(dirty) > 5 else ""),
        corrective_action="Commit or stash pending changes.",
    )
