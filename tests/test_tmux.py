import subprocess
from collections.abc import Sequence

import pytest

from wf_session_manager.tmux import FIELD_SEPARATOR, TmuxBackend


class RecordingRunner:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
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
        return subprocess.CompletedProcess(
            args=args,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def test_list_sessions_parses_machine_format() -> None:
    line = FIELD_SEPARATOR.join(
        ("$3", "claude-api", "1767225600", "1", "2", "/srv/api", "claude", "")
    )
    runner = RecordingRunner(stdout=f"{line}\n")
    sessions = TmuxBackend(runner).list_sessions()
    assert sessions[0].name == "claude-api"
    assert sessions[0].attached
    assert sessions[0].cwd.as_posix() == "/srv/api"
    assert runner.calls[0][:2] == ("tmux", "list-sessions")


@pytest.mark.parametrize(
    "message",
    (
        "no server running on /tmp/tmux",
        "failed to connect to server",
        "error connecting to /tmp/tmux-1001/default (No such file or directory)",
    ),
)
def test_no_server_is_an_empty_inventory(message: str) -> None:
    runner = RecordingRunner(returncode=1, stderr=message)
    assert TmuxBackend(runner).list_sessions() == []


def test_session_option_uses_exact_pane_target() -> None:
    runner = RecordingRunner(stdout="wf-session-manager\n")
    value = TmuxBackend(runner).get_option("claude-api", "@wf_owner")
    assert value == "wf-session-manager"
    assert runner.calls[0] == (
        "tmux",
        "show-options",
        "-qv",
        "-t",
        "=claude-api:",
        "@wf_owner",
    )


def test_unset_session_option_uses_exact_pane_target() -> None:
    runner = RecordingRunner()
    TmuxBackend(runner).unset_option("claude-api", "@wf_owner")
    assert runner.calls[0] == (
        "tmux",
        "set-option",
        "-q",
        "-u",
        "-t",
        "=claude-api:",
        "@wf_owner",
    )
