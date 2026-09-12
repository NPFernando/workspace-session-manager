"""Pure dashboard header summary formatting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HeaderSummary:
    separator: str
    counts: str
    filter_text: str
    connection: str


def build_header_summary(
    *,
    total: int,
    attached: int,
    detached: int,
    stopped: int,
    todo: int,
    doing: int,
    done: int,
    warnings: int,
    tmux_connected: bool,
    attention_scan_error: bool,
    scanned: int,
    eligible: int,
    latency_ms: int,
    render_rows: int,
    render_ms: int,
    effective_profile: str,
    refresh_interval: float,
    motion: str,
    capability: str,
    ascii_only: bool,
    active_filters: Sequence[str],
    quick_filter: str,
    filter_query: str,
    refreshing: bool,
    spinner: str,
    last_refreshed_age: int | None,
) -> HeaderSummary:
    """Format stable dashboard summary text without reading app state."""
    if not tmux_connected:
        warnings += 1
    separator = " | " if ascii_only else " • "
    session_label = "session" if total == 1 else "sessions"
    if attention_scan_error:
        warning_text = f"{warnings} known warning{'s' if warnings != 1 else ''} / alerts delayed"
    elif scanned < eligible:
        known = (
            "No known warnings"
            if warnings == 0
            else f"{warnings} known warning{'s' if warnings != 1 else ''}"
        )
        warning_text = f"{known} / alerts {scanned}/{eligible} checked"
    else:
        warning_text = (
            "No warnings" if warnings == 0 else f"{warnings} warning{'s' if warnings != 1 else ''}"
        )
    perf_text = (
        f"perf {effective_profile} {latency_ms}ms {render_rows}rows/{render_ms}ms"
        f" @{refresh_interval:.1f}s motion:{motion} cap:{capability}"
    )
    counts = separator.join(
        (
            f"{total} {session_label}",
            f"{attached} attached",
            f"{detached} detached",
            f"{stopped} stopped",
            f"todo {todo}",
            f"doing {doing}",
            f"done {done}",
            warning_text,
            perf_text,
        )
    )
    filters = list(active_filters)
    if quick_filter != "all":
        filters.insert(0, f"Quick {quick_filter}")
    if filter_query:
        filters.insert(0, f'Search "{filter_query}"')
    filter_text = f"{separator}{', '.join(filters)}" if filters else ""
    connection = "tmux connected" if tmux_connected else "tmux unavailable"
    if refreshing:
        connection = f"Refreshing {spinner}"
    elif last_refreshed_age is not None:
        updated = "Updated now" if last_refreshed_age < 1 else f"Updated {last_refreshed_age}s ago"
        connection = f"{connection}{separator}{updated}"
    return HeaderSummary(separator, counts, filter_text, connection)
