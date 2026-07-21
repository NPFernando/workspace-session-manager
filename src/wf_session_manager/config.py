"""Strict TOML configuration loading without executing shell content."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from wf_session_manager.errors import ConfigurationError
from wf_session_manager.models import Tool
from wf_session_manager.paths import AppPaths


class ToolProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command: tuple[str, ...]
    enabled: bool = True

    @field_validator("command")
    @classmethod
    def safe_command(cls, command: tuple[str, ...]) -> tuple[str, ...]:
        if not command or not command[0].strip():
            raise ValueError("tool command cannot be empty")
        if any(any(character in argument for character in "\x00\r\n") for argument in command):
            raise ValueError("tool command contains control characters")
        return command


def default_tools() -> dict[Tool, ToolProfile]:
    shell = os.environ.get("SHELL", "/bin/bash")
    return {
        Tool.CLAUDE: ToolProfile(command=("claude",)),
        Tool.CODEX: ToolProfile(command=("codex",)),
        Tool.HERMES: ToolProfile(command=("hermes", "chat")),
        Tool.SHELL: ToolProfile(command=(shell, "-l")),
    }


class InterfaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    animations: Literal["off", "subtle", "full"] = "subtle"
    reduce_motion: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    refresh_interval: float = Field(default=3.0, ge=1.0, le=60.0)
    attention_scan_budget: int = Field(default=8, ge=1, le=64)
    preview_lines: int = Field(default=12, ge=8, le=500)
    preview_bytes: int = Field(default=32_768, ge=1024, le=1_048_576)
    log_lines: int = Field(default=500, ge=50, le=5000)
    log_bytes: int = Field(default=262_144, ge=4096, le=4_194_304)
    interface: InterfaceConfig = Field(default_factory=InterfaceConfig)
    legacy_state_dirs: tuple[Path, ...] = Field(
        default_factory=lambda: (
            Path.home() / ".local" / "state" / "wf" / "sessions",
            Path.home() / ".ws-session-notes",
        )
    )
    tools: dict[Tool, ToolProfile] = Field(default_factory=default_tools)

    @field_validator("legacy_state_dirs")
    @classmethod
    def expand_legacy_paths(cls, values: tuple[Path, ...]) -> tuple[Path, ...]:
        return tuple(value.expanduser() for value in values)

    @field_validator("tools")
    @classmethod
    def all_tools_configured(cls, tools: dict[Tool, ToolProfile]) -> dict[Tool, ToolProfile]:
        missing = set(Tool) - set(tools)
        if missing:
            names = ", ".join(sorted(tool.value for tool in missing))
            raise ValueError(f"missing tool profiles: {names}")
        return tools


def load_config(paths: AppPaths, override: Path | None = None) -> AppConfig:
    """Load strict TOML, returning defaults when no config file exists."""
    env_path = os.environ.get("WF_DEV_CONFIG")
    config_path = override or (Path(env_path).expanduser() if env_path else paths.config_file)
    if not config_path.exists():
        return AppConfig()

    try:
        with config_path.open("rb") as stream:
            raw = tomllib.load(stream)
        return AppConfig.model_validate(raw)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ConfigurationError(f"invalid configuration at {config_path}: {error}") from error
