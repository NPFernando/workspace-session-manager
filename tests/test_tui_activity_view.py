from datetime import UTC, datetime
from types import SimpleNamespace

from workspace_session_manager.tui_activity_view import build_activity_text


def test_activity_copy_explains_warning_and_recent_timeline() -> None:
    notice = SimpleNamespace(
        warning=True,
        title="Usage limit reached",
        detail="Codex needs attention before it can continue.",
    )
    events = [
        SimpleNamespace(
            timestamp=datetime(2026, 9, 6, 10, 30, tzinfo=UTC),
            action="task-updated",
            detail="review API",
        )
    ]

    text = build_activity_text(notice, events)

    assert text.plain.startswith("Usage limit reached\nCodex needs attention")
    assert "Timeline" in text.plain
    assert "task-updated: review API" in text.plain


def test_activity_copy_has_actionable_normal_empty_state() -> None:
    notice = SimpleNamespace(
        warning=False,
        title="",
        detail="",
    )

    text = build_activity_text(notice, [])

    assert text.plain == "No action required.\nSession can continue normally."
