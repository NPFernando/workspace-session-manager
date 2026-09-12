"""Convert semantic palettes to Textual theme objects."""

from __future__ import annotations

from textual.theme import Theme

from workspace_session_manager.theme.model import ThemePalette


def to_textual(palette: ThemePalette, *, name: str | None = None) -> Theme:
    """Map the portable palette to Textual's semantic color slots."""
    return Theme(
        name=name or palette.name,
        primary=palette.accent,
        secondary=palette.selection,
        accent=palette.cyan,
        background=palette.background,
        surface=palette.dark_background,
        panel=palette.lighter_background,
        foreground=palette.foreground,
        warning=palette.yellow,
        error=palette.red,
        success=palette.green,
        dark=palette.mode != "light",
    )
