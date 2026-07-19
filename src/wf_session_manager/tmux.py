"""Injection-resistant tmux adapter using argument arrays and exact targets."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from wf_session_manager.errors import SessionExistsError, SessionNotFoundError, TmuxError
from wf_session_manager.models import TmuxSession

# tmux escapes control characters in format output as backslash-octal text.
FIELD_SEPARATOR = "\\037"
TMUX_FORMAT = "\x1f".join(
    (
        "#{session_id}",
        "#{session_name}",
        "#{session_created}",
        "#{session_attached}",
        "#{session_windows}",
        "#{pane_current_path}",
        "#{pane_current_command}",
    )
)


class Runner(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        capture: bool = True,
        timeout: float | None = 5.0,
    ) -> subprocess.CompletedProcess[str]: ...


def subprocess_runner(
    args: Sequence[str],
    *,
    capture: bool = True,
    timeout: float | None = 5.0,
) -> subprocess.CompletedProcess[str]:
    """Run without a shell; interactive calls inherit the current terminal."""
    return subprocess.run(  # noqa: S603 - fixed executable and shell=False
        list(args),
        check=False,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )


class TmuxBackend:
    """Small tmux API with no implicit ownership decisions."""

    def __init__(self, runner: Runner = subprocess_runner) -> None:
        self._runner = runner

    def _run(
        self,
        *args: str,
        capture: bool = True,
        timeout: float | None = 5.0,
        allow_no_server: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = self._runner(("tmux", *args), capture=capture, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            raise TmuxError(f"unable to run tmux: {error}") from error

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if allow_no_server and (
                "no server running" in stderr.lower() or "failed to connect" in stderr.lower()
            ):
                return result
            detail = stderr or f"tmux exited with status {result.returncode}"
            raise TmuxError(detail)
        return result

    def version(self) -> str:
        return self._run("-V").stdout.strip()

    def list_sessions(self) -> list[TmuxSession]:
        result = self._run("list-sessions", "-F", TMUX_FORMAT, allow_no_server=True)
        if result.returncode != 0:
            return []

        sessions: list[TmuxSession] = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            fields = line.split(FIELD_SEPARATOR)
            if len(fields) != 7:
                raise TmuxError("tmux returned an unexpected session record")
            session_id, name, created, attached, windows, cwd, command = fields
            try:
                sessions.append(
                    TmuxSession(
                        session_id=session_id,
                        name=name,
                        created_at=datetime.fromtimestamp(int(created), tz=UTC),
                        attached_clients=int(attached),
                        windows=int(windows),
                        cwd=Path(cwd or "/"),
                        current_command=command,
                    )
                )
            except (ValueError, TypeError) as error:
                raise TmuxError(f"invalid tmux session record for {name!r}") from error
        return sessions

    def get_session(self, name: str) -> TmuxSession:
        for session in self.list_sessions():
            if session.name == name:
                return session
        raise SessionNotFoundError(f"session not found: {name}")

    def session_exists(self, name: str) -> bool:
        return any(session.name == name for session in self.list_sessions())

    def create_session(
        self,
        name: str,
        cwd: Path,
        shell_command: Sequence[str],
        agent_command: Sequence[str] | None,
    ) -> TmuxSession:
        if self.session_exists(name):
            raise SessionExistsError(f"session already exists: {name}")

        result = self._run(
            "new-session",
            "-d",
            "-P",
            "-F",
            "#{session_id}",
            "-s",
            name,
            "-c",
            str(cwd),
            "--",
            *shell_command,
        )
        created_id = result.stdout.strip()
        try:
            self.set_option(name, "@wf_owner", "wf-session-manager")
            if agent_command:
                command_line = shlex.join(agent_command)
                self._run("send-keys", "-t", f"={name}:", "-l", "--", command_line)
                self._run("send-keys", "-t", f"={name}:", "Enter")
            session = self.get_session(name)
            if created_id and session.session_id != created_id:
                raise TmuxError("tmux session ID changed during creation")
            return session
        except Exception:
            self.kill_session(name, expected_id=created_id or None)
            raise

    def set_option(self, name: str, option: str, value: str) -> None:
        self._run("set-option", "-q", "-t", f"={name}:", option, value)

    def get_option(self, name: str, option: str) -> str | None:
        result = self._runner(
            ("tmux", "show-options", "-qv", "-t", f"={name}:", option),
            capture=True,
            timeout=5.0,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def capture_pane(self, name: str, lines: int) -> str:
        session = self.get_session(name)
        del session
        return self._run(
            "capture-pane",
            "-p",
            "-t",
            f"={name}:",
            "-S",
            f"-{lines}",
        ).stdout

    def attach(self, name: str) -> int:
        self.get_session(name)
        command = "switch-client" if os.environ.get("TMUX") else "attach-session"
        result = self._run(command, "-t", f"={name}", capture=False, timeout=None)
        return result.returncode

    def rename_session(self, old_name: str, new_name: str) -> None:
        self.get_session(old_name)
        if self.session_exists(new_name):
            raise SessionExistsError(f"session already exists: {new_name}")
        self._run("rename-session", "-t", f"={old_name}", new_name)

    def kill_session(self, name: str, expected_id: str | None = None) -> None:
        session = self.get_session(name)
        if expected_id is not None and session.session_id != expected_id:
            raise TmuxError(
                f"refusing to kill {name}: expected tmux ID {expected_id}, "
                f"found {session.session_id}"
            )
        self._run("kill-session", "-t", f"={name}")


BackendFactory = Callable[[], TmuxBackend]
