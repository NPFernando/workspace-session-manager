"""Pure contextual action availability for the session inspector."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionActionState:
    """Widget-neutral action state and the explanation shown to the user."""

    enabled: bool
    pin_label: str
    resume_disabled: bool
    attach_disabled: bool
    stop_disabled: bool
    disabled_reason: str


def session_action_state(
    *,
    enabled: bool,
    pinned: bool = False,
    resumable: bool = False,
) -> SessionActionState:
    """Return contextual button state without performing an operation."""
    if not enabled:
        return SessionActionState(
            enabled=False,
            pin_label="Pin",
            resume_disabled=True,
            attach_disabled=True,
            stop_disabled=True,
            disabled_reason="",
        )
    return SessionActionState(
        enabled=True,
        pin_label="Unpin" if pinned else "Pin",
        resume_disabled=not resumable,
        attach_disabled=resumable,
        stop_disabled=resumable,
        disabled_reason=(
            "Attach disabled: session is stopped. Use Resume or Manage." if resumable else ""
        ),
    )
