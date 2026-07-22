from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_log_sink_writes_owner_only_sanitized_redacted_output(tmp_path: Path) -> None:
    destination = tmp_path / "logs" / "session.log"
    source = (
        "\x1b]0;private title\x07"
        "\x1b]52;c;Y2xpcGJvYXJkLXNlY3JldA==\x07"
        "\x1b[31mstatus\x1b[0m password=not-safe 192.168.1.1\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "workspace_session_manager.log_sink", str(destination)],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    logged = destination.read_text(encoding="utf-8")
    assert "\x1b" not in logged
    assert "private title" not in logged
    assert "clipboard-secret" not in logged
    assert "not-safe" not in logged
    assert "192.168.1.1" not in logged
    assert "status" in logged
    assert destination.stat().st_mode & 0o777 == 0o600
