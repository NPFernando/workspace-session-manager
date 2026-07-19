from pathlib import Path

import pytest
from pydantic import ValidationError

from wf_session_manager.models import SessionMetadata, Tool
from wf_session_manager.security import bounded_preview, redact_text
from wf_session_manager.service import normalized_session_name, slugify_name


def test_slugify_and_tool_prefix() -> None:
    assert slugify_name(" API Refactor! ") == "api-refactor"
    assert normalized_session_name(Tool.CLAUDE, "API Refactor") == "claude-api-refactor"
    assert normalized_session_name(Tool.CODEX, "codex-review") == "codex-review"
    assert normalized_session_name(Tool.SHELL, "Diagnostics") == "diagnostics"


def test_metadata_rejects_relative_path_and_invalid_tag() -> None:
    with pytest.raises(ValidationError):
        SessionMetadata(
            tmux_session_id="$1",
            name="claude-test",
            tool=Tool.CLAUDE,
            cwd=Path("relative"),
            tags=["not valid"],
        )


def test_preview_is_sanitized_redacted_and_bounded() -> None:
    source = (
        "\x1b[31mred\x1b[0m\n"
        "password=correct-horse-battery-staple\n"
        "sk-abcdefghijklmnopqrstuvwxyz1234\n"
        "/home/tester/private 192.168.1.10\n"
        "last"
    )
    redacted = redact_text(source, home=Path("/home/tester"))
    assert "\x1b" not in redacted
    assert "correct-horse" not in redacted
    assert "sk-abc" not in redacted
    assert "192.168" not in redacted
    assert "~/private" in redacted
    assert bounded_preview(source, 2).splitlines()[-1] == "last"
