"""Pure compact toolbar and shortcut-rail presentation."""

from __future__ import annotations

from typing import Literal

InteractionModeName = Literal["normal", "search", "palette"]


def render_shortcut_rail(
    *,
    mode: InteractionModeName,
    selected: bool,
) -> str:
    """Return the five most useful shortcuts for the current interaction mode."""
    if mode == "search":
        shortcuts = ("Enter Apply", "Esc Cancel", "Ctrl+U Clear", "f Filter", "? Help")
    elif mode == "palette":
        shortcuts = ("Type search", "Enter run", "Esc close", "j/k move", "? help")
    elif not selected:
        shortcuts = ("c Create", "f Filter", "W Triage", "0 Macro", "? Help")
    else:
        shortcuts = ("Enter Open", "l Logs", "d Manage", "U Undo", "W Triage")
    return " | ".join(shortcuts)


def render_toolbar_summary(
    *,
    shown: int,
    total: int,
    separator: str,
    grouping: str,
    density: str,
    text_scale: str,
    motion: str,
    high_contrast: bool,
    filter_label: str,
    shortcuts: str,
) -> str:
    """Return the compact session inventory/settings line."""
    inventory = f"{shown}/{total} shown" if total and shown < total else f"{total} shown"
    return (
        f"Sessions {inventory}{separator}Group: {grouping} (g)"
        f"{separator}Density: {density} (z)"
        f"{separator}Text: {text_scale} (w)"
        f"{separator}Motion: {motion} (M)"
        f"{separator}Contrast: {'on' if high_contrast else 'off'} (C)"
        f"{separator}Filter: {filter_label} (1-6)"
        f"{separator}Shortcuts: {shortcuts}"
    )
