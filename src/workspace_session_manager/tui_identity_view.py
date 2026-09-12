"""Pure selected-session identity header presentation."""

from __future__ import annotations

from typing import Protocol

from rich.text import Text

from workspace_session_manager.models import SessionView
from workspace_session_manager.tui_session_view import display_state, runtime_style, tool_style


class IdentityNotice(Protocol):
    level: str
    title: str
    warning: bool


def _truncate(value: str, width: int, *, ascii_only: bool) -> str:
    if len(value) <= width:
        return value
    marker = "..." if ascii_only else "…"
    return f"{value[: max(1, width - len(marker))]}{marker}"


def build_identity_text(
    session: SessionView,
    notice: IdentityNotice,
    *,
    name_label: str,
    last_active_label: str,
    separator: str,
    narrow: bool,
    content_width: int,
    ascii_only: bool,
    monochrome: bool,
    accent_color: str,
    warning_color: str,
    error_color: str,
) -> Text:
    """Compose the selected-session identity and state line."""
    identity = Text()
    identity.append(
        f"{session.tool.value.upper():<7}",
        style=tool_style(session.tool, monochrome=monochrome),
    )
    identity_name = name_label
    alert_title = notice.title
    if narrow:
        alert_width = (
            min(len(notice.title) + 4, max(18, content_width // 3)) if notice.warning else 0
        )
        pin_width = 3 if session.pinned else 0
        identity_name = _truncate(
            session.name,
            max(12, content_width - 7 - pin_width - alert_width),
            ascii_only=ascii_only,
        )
        if notice.warning:
            alert_title = _truncate(
                notice.title,
                max(12, content_width - 7 - pin_width - len(identity_name) - 4),
                ascii_only=ascii_only,
            )
    identity.append(identity_name, style="bold")
    if session.pinned:
        identity.append("  *" if ascii_only else "  ★", accent_color)
    if notice.warning:
        alert_style = f"bold {warning_color if notice.level == 'warning' else error_color}"
        identity.append(f"  ! {alert_title}", alert_style)
    identity.append(
        "\n"
        + separator.join(
            (
                display_state(session.runtime.value),
                display_state(session.task_state.value),
                f"Last active {last_active_label} ago",
            )
        ),
        runtime_style(session.runtime, monochrome=monochrome),
    )
    return identity
