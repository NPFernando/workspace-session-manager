"""Optional Omarchy palette reader.

Omarchy keeps the active colors at ``$XDG_STATE_HOME/omarchy/current/theme/colors.toml``
with a legacy ``~/.config/omarchy/current/theme/colors.toml`` fallback. Reading this
file does not require Omarchy, a graphical session, Wayland, or any executable.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from workspace_session_manager.theme.model import ThemePalette, ThemeRecord


class OmarchyThemeProvider:
    def __init__(self, home: Path | None = None) -> None:
        self.home = (home or Path.home()).expanduser()

    def candidate_paths(self) -> tuple[Path, ...]:
        state_root = Path(os.environ.get("XDG_STATE_HOME", self.home / ".local" / "state"))
        config_root = Path(os.environ.get("XDG_CONFIG_HOME", self.home / ".config"))
        return (
            state_root / "omarchy" / "current" / "theme" / "colors.toml",
            config_root / "omarchy" / "current" / "theme" / "colors.toml",
        )

    def load(self) -> ThemeRecord | None:
        for path in self.candidate_paths():
            if not path.is_file() or path.is_symlink():
                continue
            try:
                with path.open("rb") as stream:
                    values = tomllib.load(stream)
                if not all(not isinstance(value, (dict, list)) for value in values.values()):
                    continue
                palette = ThemePalette.from_mapping("omarchy-auto", "omarchy", values)
            except (OSError, tomllib.TOMLDecodeError, ValueError):
                continue
            return ThemeRecord(palette, path=str(path), following_system=True)
        return None
