"""Terminal sanitization and conservative secret redaction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ANSI_CSI = re.compile(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]")
ANSI_OSC = re.compile(r"(?:\x1b\]|\x9d).*?(?:\x07|\x1b\\|\x9c)", re.DOTALL)
ANSI_STRING = re.compile(r"(?:\x1b[P\^_X]|[\x90\x98\x9e\x9f]).*?(?:\x07|\x1b\\|\x9c)", re.DOTALL)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
JWT = re.compile(r"\b[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{10,}\b")
OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth|bearer|password|passwd|secret)"
    r"(\s*[:=]\s*)([^\s]+)"
)
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def sanitize_terminal(text: str) -> str:
    """Remove terminal control sequences before rendering untrusted pane output."""
    return CONTROL.sub("", ANSI_STRING.sub("", ANSI_OSC.sub("", ANSI_CSI.sub("", text))))


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
    return bounded_output(text, max_lines=max_lines).text


@dataclass(frozen=True, slots=True)
class BoundedOutput:
    text: str
    truncated: bool


def bounded_output(text: str, *, max_lines: int, max_bytes: int = 32_768) -> BoundedOutput:
    """Sanitize and retain the newest complete output within line and byte limits."""
    clean = redact_text(text)
    lines = clean.splitlines()
    truncated = len(lines) > max_lines
    selected = lines[-max_lines:]
    kept: list[str] = []
    used = 0
    for line in reversed(selected):
        line_size = len(line.encode("utf-8"))
        additional = line_size + (1 if kept else 0)
        if used + additional > max_bytes:
            truncated = True
            break
        kept.append(line)
        used += additional
    if not kept and selected:
        truncated = True
        rendered = selected[-1].encode("utf-8")[-max_bytes:].decode("utf-8", errors="ignore")
    else:
        rendered = "\n".join(reversed(kept))
    return BoundedOutput(text=rendered, truncated=truncated)
