from pathlib import Path

from workspace_session_manager.models import InputState, RuntimeState, Tool
from workspace_session_manager.tui_session_view import (
    display_input,
    display_path,
    display_state,
    humanize_task,
    runtime_style,
    status_badge,
    tool_style,
)


def test_session_labels_are_human_readable_and_conservative() -> None:
    assert display_state("needs_input") == "Needs input"
    assert display_input(InputState.REQUIRED) == "Required"
    assert humanize_task("codex task: review_api-client (legacy)") == "Work on review api client"
    assert humanize_task("A user-authored task") == "A user-authored task"


def test_session_styles_keep_ascii_and_monochrome_options_available() -> None:
    assert tool_style(Tool.CODEX).startswith("bold")
    assert tool_style(Tool.CODEX, monochrome=True) == "bold #e6e6e6"
    assert runtime_style(RuntimeState.FAILED).startswith("bold")
    assert runtime_style(RuntimeState.FAILED, monochrome=True) == "bold #ffffff"


def test_status_badge_has_ascii_fallback() -> None:
    assert (
        status_badge("Failed", kind="error", ascii_only=True, monochrome=True).plain == "[X] Failed"
    )
    assert display_path(Path("/tmp/project")) == "/tmp/project"
