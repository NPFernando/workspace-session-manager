"""Pure detail-pane row construction for a selected session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from workspace_session_manager.models import AgentState, SessionView
from workspace_session_manager.tui_session_view import display_input, display_state, humanize_task


@dataclass(frozen=True, slots=True)
class DetailRows:
    overview: tuple[tuple[str, str], ...]
    status: tuple[tuple[str, str], ...]


class DetailNotice(Protocol):
    """Structural type documentation for the activity notice used by the UI."""

    agent_state: AgentState


def build_detail_rows(
    session: SessionView,
    notice: DetailNotice,
    *,
    display_name: str,
    tool_label: str,
    directory_label: str,
    last_active_label: str,
    medium: bool,
) -> DetailRows:
    """Build human-readable overview/status rows without touching widgets."""
    overview = [
        ("Display name", display_name),
        ("Full session ID", session.name),
        ("Tool", tool_label),
        ("Task", humanize_task(session.note)),
        ("Project", session.project),
        ("Directory", directory_label),
        ("Owner", "Managed by ws" if session.owned else "Read only"),
    ]
    if session.tags:
        overview.append(("Tags", ", ".join(session.tags)))
    status = [
        ("Runtime", display_state(session.runtime.value)),
        ("Task", display_state(session.task_state.value)),
        ("Agent", display_state(notice.agent_state.value)),
        ("Input", display_input(session.input_state)),
        ("Windows", str(session.windows)),
        ("Logging", "Enabled" if session.logging_enabled else "Disabled"),
        ("Last active", last_active_label),
    ]
    if medium:
        overview = overview[:1]
        status = status[:4]
    return DetailRows(tuple(overview), tuple(status))
