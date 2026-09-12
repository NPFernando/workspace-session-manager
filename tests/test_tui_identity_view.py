from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from workspace_session_manager.models import RuntimeState, SessionView, TaskState, Tool
from workspace_session_manager.tui_identity_view import build_identity_text


def _session(*, pinned: bool = True) -> SessionView:
    return SessionView(
        name="codex-long-api-review-session",
        session_id="$1",
        tool=Tool.CODEX,
        cwd=Path("/tmp"),
        current_command="codex",
        runtime=RuntimeState.DETACHED,
        attached=False,
        attached_clients=0,
        windows=1,
        created_at=datetime.now(UTC),
        task_state=TaskState.IN_PROGRESS,
        pinned=pinned,
    )


def test_identity_header_contains_tool_pin_and_status() -> None:
    session = _session()
    notice = SimpleNamespace(level="neutral", title="", warning=False)

    text = build_identity_text(
        session,
        notice,
        name_label="Codex · API review",
        last_active_label="5m",
        separator=" · ",
        narrow=False,
        content_width=80,
        ascii_only=False,
        monochrome=False,
        accent_color="yellow",
        warning_color="yellow",
        error_color="red",
    )

    assert "CODEX" in text.plain
    assert "Codex · API review" in text.plain
    assert "★" in text.plain
    assert "Detached" in text.plain
    assert "Last active 5m ago" in text.plain


def test_narrow_identity_header_truncates_warning_copy_and_supports_ascii() -> None:
    session = _session(pinned=False)
    notice = SimpleNamespace(
        level="error",
        title="Authentication needs input now",
        warning=True,
    )

    text = build_identity_text(
        session,
        notice,
        name_label="unused wide label",
        last_active_label="now",
        separator=" / ",
        narrow=True,
        content_width=28,
        ascii_only=True,
        monochrome=True,
        accent_color="yellow",
        warning_color="yellow",
        error_color="red",
    )

    assert "[" not in text.plain
    assert "..." in text.plain
    assert " ! " in text.plain
    assert " / " in text.plain
