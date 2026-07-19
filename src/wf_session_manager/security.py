"""Terminal sanitization and conservative secret redaction."""

from __future__ import annotations

import re
from pathlib import Path

ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ANSI_OSC = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
JWT = re.compile(r"\b[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{10,}\b")
OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth|bearer|password|passwd|secret)"
    r"(\s*[:=]\s*)([^\s]+)"
)
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def sanitize_terminal(text: str) -> str:
    """Remove terminal control sequences before rendering untrusted pane output."""
    return CONTROL.sub("", ANSI_OSC.sub("", ANSI_CSI.sub("", text)))


def redact_text(text: str, home: Path | None = None) -> str:
    """Redact common credentials, IP addresses, and the local home path."""
    clean = sanitize_terminal(text)
    home_path = str(home or Path.home())
    if home_path and home_path != "/":
        clean = clean.replace(home_path, "~")
    clean = JWT.sub("[REDACTED_TOKEN]", clean)
    clean = OPENAI_KEY.sub("[REDACTED_TOKEN]", clean)
    clean = KEY_VALUE.sub(r"\1\2[REDACTED]", clean)
    return IPV4.sub("[REDACTED_IP]", clean)


def bounded_preview(text: str, max_lines: int) -> str:
    """Bound output after redaction to prevent oversized terminal payloads."""
    lines = redact_text(text).splitlines()
    return "\n".join(lines[-max_lines:])
