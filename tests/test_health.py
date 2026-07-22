import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from workspace_session_manager.health import (
    apt_updates_check,
    docker_containers_check,
    git_dirty_repos_check,
    reboot_required_check,
)
from workspace_session_manager.models import HealthStatus


class ScriptedRunner:
    """A Runner whose response depends on the invoked command, for tests that
    need different fake subprocess behavior per external tool."""

    def __init__(
        self, respond: Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
    ) -> None:
        self._respond = respond
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        args: Sequence[str],
        *,
        capture: bool = True,
        timeout: float | None = 5.0,
    ) -> subprocess.CompletedProcess[str]:
        del capture, timeout
        self.calls.append(tuple(args))
        return self._respond(args)


def _completed(args: Sequence[str], *, stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_reboot_required_check_pass_when_flag_absent(tmp_path: Path) -> None:
    check = reboot_required_check(tmp_path / "reboot-required")
    assert check.status is HealthStatus.PASS


def test_reboot_required_check_warns_when_flag_present(tmp_path: Path) -> None:
    flag = tmp_path / "reboot-required"
    flag.write_text("*** System restart required ***\n", encoding="utf-8")
    check = reboot_required_check(flag)
    assert check.status is HealthStatus.WARN
    assert check.corrective_action


def test_apt_updates_check_missing_tool_is_info(tmp_path: Path) -> None:
    check = apt_updates_check(apt_check=tmp_path / "does-not-exist.py")
    assert check.status is HealthStatus.INFO


def test_apt_updates_check_parses_stderr_counts(tmp_path: Path) -> None:
    fake = tmp_path / "apt_check.py"
    fake.write_text("#!/bin/true\n", encoding="utf-8")
    fake.chmod(0o755)
    runner = ScriptedRunner(lambda args: _completed(args, stderr="0;0"))
    check = apt_updates_check(runner, apt_check=fake)
    assert check.status is HealthStatus.PASS


def test_apt_updates_check_warns_on_security_updates(tmp_path: Path) -> None:
    fake = tmp_path / "apt_check.py"
    fake.write_text("#!/bin/true\n", encoding="utf-8")
    fake.chmod(0o755)
    runner = ScriptedRunner(lambda args: _completed(args, stderr="5;2"))
    check = apt_updates_check(runner, apt_check=fake)
    assert check.status is HealthStatus.WARN
    assert "security" in check.detail


def test_apt_updates_check_info_when_only_ordinary_updates(tmp_path: Path) -> None:
    fake = tmp_path / "apt_check.py"
    fake.write_text("#!/bin/true\n", encoding="utf-8")
    fake.chmod(0o755)
    runner = ScriptedRunner(lambda args: _completed(args, stderr="3;0"))
    check = apt_updates_check(runner, apt_check=fake)
    assert check.status is HealthStatus.INFO


def test_apt_updates_check_isolates_subprocess_failure(tmp_path: Path) -> None:
    fake = tmp_path / "apt_check.py"
    fake.write_text("#!/bin/true\n", encoding="utf-8")
    fake.chmod(0o755)

    def raise_timeout(
        args: Sequence[str], *, capture: bool = True, timeout: float | None = 5.0
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=list(args), timeout=5.0)

    check = apt_updates_check(raise_timeout, apt_check=fake)
    assert check.status is HealthStatus.INFO


def test_docker_containers_check_counts_running(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")
    runner = ScriptedRunner(lambda args: _completed(args, stdout="a\nb\nc\n"))
    check = docker_containers_check(runner)
    assert check.status is HealthStatus.INFO
    assert "3 running" in check.detail


def test_docker_containers_check_none_installed(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    check = docker_containers_check()
    assert check.status is HealthStatus.INFO
    assert "not installed" in check.detail


def test_docker_containers_check_daemon_down_is_info(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")
    runner = ScriptedRunner(lambda args: _completed(args, returncode=1, stderr="permission denied"))
    check = docker_containers_check(runner)
    assert check.status is HealthStatus.INFO


def test_git_dirty_repos_check_clean(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git")
    repo = tmp_path / "repo-one"
    (repo / ".git").mkdir(parents=True)
    runner = ScriptedRunner(lambda args: _completed(args, stdout=""))
    check = git_dirty_repos_check([tmp_path], runner=runner)
    assert check.status is HealthStatus.PASS


def test_git_dirty_repos_check_finds_dirty_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git")
    repo = tmp_path / "repo-one"
    (repo / ".git").mkdir(parents=True)
    runner = ScriptedRunner(lambda args: _completed(args, stdout=" M some-file.py\n"))
    check = git_dirty_repos_check([tmp_path], runner=runner)
    assert check.status is HealthStatus.WARN
    assert "repo-one" in check.detail


def test_git_dirty_repos_check_respects_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git")
    for index in range(5):
        (tmp_path / f"repo-{index}" / ".git").mkdir(parents=True)
    runner = ScriptedRunner(lambda args: _completed(args, stdout=""))
    check = git_dirty_repos_check([tmp_path], runner=runner, budget=2)
    assert "2 repo(s)" in check.detail
    assert len(runner.calls) == 2


def test_git_dirty_repos_check_no_git_installed(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    check = git_dirty_repos_check([Path("/tmp")])
    assert check.status is HealthStatus.INFO


def test_git_dirty_repos_check_isolates_per_repo_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git")
    (tmp_path / "repo-one" / ".git").mkdir(parents=True)

    def raise_error(
        args: Sequence[str], *, capture: bool = True, timeout: float | None = 5.0
    ) -> subprocess.CompletedProcess[str]:
        raise OSError("boom")

    check = git_dirty_repos_check([tmp_path], runner=raise_error)
    assert check.status is HealthStatus.PASS
