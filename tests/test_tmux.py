import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from wf_session_manager.errors import TmuxError
from wf_session_manager.tmux import FIELD_SEPARATOR, TMUX_FORMAT, TmuxBackend


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
        (
            "$3",
            "claude-api",
            "1767225600",
            "1767225660",
            "1",
            "2",
            "/srv/api",
            "claude",
            "",
            "0",
            "",
        )
    )
    runner = RecordingRunner(stdout=f"{line}\n")
    sessions = TmuxBackend(runner).list_sessions()
    assert sessions[0].name == "claude-api"
    assert sessions[0].attached
    assert sessions[0].cwd.as_posix() == "/srv/api"
    assert sessions[0].last_activity_at is not None
    assert not sessions[0].pane_dead
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


def live_session_line(session_id: str = "$3", name: str = "claude-api") -> str:
    return FIELD_SEPARATOR.join(
        (
            session_id,
            name,
            "1767225600",
            "1767225660",
            "0",
            "1",
            "/srv/api",
            "claude",
            "",
            "0",
            "",
        )
    )


def test_expected_id_is_used_for_final_tmux_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    capture_runner = RecordingRunner(stdout=f"{live_session_line()}\n")
    TmuxBackend(capture_runner).capture_pane("claude-api", 20, expected_id="$3")
    assert capture_runner.calls[-1] == (
        "tmux",
        "capture-pane",
        "-p",
        "-t",
        "$3:",
        "-S",
        "-20",
    )

    option_runner = RecordingRunner(stdout=f"{live_session_line()}\n")
    TmuxBackend(option_runner).set_option(
        "claude-api", "@wf_owner", "wf-session-manager", expected_id="$3"
    )
    assert option_runner.calls[-1] == (
        "tmux",
        "set-option",
        "-q",
        "-t",
        "$3:",
        "@wf_owner",
        "wf-session-manager",
    )

    read_runner = RecordingRunner(stdout=f"{live_session_line()}\n")
    TmuxBackend(read_runner).get_option("claude-api", "@wf_owner", expected_id="$3")
    assert read_runner.calls[-1] == (
        "tmux",
        "show-options",
        "-qv",
        "-t",
        "$3:",
        "@wf_owner",
    )

    unset_runner = RecordingRunner(stdout=f"{live_session_line()}\n")
    TmuxBackend(unset_runner).unset_option("claude-api", "@wf_owner", expected_id="$3")
    assert unset_runner.calls[-1] == (
        "tmux",
        "set-option",
        "-q",
        "-u",
        "-t",
        "$3:",
        "@wf_owner",
    )

    attach_runner = RecordingRunner(stdout=f"{live_session_line()}\n")
    TmuxBackend(attach_runner).attach("claude-api", expected_id="$3")
    assert attach_runner.calls[-1] == ("tmux", "attach-session", "-t", "$3")

    rename_runner = RecordingRunner(stdout=f"{live_session_line()}\n")
    TmuxBackend(rename_runner).rename_session("claude-api", "claude-new", expected_id="$3")
    assert rename_runner.calls[-1] == ("tmux", "rename-session", "-t", "$3", "claude-new")

    kill_runner = RecordingRunner(stdout=f"{live_session_line()}\n")
    TmuxBackend(kill_runner).kill_session("claude-api", expected_id="$3")
    assert kill_runner.calls[-1] == ("tmux", "kill-session", "-t", "$3")


def test_expected_id_mismatch_never_runs_final_tmux_command() -> None:
    runner = RecordingRunner(stdout=f"{live_session_line(session_id='$replacement')}\n")
    with pytest.raises(TmuxError, match="expected tmux ID \\$original"):
        TmuxBackend(runner).kill_session("claude-api", expected_id="$original")
    assert runner.calls == [("tmux", "list-sessions", "-F", TMUX_FORMAT)]


def test_named_socket_is_applied_to_every_tmux_command() -> None:
    runner = RecordingRunner(stdout="tmux 3.4\n")
    assert TmuxBackend(runner, socket_name="wf-test").version() == "tmux 3.4"
    assert runner.calls == [("tmux", "-L", "wf-test", "-V")]


def test_socket_path_is_applied_to_every_tmux_command(tmp_path: Path) -> None:
    socket_path = tmp_path / "tmux.sock"
    runner = RecordingRunner(stdout="tmux 3.4\n")
    assert TmuxBackend(runner, socket_path=socket_path).version() == "tmux 3.4"
    assert runner.calls == [("tmux", "-S", str(socket_path), "-V")]


def test_socket_name_and_path_are_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not both"):
        TmuxBackend(socket_name="wf-test", socket_path=tmp_path / "tmux.sock")
