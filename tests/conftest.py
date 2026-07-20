from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wf_session_manager.config import AppConfig, ToolProfile
from wf_session_manager.errors import SessionExistsError, SessionNotFoundError, TmuxError
from wf_session_manager.legacy import LegacyMetadataReader
from wf_session_manager.models import TmuxSession, Tool
from wf_session_manager.paths import AppPaths
from wf_session_manager.service import SessionService
from wf_session_manager.store import MetadataStore


class FakeBackend:
    def __init__(self) -> None:
        self.sessions: dict[str, TmuxSession] = {}
        self.options: dict[tuple[str, str], str] = {}
        self.previews: dict[str, str] = {}
        self.attached: list[str] = []
        self.created_commands: list[tuple[tuple[str, ...], tuple[str, ...] | None]] = []
        self._counter = 0

    def add(
        self,
        name: str,
        *,
        session_id: str | None = None,
        cwd: Path = Path("/tmp"),
        command: str = "bash",
        clients: int = 0,
        last_activity_at: datetime | None = None,
        pane_dead: bool = False,
        pane_dead_status: int | None = None,
    ) -> TmuxSession:
        self._counter += 1
        session = TmuxSession(
            session_id=session_id or f"$fake-{self._counter}",
            name=name,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            attached_clients=clients,
            windows=1,
            cwd=cwd,
            current_command=command,
            last_activity_at=last_activity_at,
            pane_dead=pane_dead,
            pane_dead_status=pane_dead_status,
        )
        self.sessions[name] = session
        return session

    def version(self) -> str:
        return "tmux fake"

    def list_sessions(self) -> list[TmuxSession]:
        return list(self.sessions.values())

    def get_session(self, name: str) -> TmuxSession:
        try:
            return self.sessions[name]
        except KeyError as error:
            raise SessionNotFoundError(f"session not found: {name}") from error

    def session_exists(self, name: str) -> bool:
        return name in self.sessions

    def require_expected(self, name: str, expected_id: str | None) -> TmuxSession:
        session = self.get_session(name)
        if expected_id is not None and session.session_id != expected_id:
            raise TmuxError("tmux ID mismatch")
        return session

    def create_session(
        self,
        name: str,
        cwd: Path,
        shell_command: Sequence[str],
        agent_command: Sequence[str] | None,
    ) -> TmuxSession:
        if name in self.sessions:
            raise SessionExistsError(name)
        self.created_commands.append(
            (tuple(shell_command), tuple(agent_command) if agent_command else None)
        )
        session = self.add(name, cwd=cwd, command=Path((agent_command or shell_command)[0]).name)
        self.set_option(name, "@wf_owner", "wf-session-manager")
        return session

    def capture_pane(self, name: str, lines: int, expected_id: str | None = None) -> str:
        self.require_expected(name, expected_id)
        return "\n".join(self.previews.get(name, "").splitlines()[-lines:])

    def attach(self, name: str, expected_id: str | None = None) -> int:
        self.require_expected(name, expected_id)
        self.attached.append(name)
        return 0

    def rename_session(self, old_name: str, new_name: str, expected_id: str | None = None) -> None:
        if new_name in self.sessions:
            raise SessionExistsError(new_name)
        session = self.require_expected(old_name, expected_id)
        del self.sessions[old_name]
        self.sessions[new_name] = session.model_copy(update={"name": new_name})
        for (session_name, option), value in list(self.options.items()):
            if session_name == old_name:
                del self.options[(session_name, option)]
                self.options[(new_name, option)] = value

    def kill_session(self, name: str, expected_id: str | None = None) -> None:
        self.require_expected(name, expected_id)
        del self.sessions[name]
        for key in [key for key in self.options if key[0] == name]:
            del self.options[key]

    def set_option(
        self,
        name: str,
        option: str,
        value: str,
        expected_id: str | None = None,
    ) -> None:
        session = self.require_expected(name, expected_id)
        self.options[(name, option)] = value
        if option == "@wf_owner":
            self.sessions[name] = session.model_copy(update={"wf_owner": value})

    def get_option(self, name: str, option: str, expected_id: str | None = None) -> str | None:
        self.require_expected(name, expected_id)
        return self.options.get((name, option))

    def unset_option(self, name: str, option: str, expected_id: str | None = None) -> None:
        session = self.require_expected(name, expected_id)
        self.options.pop((name, option), None)
        if option == "@wf_owner":
            self.sessions[name] = session.model_copy(update={"wf_owner": None})


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        tools={
            Tool.CLAUDE: ToolProfile(command=("/bin/true",)),
            Tool.CODEX: ToolProfile(command=("/bin/true",)),
            Tool.HERMES: ToolProfile(command=("/bin/true",)),
            Tool.SHELL: ToolProfile(command=("/bin/bash", "-l")),
        },
        legacy_state_dirs=(),
    )


@pytest.fixture
def service(
    tmp_path: Path,
    fake_backend: FakeBackend,
    app_config: AppConfig,
) -> SessionService:
    paths = AppPaths(tmp_path / "config", tmp_path / "state", tmp_path / "cache")
    return SessionService(
        backend=fake_backend,
        store=MetadataStore(paths),
        config=app_config,
        paths=paths,
        legacy=LegacyMetadataReader(()),
    )
