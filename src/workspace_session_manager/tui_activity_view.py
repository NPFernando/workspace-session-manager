"""Pure activity-card presentation for selected sessions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from rich.text import Text


class ActivityNotice(Protocol):
    title: str
    detail: str
    warning: bool


class TimelineEvent(Protocol):
    timestamp: datetime
    action: str
    detail: str


def build_activity_text(
    notice: ActivityNotice,
    events: Sequence[TimelineEvent],
) -> Text:
    """Build warning/normal copy and a bounded recent timeline."""
    activity = Text("No action required.", style="bold")
    activity.append("\nSession can continue normally.")
    if notice.warning:
        activity = Text(notice.title, style="bold")
        activity.append(f"\n{notice.detail}")
    if events:
        activity.append("\n\nTimeline")
        for event in events:
            activity.append(
                f"\n- {event.timestamp.astimezone().strftime('%H:%M')} {event.action}"
                + (f": {event.detail}" if event.detail else ""),
                "dim",
            )
    return activity
