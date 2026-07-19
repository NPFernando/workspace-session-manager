"""Explicit bridge to a preserved classic WF executable."""

from __future__ import annotations

import os
from pathlib import Path

from wf_session_manager.config import AppConfig
from wf_session_manager.errors import ConfigurationError


def resolve_classic_command(config: AppConfig) -> Path | None:
    candidates = [
        config.classic_command,
        Path.home() / ".local" / "libexec" / "wf-classic",
        Path.home() / "ws",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        path = candidate.expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path.resolve()
    return None


def exec_classic(config: AppConfig, arguments: list[str] | None = None) -> None:
    command = resolve_classic_command(config)
    if command is None:
        raise ConfigurationError(
            "classic WF executable not found; set classic_command in config.toml"
        )
    os.execv(command, [str(command), *(arguments or [])])  # noqa: S606
