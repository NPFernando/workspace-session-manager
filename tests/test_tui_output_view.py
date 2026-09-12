from types import SimpleNamespace

from workspace_session_manager.tui_output_view import build_output_preview, summarize_output


def test_summary_removes_cli_chrome_and_bounds_meaningful_lines() -> None:
    notice = SimpleNamespace(kind="none", title="No output", detail="Nothing captured")
    output = "tokens: 100\nmodel: codex\nFirst result\nSecond result\n"

    summary = summarize_output(output, notice)

    assert "tokens: 100" not in summary.plain
    assert "model: codex" not in summary.plain
    assert "First result" in summary.plain
    assert "[l] Open full output" in summary.plain


def test_raw_preview_marks_truncation_and_reports_sanitized_metadata() -> None:
    notice = SimpleNamespace(kind="none", title="No output", detail="Nothing captured")

    preview = build_output_preview(
        "line one\nline two",
        notice,
        mode="raw",
        warning_color="yellow",
        truncated=True,
    )

    assert preview.text.plain.startswith("[older output truncated]")
    assert "Raw  2 lines  truncated  sanitized" in preview.metadata


def test_usage_limit_summary_explains_why_output_is_blocked() -> None:
    notice = SimpleNamespace(
        kind="usage-limit",
        title="Usage limit reached",
        detail="Wait before continuing.",
    )

    preview = build_output_preview(
        "ignored output",
        notice,
        mode="summary",
        warning_color="orange",
        truncated=False,
    )

    assert "Usage limit reached" in preview.text.plain
    assert "tmux session remains active" in preview.text.plain
