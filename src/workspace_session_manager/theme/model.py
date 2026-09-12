"""Validated semantic theme data.

Theme files are data. This module intentionally accepts only scalar TOML color
values and never imports, evaluates, or executes theme content.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(value: object, *, name: str, default: str) -> str:
    candidate = default if value is None else str(value).strip()
    if not HEX_COLOR.fullmatch(candidate):
        raise ValueError(f"{name} must be a #RRGGBB color")
    return candidate.lower()


@dataclass(frozen=True, slots=True)
class ThemePalette:
    """Portable semantic colors shared by TUI and non-TUI diagnostics."""

    name: str
    source: str
    mode: str
    accent: str
    selection: str
    muted: str
    background: str
    dark_background: str
    darker_background: str
    lighter_background: str
    foreground: str
    dark_foreground: str
    light_foreground: str
    bright_foreground: str
    red: str
    yellow: str
    orange: str
    green: str
    cyan: str
    blue: str
    magenta: str
    brown: str
    bright: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        name: str,
        source: str,
        values: Mapping[str, object],
    ) -> ThemePalette:
        """Build a palette from Omarchy-like ``colors.toml`` data."""

        background = _color(values.get("background"), name="background", default="#0b0d0f")
        foreground = _color(values.get("foreground"), name="foreground", default="#e6edf3")
        accent = _color(values.get("accent"), name="accent", default="#f2a65a")
        muted = _color(values.get("muted"), name="muted", default="#82909d")
        selection = _color(values.get("selection"), name="selection", default=accent)
        colors = {
            "red": "#ef6b73",
            "yellow": "#e9b44c",
            "orange": "#f2a65a",
            "green": "#72c78e",
            "cyan": "#8bd5ca",
            "blue": "#66aaff",
            "magenta": "#c792ea",
            "brown": "#b98b63",
        }
        for key, default in tuple(colors.items()):
            colors[key] = _color(values.get(key), name=key, default=default)
        bright = {
            key.removeprefix("bright_"): _color(value, name=key, default=value)
            for key, value in values.items()
            if key.startswith("bright_") and isinstance(value, str)
        }
        return cls(
            name=name,
            source=source,
            mode=str(values.get("mode", "dark")).lower(),
            accent=accent,
            selection=selection,
            muted=muted,
            background=background,
            dark_background=_color(
                values.get("dark_background"), name="dark_background", default="#07090b"
            ),
            darker_background=_color(
                values.get("darker_background"), name="darker_background", default="#050607"
            ),
            lighter_background=_color(
                values.get("lighter_background"), name="lighter_background", default="#171b21"
            ),
            foreground=foreground,
            dark_foreground=_color(
                values.get("dark_foreground"), name="dark_foreground", default="#aab6c0"
            ),
            light_foreground=_color(
                values.get("light_foreground"), name="light_foreground", default="#f0f4f7"
            ),
            bright_foreground=_color(
                values.get("bright_foreground"), name="bright_foreground", default="#ffffff"
            ),
            red=colors["red"],
            yellow=colors["yellow"],
            orange=colors["orange"],
            green=colors["green"],
            cyan=colors["cyan"],
            blue=colors["blue"],
            magenta=colors["magenta"],
            brown=colors["brown"],
            bright=bright,
        )


@dataclass(frozen=True, slots=True)
class ThemeRecord:
    """Resolved palette plus its origin for diagnostics and CLI output."""

    palette: ThemePalette
    path: str = ""
    following_system: bool = False
