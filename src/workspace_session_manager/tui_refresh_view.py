"""Pure user-facing feedback for refresh and stale-selection outcomes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RefreshFailureCopy:
    title: str
    message: str


def refresh_failure_copy(error: str) -> RefreshFailureCopy:
    """Explain a failed inventory refresh and give the immediate recovery path."""
    return RefreshFailureCopy(
        title="Refresh failed",
        message=f"{error}\nCheck tmux availability, then press r to retry.",
    )


def stale_selection_copy() -> tuple[str, str]:
    """Return title/message for a selection removed or changed during refresh."""
    return (
        "Returned to session list",
        "The selected session is no longer available in this view.",
    )
