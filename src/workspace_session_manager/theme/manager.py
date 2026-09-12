"""Theme resolution with explicit precedence and safe fallbacks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from workspace_session_manager.paths import AppPaths
from workspace_session_manager.theme.model import ThemeRecord
from workspace_session_manager.theme.providers.builtin import builtin_palettes
from workspace_session_manager.theme.providers.custom import CustomThemeProvider
from workspace_session_manager.theme.providers.omarchy import OmarchyThemeProvider


@dataclass(frozen=True, slots=True)
class ThemeDiagnostic:
    name: str
    source: str
    mode: str
    path: str
    following_system: bool


class ThemeManager:
    """Resolve built-in, custom, and optional Omarchy data-only palettes."""

    def __init__(self, paths: AppPaths, *, home: Path | None = None) -> None:
        self.paths = paths
        self.builtins = builtin_palettes()
        self.custom = CustomThemeProvider(paths.themes_dir)
        self.omarchy = OmarchyThemeProvider(home)

    def list_names(self) -> list[str]:
        return ["auto", *sorted({*self.builtins, *self.custom.names()})]

    def _named(self, name: str) -> ThemeRecord | None:
        if name in self.builtins:
            return self.builtins[name]
        return self.custom.load(name)

    def resolve(self, requested: str = "auto", *, config_theme: str | None = None) -> ThemeRecord:
        """Resolve in the documented order without silently executing anything.

        ``NO_COLOR`` is the safety/accessibility override. An explicit request
        wins next, followed by ``WS_THEME``, config, Omarchy, and the built-in.
        """
        if os.environ.get("NO_COLOR"):
            return self.builtins["monochrome"]
        for candidate, _system in (
            (requested, False),
            (os.environ.get("WS_THEME", ""), False),
            (config_theme or "", False),
        ):
            if candidate and candidate != "auto":
                resolved = self._named(candidate)
                if resolved is not None:
                    return resolved
        omarchy = self.omarchy.load()
        if omarchy is not None:
            return omarchy
        return self.builtins["omarchy"]

    def diagnostic(
        self, requested: str = "auto", *, config_theme: str | None = None
    ) -> ThemeDiagnostic:
        record = self.resolve(requested, config_theme=config_theme)
        palette = record.palette
        return ThemeDiagnostic(
            name=palette.name,
            source=palette.source,
            mode=palette.mode,
            path=record.path,
            following_system=record.following_system,
        )
