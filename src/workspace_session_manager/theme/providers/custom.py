"""Safe custom theme provider."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from workspace_session_manager.theme.model import ThemePalette, ThemeRecord

THEME_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class CustomThemeProvider:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()

    def names(self) -> list[str]:
        try:
            entries = self.root.iterdir()
            return sorted(
                entry.name
                for entry in entries
                if entry.is_dir()
                and not entry.is_symlink()
                and THEME_NAME.fullmatch(entry.name)
                and (entry / "colors.toml").is_file()
                and not (entry / "colors.toml").is_symlink()
            )
        except OSError:
            return []

    def load(self, name: str) -> ThemeRecord | None:
        if not THEME_NAME.fullmatch(name):
            return None
        theme_dir = self.root / name
        path = theme_dir / "colors.toml"
        if (
            not theme_dir.is_dir()
            or theme_dir.is_symlink()
            or not path.is_file()
            or path.is_symlink()
        ):
            return None
        try:
            with path.open("rb") as stream:
                values = tomllib.load(stream)
            if not all(
                isinstance(key, str) and not isinstance(value, (dict, list))
                for key, value in values.items()
            ):
                return None
            palette = ThemePalette.from_mapping(name, "custom", values)
        except (OSError, tomllib.TOMLDecodeError, ValueError):
            return None
        return ThemeRecord(palette, path=str(path))
