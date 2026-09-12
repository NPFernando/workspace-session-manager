"""Pure interaction-mode presentation policy for the Textual dashboard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InteractionModePresentation:
    """Visual state derived from the active dashboard interaction mode."""

    mode_class: str
    overlay_active: bool
    searching: bool


def interaction_mode_presentation(mode: str) -> InteractionModePresentation:
    """Return semantic CSS state for an interaction mode.

    Unknown values fail closed to the normal dashboard. This keeps the mapping
    independently testable without importing Textual or the application class.
    """

    known_modes = {
        "normal",
        "search",
        "filter",
        "form",
        "command_palette",
        "manage",
        "confirmation",
    }
    normalized = mode if mode in known_modes else "normal"
    return InteractionModePresentation(
        mode_class=f"mode-{normalized}",
        overlay_active=normalized not in {"normal", "search"},
        searching=normalized == "search",
    )
