"""Pure formatting for dashboard background-job and health rows."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol


class JobLike(Protocol):
    label: str
    severity: Literal["success", "error", "info"]
    at: datetime


def render_jobs_row(
    *,
    active: Sequence[str],
    recent_jobs: Sequence[JobLike],
    now: datetime,
    ascii_only: bool,
    spinner: str,
) -> str:
    """Format active background work or the last three completed jobs."""
    if active:
        return f"{spinner} Jobs: {', '.join(active)}"
    if not recent_jobs:
        return ""
    icons = {
        "success": ("✓", "OK"),
        "error": ("✕", "XX"),
        "info": ("•", "-"),
    }
    parts: list[str] = []
    for event in list(recent_jobs)[:3]:
        elapsed = max(0, int((now - event.at).total_seconds()))
        marker = icons[event.severity][1 if ascii_only else 0]
        parts.append(f"{marker} {event.label} ({elapsed}s)")
    return "Recent jobs: " + "  |  ".join(parts)


def critical_health_summary(
    *,
    names: Sequence[str],
    dismissed: bool,
) -> str:
    """Return actionable critical-health copy, or empty when the row is hidden."""
    if dismissed or not names:
        return ""
    return f"  ! Critical system health  {', '.join(names[:3])}  Press h to review"
