"""Pure user-facing copy for dashboard empty and unavailable states."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EmptyStateKind = Literal["attention", "disconnected", "filtered", "no_sessions"]


@dataclass(frozen=True, slots=True)
class EmptyStateCopy:
    title: str
    overview: str
    metadata: str


def empty_state_copy(
    kind: EmptyStateKind,
    *,
    attention_checking: bool = False,
    scanned: int = 0,
    eligible: int = 0,
) -> EmptyStateCopy:
    """Return concise, actionable copy for a dashboard state."""
    if kind == "attention":
        return EmptyStateCopy(
            title="Checking session alerts" if attention_checking else "No sessions need attention",
            overview=(
                f"Checked {scanned} of {eligible} eligible agent sessions."
                if attention_checking
                else "Why empty: no warning or blocked sessions match the attention view.\n"
                "Primary action: press f to inspect all sessions.\n"
                "Secondary shortcut: press r to refresh signal scans."
            ),
            metadata="Primary: Esc restore dashboard\nSecondary: f open filters",
        )
    if kind == "disconnected":
        return EmptyStateCopy(
            title="Runtime disconnected",
            overview=(
                "Why empty: ws cannot read tmux sessions right now.\n"
                "Primary action: press h to open health details.\n"
                "Secondary shortcut: press r to retry connection."
            ),
            metadata="Recovery: ws doctor --actionable | ws health --actionable",
        )
    if kind == "filtered":
        return EmptyStateCopy(
            title="No matches",
            overview=(
                "Why empty: active query/filter excludes all managed sessions.\n"
                "Primary action: press Esc to clear search or press f to revise filters.\n"
                "Secondary shortcut: press 1 for All sessions."
            ),
            metadata="Primary: c create session\nSecondary: o presets   p palette",
        )
    return EmptyStateCopy(
        title="No sessions",
        overview=(
            "Why empty: no managed sessions exist yet.\n"
            "Primary action: press c to create a session.\n"
            "Secondary shortcut: press o to launch from a preset."
        ),
        metadata="Primary: c create session\nSecondary: o presets   p palette",
    )
