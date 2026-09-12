from datetime import UTC, datetime
from pathlib import Path

from workspace_session_manager.models import RuntimeState, SessionView, Tool
from workspace_session_manager.tui_session_list import bound_session_window


def _session(name: str) -> SessionView:
    return SessionView(
        name=name,
        session_id=f"id-{name}",
        tool=Tool.SHELL,
        cwd=Path("/tmp"),
        current_command="bash",
        runtime=RuntimeState.DETACHED,
        attached=False,
        attached_clients=0,
        windows=1,
        created_at=datetime.now(UTC),
    )


def test_bounded_window_reports_overflow() -> None:
    window = bound_session_window(
        [_session("one"), _session("two"), _session("three")],
        cap=2,
        selected_identity=None,
    )

    assert [item.name for item in window.sessions] == ["one", "two"]
    assert window.overflow_count == 1


def test_bounded_window_keeps_selected_session_visible() -> None:
    window = bound_session_window(
        [_session("one"), _session("two"), _session("three")],
        cap=2,
        selected_identity=("three", "id-three"),
    )

    assert [item.name for item in window.sessions] == ["one", "three"]
    assert window.overflow_count == 1


def test_zero_cap_means_unbounded() -> None:
    sessions = [_session("one"), _session("two")]
    window = bound_session_window(sessions, cap=0, selected_identity=None)

    assert window.sessions == tuple(sessions)
    assert window.overflow_count == 0
