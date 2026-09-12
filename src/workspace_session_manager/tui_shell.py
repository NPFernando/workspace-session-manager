"""Pure presentation helpers for the primary dashboard shell.

This module intentionally has no Textual or service dependencies. The app
maps its current interaction state into :class:`ActionRailState`, and this
module turns that state into the compact, discoverable keyboard rail shown at
the bottom of the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DashboardMode = Literal["search", "attention", "detail", "narrow", "medium", "wide"]


@dataclass(frozen=True, slots=True)
class ActionRailState:
    """Inputs needed to render the dashboard's contextual action rail."""

    mode: DashboardMode
    ascii_only: bool
    concise: bool
    create_hint: str
    search_query: str = ""
    selected_is_stopped: bool = False
    shortcut_pulse: str = ""


def render_action_rail(state: ActionRailState) -> str:
    """Render short, contextual actions without exposing business logic."""

    navigation = "Up/Down/jk" if state.ascii_only else "↑↓/jk"
    if state.mode == "search":
        value = (
            f"Search  {state.search_query}_   Enter apply   Esc cancel"
            if state.concise
            else f"Search  {state.search_query}_   Enter apply   Esc cancel   Ctrl+U clear"
        )
    elif state.mode == "attention":
        value = (
            f"Attention  {navigation} nav   Enter open   Esc back   ? shortcuts"
            if state.concise
            else (
                f"Attention  {navigation} nav   Enter open   Esc back   "
                "f filter   r refresh   ? help   q quit"
            )
        )
    elif state.mode == "detail":
        primary = "Enter Manage" if state.selected_is_stopped else "Enter Attach"
        value = (
            f"Detail  Esc back   {primary}   l logs   d manage   ? shortcuts"
            if state.concise
            else f"Esc back   {primary}   e edit   n task   l logs   r reload   * pin   d manage"
        )
    elif state.mode == "narrow":
        value = (
            f"{navigation} Nav  Enter Open  {state.create_hint}  f Filter  h Health  ? shortcuts"
            if state.concise
            else (
                f"{navigation} Nav   Enter Open   {state.create_hint}   "
                "Space Mark   Ctrl+A Mark all   Ctrl+U Clear marks   b Bulk"
                "   1-6 Quick filters   f Filter   g Group   h Health   ? Help"
            )
        )
    elif state.mode == "medium":
        value = (
            f"{navigation}  Enter Attach  {state.create_hint}  / Search  f Filter  d Manage  "
            "? shortcuts"
            if state.concise
            else (
                f"{navigation} Nav   Enter Attach   {state.create_hint}   o Presets   "
                "/ Search   Space Mark   Ctrl+A Mark all   Ctrl+U Clear marks   b Bulk"
                "   1-6 Quick filters   f Filter   g Group   h Health   d Manage   ? Help"
            )
        )
    else:
        value = (
            f"{navigation}  Enter Attach  {state.create_hint}  / Search  p Palette  d Manage  "
            "? shortcuts"
            if state.concise
            else (
                f"{navigation} Navigate   Enter Attach   {state.create_hint}"
                "   o Presets   / Search   Space Mark   Ctrl+A Mark all   Ctrl+U Clear   "
                "Alt+I Invert   b Bulk"
                "   1-6 Quick filters   f Filter   g Group   z Density   w Text"
                "   h Health   p Palette   d Manage   i Timeline   ? Help"
            )
        )
    if state.shortcut_pulse:
        value = f"{value}\nTip: {state.shortcut_pulse}"
    return value
