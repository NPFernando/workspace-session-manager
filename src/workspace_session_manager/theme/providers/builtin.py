"""Built-in palettes with no filesystem or desktop dependency."""

from __future__ import annotations

from dataclasses import replace

from workspace_session_manager.theme.model import ThemePalette, ThemeRecord


def builtin_palettes() -> dict[str, ThemeRecord]:
    values = {
        "mode": "dark",
        "accent": "#f2a65a",
        "selection": "#2b3440",
        "muted": "#82909d",
        "background": "#0b0d0f",
        "dark_background": "#07090b",
        "darker_background": "#050607",
        "lighter_background": "#171b21",
        "foreground": "#e6edf3",
        "dark_foreground": "#aab6c0",
        "light_foreground": "#f0f4f7",
        "bright_foreground": "#ffffff",
        "red": "#ef6b73",
        "yellow": "#e9b44c",
        "orange": "#f2a65a",
        "green": "#72c78e",
        "cyan": "#8bd5ca",
        "blue": "#66aaff",
        "magenta": "#c792ea",
        "brown": "#b98b63",
    }
    omarchy = ThemeRecord(ThemePalette.from_mapping("omarchy", "builtin", values))
    # Keep the existing public default name stable while its palette is now
    # supplied by the standalone semantic theme subsystem.
    ithaca = ThemeRecord(replace(omarchy.palette, name="ithaca"))
    monochrome_values = dict(values)
    monochrome_values.update(
        {
            key: "#d7d7d7"
            for key in (
                "accent",
                "selection",
                "muted",
                "red",
                "yellow",
                "orange",
                "green",
                "cyan",
                "blue",
                "magenta",
                "brown",
            )
        }
    )
    monochrome = ThemeRecord(ThemePalette.from_mapping("monochrome", "builtin", monochrome_values))
    return {"ithaca": ithaca, "omarchy": omarchy, "monochrome": monochrome}
