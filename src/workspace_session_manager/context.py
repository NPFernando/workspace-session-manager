"""Explicit application composition for CLI, TUI, and future consumers."""

from __future__ import annotations

from dataclasses import dataclass

from workspace_session_manager.config import AppConfig
from workspace_session_manager.legacy import LegacyMetadataReader
from workspace_session_manager.paths import AppPaths
from workspace_session_manager.service import SessionService
from workspace_session_manager.store import MetadataStore
from workspace_session_manager.theme import ThemeManager
from workspace_session_manager.tmux import TmuxBackend


@dataclass(frozen=True, slots=True)
class AppContext:
    """Small explicit dependency container; not a global service locator."""

    paths: AppPaths
    config: AppConfig
    sessions: SessionService
    themes: ThemeManager


def build_context(paths: AppPaths, config: AppConfig) -> AppContext:
    """Compose production dependencies without changing lifecycle policy."""
    service = SessionService(
        backend=TmuxBackend(),
        store=MetadataStore(paths),
        config=config,
        paths=paths,
        legacy=LegacyMetadataReader(config.legacy_state_dirs),
    )
    return AppContext(paths=paths, config=config, sessions=service, themes=ThemeManager(paths))
