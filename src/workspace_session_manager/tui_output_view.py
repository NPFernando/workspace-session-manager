"""Pure formatting helpers for bounded, already-sanitized output previews."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from rich.text import Text


class OutputNotice(Protocol):
    kind: str
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class OutputPreview:
    text: Text
    metadata: str


def summarize_output(
    output: str,
    notice: OutputNotice,
    warning_color: str = "yellow",
) -> Text:
    """Render a conservative summary without exposing CLI chrome by default."""
    summary = Text()
    if notice.kind == "usage-limit":
        summary.append(notice.title, f"bold {warning_color}")
        summary.append(f"\n{notice.detail}\n")
        summary.append("The tmux session remains active, but the agent cannot continue yet.")
        return summary
    ignored = re.compile(
        r"(?i)^(?:tokens?|context|model|working directory|approval|session id|[-=]{3,}|[>$#]\s*)"
    )
    useful = [
        line.strip()
        for line in output.splitlines()
        if line.strip() and not ignored.match(line.strip())
    ][-4:]
    if useful:
        summary.append("Last meaningful output\n", "bold")
        summary.append("\n".join(useful))
    else:
        summary.append(notice.title, "bold")
        summary.append(f"\n{notice.detail}")
    summary.append("\n\n[l] Open full output", "dim")
    return summary


def build_output_preview(
    output: str,
    notice: OutputNotice,
    *,
    mode: str,
    warning_color: str,
    truncated: bool,
) -> OutputPreview:
    """Build preview text and stable metadata without touching widgets."""
    if mode == "summary":
        text = summarize_output(output, notice, warning_color)
    else:
        text = Text()
        if truncated:
            text.append("[older output truncated]\n", "dim")
        text.append(output or "No output captured yet.")
    state = "truncated" if truncated else "complete"
    metadata = (
        f"{mode.title()}  {len(output.splitlines())} lines  {state}  sanitized  l open full logs"
    )
    return OutputPreview(text=text, metadata=metadata)
