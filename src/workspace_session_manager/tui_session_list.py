"""Pure list-window decisions for the dashboard session pane."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from workspace_session_manager.models import SessionView


@dataclass(frozen=True, slots=True)
class SessionRenderWindow:
    """The bounded set of sessions rendered in the list and its overflow."""

    sessions: tuple[SessionView, ...]
    overflow_count: int


def bound_session_window(
    sessions: Sequence[SessionView],
    *,
    cap: int,
    selected_identity: tuple[str, str] | None,
) -> SessionRenderWindow:
    """Bound list rendering while keeping the selected session visible.

    The list is intentionally bounded for SSH responsiveness. If the selected
    item falls outside the first page, it replaces the final visible item so
    refreshes never make the inspector point at an invisible row.
    """
    matched = tuple(sessions)
    if cap <= 0 or len(matched) <= cap:
        return SessionRenderWindow(matched, 0)

    rendered = list(matched[:cap])
    selected = next(
        (item for item in matched if (item.name, item.session_id) == selected_identity),
        None,
    )
    if selected is not None and selected not in rendered and cap > 1:
        rendered[-1] = selected
    return SessionRenderWindow(tuple(rendered), len(matched) - len(rendered))
