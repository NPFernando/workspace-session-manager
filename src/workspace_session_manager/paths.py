"""XDG-compatible application path discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_path, user_config_path, user_state_path


@dataclass(frozen=True, slots=True)
class AppPaths:
    config_dir: Path
    state_dir: Path
    cache_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def sessions_dir(self) -> Path:
        return self.state_dir / "sessions"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / ".state.lock"

    @property
    def migrations_dir(self) -> Path:
        return self.state_dir / "migrations"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def onboarding_file(self) -> Path:
        return self.state_dir / ".onboarding-v1"

    @property
    def diagnostics_dir(self) -> Path:
        return self.cache_dir / "diagnostics"

    @property
    def migration_lock_file(self) -> Path:
        return self.state_dir / ".migration.lock"

    @classmethod
    def discover(cls, namespace: str = "workspace-session-manager") -> AppPaths:
        """Use an isolated namespace; WS_DEV_ROOT makes tests fully hermetic."""
        isolated_root = os.environ.get("WS_DEV_ROOT")
        if isolated_root:
            root = Path(isolated_root).expanduser().resolve()
            return cls(root / "config", root / "state", root / "cache")

        return cls(
            config_dir=Path(user_config_path(namespace, appauthor=False)),
            state_dir=Path(user_state_path(namespace, appauthor=False)),
            cache_dir=Path(user_cache_path(namespace, appauthor=False)),
        )
