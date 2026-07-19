"""Validated configuration, persistence, and view models."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

SESSION_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def utc_now() -> datetime:
    """Return a timezone-aware timestamp for persisted state."""
    return datetime.now(UTC)


class Tool(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    HERMES = "hermes"
    SHELL = "shell"


class SessionState(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    BLOCKED = "blocked"
    DONE = "done"
    PAUSED = "paused"


class SessionName(BaseModel):
    """Validated tmux session name."""

    model_config = ConfigDict(frozen=True)
    value: str

    @field_validator("value")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not SESSION_NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "use 1-80 lowercase letters, digits, hyphens, or underscores; "
                "the first character must be alphanumeric"
            )
        return value


class TmuxSession(BaseModel):
    """Read-only snapshot returned by tmux."""

    model_config = ConfigDict(frozen=True)
    session_id: str
    name: str
    created_at: datetime
    attached_clients: int = Field(ge=0)
    windows: int = Field(ge=1)
    cwd: Path
    current_command: str
    wf_owner: str | None = None

    @property
    def attached(self) -> bool:
        return self.attached_clients > 0


class SessionMetadata(BaseModel):
    """WF-owned state. A tmux ID prevents accidental adoption after name reuse."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    record_id: UUID = Field(default_factory=uuid4)
    owner: Literal["wf-session-manager"] = "wf-session-manager"
    tmux_session_id: str
    name: str
    tool: Tool
    cwd: Path
    note: Annotated[str, Field(max_length=2000)] = ""
    tags: Annotated[list[str], Field(max_length=12)] = Field(default_factory=list)
    state: SessionState = SessionState.ACTIVE
    pinned: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_attached_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return SessionName(value=value).value

    @field_validator("cwd")
    @classmethod
    def absolute_cwd(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("working directory must be absolute")
        return value

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            tag = value.strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", tag):
                raise ValueError(f"invalid tag: {value!r}")
            if tag not in cleaned:
                cleaned.append(tag)
        return cleaned


class LegacyMetadata(BaseModel):
    """Read-only data discovered from the legacy launcher."""

    model_config = ConfigDict(frozen=True)
    tool: Tool | None = None
    cwd: Path | None = None
    project: Path | None = None
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    state: str = ""
    last_used: datetime | None = None
    pinned: bool = False
    source: Path | None = None


class SessionView(BaseModel):
    """Merged session data used by the CLI and TUI."""

    model_config = ConfigDict(frozen=True)
    name: str
    session_id: str
    tool: Tool
    cwd: Path
    current_command: str
    attached: bool
    attached_clients: int
    windows: int
    created_at: datetime
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    state: str = "active"
    pinned: bool = False
    owned: bool = False
    legacy_metadata: bool = False
    last_active_at: datetime | None = None


class SessionDetails(BaseModel):
    """Session view plus a sanitized, non-persisted pane preview."""

    session: SessionView
    preview: str


class CreateRequest(BaseModel):
    """Validated request shared by CLI and TUI."""

    name: str
    tool: Tool
    cwd: Path
    note: Annotated[str, Field(max_length=2000)] = ""
    tags: Annotated[list[str], Field(max_length=12)] = Field(default_factory=list)


class HealthStatus(StrEnum):
    PASS = "pass"  # noqa: S105
    WARN = "warn"
    FAIL = "fail"


class HealthCheck(BaseModel):
    name: str
    status: HealthStatus
    detail: str


class DoctorReport(BaseModel):
    checks: list[HealthCheck]

    @property
    def healthy(self) -> bool:
        return not any(check.status is HealthStatus.FAIL for check in self.checks)
