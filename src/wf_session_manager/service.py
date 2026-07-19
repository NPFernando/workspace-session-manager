"""Session lifecycle policy, ownership enforcement, and merged discovery."""

from __future__ import annotations

import os
import re
import shutil
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from wf_session_manager.config import AppConfig
from wf_session_manager.errors import (
    OwnershipError,
    SessionExistsError,
    SessionNotFoundError,
    StateError,
    ToolUnavailableError,
    WFError,
)
from wf_session_manager.legacy import LegacyMetadataReader
from wf_session_manager.models import (
    CreateRequest,
    DoctorReport,
    HealthCheck,
    HealthStatus,
    SessionDetails,
    SessionMetadata,
    SessionState,
    SessionView,
    TmuxSession,
    Tool,
    utc_now,
)
from wf_session_manager.paths import AppPaths
from wf_session_manager.security import bounded_preview
from wf_session_manager.store import MetadataStore


class SessionBackend(Protocol):
    def version(self) -> str: ...

    def list_sessions(self) -> list[TmuxSession]: ...

    def get_session(self, name: str) -> TmuxSession: ...

    def session_exists(self, name: str) -> bool: ...

    def create_session(
        self,
        name: str,
        cwd: Path,
        shell_command: Sequence[str],
        agent_command: Sequence[str] | None,
    ) -> TmuxSession: ...

    def capture_pane(self, name: str, lines: int, expected_id: str | None = None) -> str: ...

    def attach(self, name: str, expected_id: str | None = None) -> int: ...

    def rename_session(
        self, old_name: str, new_name: str, expected_id: str | None = None
    ) -> None: ...

    def kill_session(self, name: str, expected_id: str | None = None) -> None: ...

    def set_option(
        self, name: str, option: str, value: str, expected_id: str | None = None
    ) -> None: ...

    def get_option(self, name: str, option: str, expected_id: str | None = None) -> str | None: ...

    def unset_option(self, name: str, option: str, expected_id: str | None = None) -> None: ...


def slugify_name(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9_-]+", "-", ascii_value.lower())
    return re.sub(r"-{2,}", "-", normalized).strip("-_")[:80]


def normalized_session_name(tool: Tool, requested: str) -> str:
    purpose = slugify_name(requested)
    if not purpose:
        raise WFError("session name must contain a letter or digit")
    if tool is Tool.SHELL:
        return purpose
    if purpose == tool.value or purpose.startswith(f"{tool.value}-"):
        return purpose
    available = 80 - len(tool.value) - 1
    return f"{tool.value}-{purpose[:available].rstrip('-_')}"


def infer_tool(name: str, current_command: str) -> Tool:
    for tool in (Tool.CLAUDE, Tool.CODEX, Tool.HERMES):
        if name == tool.value or name.startswith(f"{tool.value}-"):
            return tool
    command = Path(current_command).name.lower()
    if command in {tool.value for tool in Tool if tool is not Tool.SHELL}:
        return Tool(command)
    return Tool.SHELL


def command_available(command: tuple[str, ...]) -> bool:
    executable = command[0]
    if "/" in executable:
        path = Path(executable).expanduser()
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(executable) is not None


class SessionService:
    def __init__(
        self,
        backend: SessionBackend,
        store: MetadataStore,
        config: AppConfig,
        paths: AppPaths,
        legacy: LegacyMetadataReader | None = None,
    ) -> None:
        self.backend = backend
        self.store = store
        self.config = config
        self.paths = paths
        self.legacy = legacy or LegacyMetadataReader(config.legacy_state_dirs)

    def list_sessions(self, *, include_unmanaged: bool = False) -> list[SessionView]:
        owned_records = self.store.load_all()
        views = [
            self._merge(session, owned_records.get(session.name))
            for session in self.backend.list_sessions()
        ]
        if not include_unmanaged:
            views = [view for view in views if view.owned]
        minimum = datetime.min.replace(tzinfo=UTC)
        return sorted(
            views,
            key=lambda view: (
                view.pinned,
                view.attached,
                view.last_active_at or view.created_at or minimum,
                view.name,
            ),
            reverse=True,
        )

    def _merge(self, session: TmuxSession, record: SessionMetadata | None) -> SessionView:
        owned = (
            record is not None
            and record.tmux_session_id == session.session_id
            and session.wf_owner == "wf-session-manager"
        )
        legacy = None if owned else self.legacy.read(session.name)
        return SessionView(
            name=session.name,
            session_id=session.session_id,
            tool=record.tool
            if owned and record
            else legacy.tool
            if legacy and legacy.tool
            else infer_tool(session.name, session.current_command),
            cwd=record.cwd
            if owned and record
            else legacy.cwd
            if legacy and legacy.cwd
            else session.cwd,
            current_command=session.current_command,
            attached=session.attached,
            attached_clients=session.attached_clients,
            windows=session.windows,
            created_at=session.created_at,
            note=record.note if owned and record else legacy.note if legacy else "",
            tags=record.tags if owned and record else [],
            state=record.state.value if owned and record else legacy.state if legacy else "active",
            pinned=record.pinned if owned and record else legacy.pinned if legacy else False,
            owned=owned,
            legacy_metadata=legacy is not None,
            last_active_at=(
                record.last_attached_at
                if owned and record
                else legacy.last_used
                if legacy
                else None
            ),
        )

    def get(self, name: str, *, include_unmanaged: bool = False) -> SessionView:
        for session in self.list_sessions(include_unmanaged=include_unmanaged):
            if session.name == name:
                return session
        raise SessionNotFoundError(f"session not found: {name}")

    def inspect(self, name: str) -> SessionDetails:
        session = self.get(name)
        output = self.backend.capture_pane(
            name, self.config.preview_lines, expected_id=session.session_id
        )
        return SessionDetails(
            session=session,
            preview=bounded_preview(output, self.config.preview_lines),
        )

    def create(self, request: CreateRequest, *, dry_run: bool = False) -> SessionView:
        name = normalized_session_name(request.tool, request.name)
        if self.backend.session_exists(name):
            raise SessionExistsError(f"session already exists: {name}")

        try:
            cwd = request.cwd.expanduser().resolve(strict=True)
        except OSError as error:
            raise WFError(f"working directory does not exist: {request.cwd}") from error
        if not cwd.is_dir():
            raise WFError(f"working directory is not a directory: {cwd}")

        profile = self.config.tools[request.tool]
        shell_profile = self.config.tools[Tool.SHELL]
        if not profile.enabled:
            raise ToolUnavailableError(f"{request.tool.value} is disabled in configuration")
        if not command_available(profile.command):
            raise ToolUnavailableError(f"command not found: {profile.command[0]}")
        if not command_available(shell_profile.command):
            raise ToolUnavailableError(f"shell command not found: {shell_profile.command[0]}")

        if dry_run:
            now = utc_now()
            return SessionView(
                name=name,
                session_id="dry-run",
                tool=request.tool,
                cwd=cwd,
                current_command=Path(profile.command[0]).name,
                attached=False,
                attached_clients=0,
                windows=1,
                created_at=now,
                note=request.note,
                tags=request.tags,
                state=SessionState.ACTIVE.value,
                owned=True,
            )

        agent_command = None if request.tool is Tool.SHELL else profile.command
        session = self.backend.create_session(
            name=name,
            cwd=cwd,
            shell_command=shell_profile.command,
            agent_command=agent_command,
        )
        record = SessionMetadata(
            tmux_session_id=session.session_id,
            name=name,
            tool=request.tool,
            cwd=cwd,
            note=request.note,
            tags=request.tags,
        )
        try:
            self.store.save(record)
        except StateError:
            self.backend.kill_session(name, expected_id=session.session_id)
            raise
        return self.get(name)

    def _owned_record(self, name: str) -> SessionMetadata:
        session = self.backend.get_session(name)
        record = self.store.load(name)
        marker = self.backend.get_option(name, "@wf_owner", expected_id=session.session_id)
        if (
            record is None
            or record.tmux_session_id != session.session_id
            or marker != "wf-session-manager"
        ):
            raise OwnershipError(
                f"refusing to modify {name}: it was not created by this WF installation"
            )
        return record

    def attach(self, name: str) -> int:
        self.get(name)
        record = self._owned_record(name)
        self.store.save(
            record.model_copy(update={"last_attached_at": utc_now(), "updated_at": utc_now()})
        )
        return self.backend.attach(name, expected_id=record.tmux_session_id)

    def resume_target(self) -> SessionView:
        sessions = self.list_sessions()
        detached = [session for session in sessions if not session.attached]
        candidates = detached or sessions
        if not candidates:
            raise SessionNotFoundError("no tmux sessions are available")
        return candidates[0]

    def update_note(self, name: str, note: str) -> SessionView:
        if len(note) > 2000:
            raise WFError("note cannot exceed 2000 characters")
        record = self._owned_record(name)
        self.store.save(record.model_copy(update={"note": note, "updated_at": utc_now()}))
        return self.get(name)

    def organize(
        self,
        name: str,
        *,
        tags: list[str] | None = None,
        state: SessionState | None = None,
        pinned: bool | None = None,
    ) -> SessionView:
        record = self._owned_record(name)
        updates: dict[str, object] = {"updated_at": utc_now()}
        if tags is not None:
            updates["tags"] = tags
        if state is not None:
            updates["state"] = state
        if pinned is not None:
            updates["pinned"] = pinned
        updated = SessionMetadata.model_validate(record.model_copy(update=updates).model_dump())
        self.store.save(updated)
        return self.get(name)

    def rename(self, old_name: str, requested_name: str) -> SessionView:
        record = self._owned_record(old_name)
        new_name = normalized_session_name(record.tool, requested_name)
        if old_name == new_name:
            return self.get(old_name)
        self.backend.rename_session(old_name, new_name, expected_id=record.tmux_session_id)
        updated = record.model_copy(update={"name": new_name, "updated_at": utc_now()})
        try:
            self.store.replace(old_name, updated)
        except StateError:
            self.backend.rename_session(new_name, old_name, expected_id=record.tmux_session_id)
            raise
        return self.get(new_name)

    def delete(self, name: str) -> None:
        record = self._owned_record(name)
        self.backend.kill_session(name, expected_id=record.tmux_session_id)
        self.store.delete(name)

    def doctor(self) -> DoctorReport:
        checks: list[HealthCheck] = []
        try:
            checks.append(
                HealthCheck(name="tmux", status=HealthStatus.PASS, detail=self.backend.version())
            )
        except WFError as error:
            checks.append(HealthCheck(name="tmux", status=HealthStatus.FAIL, detail=str(error)))

        for tool, profile in self.config.tools.items():
            available = command_available(profile.command)
            status = HealthStatus.PASS if available else HealthStatus.WARN
            detail = shutil.which(profile.command[0]) or f"not found: {profile.command[0]}"
            checks.append(HealthCheck(name=f"tool:{tool.value}", status=status, detail=detail))

        errors = self.store.validation_errors()
        checks.append(
            HealthCheck(
                name="state",
                status=HealthStatus.FAIL if errors else HealthStatus.PASS,
                detail="; ".join(errors) if errors else str(self.paths.state_dir),
            )
        )
        unmanaged = sum(not session.owned for session in self.list_sessions(include_unmanaged=True))
        checks.append(
            HealthCheck(
                name="unmanaged-sessions",
                status=HealthStatus.PASS,
                detail=f"{unmanaged} hidden from managed views",
            )
        )
        readable_legacy = [
            str(path) for path in self.config.legacy_state_dirs if path.expanduser().is_dir()
        ]
        checks.append(
            HealthCheck(
                name="legacy-readonly",
                status=HealthStatus.PASS if readable_legacy else HealthStatus.WARN,
                detail=", ".join(readable_legacy) or "no legacy state directories found",
            )
        )
        return DoctorReport(checks=checks)
