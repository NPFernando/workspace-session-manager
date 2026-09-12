"""Pure session presentation helpers shared by dashboard and detail views."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from rich.text import Text

from workspace_session_manager.models import (
    AgentState,
    InputState,
    RuntimeState,
    SessionView,
    TaskState,
    Tool,
)

TOOL_STYLES = {
    Tool.CLAUDE: "bold #c792ea",
    Tool.COPILOT: "bold #8a7fff",
    Tool.CODEX: "bold #66aaff",
    Tool.HERMES: "bold #e9b44c",
    Tool.SHELL: "bold #72c78e",
}
CREATE_TOOL_SHORT_LABELS = {
    Tool.CLAUDE: "Claude",
    Tool.COPILOT: "Copilot",
    Tool.CODEX: "Codex",
    Tool.HERMES: "Hermes",
    Tool.SHELL: "Shell",
}
RUNTIME_STYLES = {
    RuntimeState.ATTACHED: "#72c78e",
    RuntimeState.DETACHED: "#9aa6ad",
    RuntimeState.STOPPED: "#e9b44c",
    RuntimeState.FAILED: "bold #ef6b73",
    RuntimeState.UNKNOWN: "#9aa6ad",
}
MONO_TOOL_STYLE = "bold #e6e6e6"
MONO_RUNTIME_STYLES = {
    RuntimeState.ATTACHED: "#e6e6e6",
    RuntimeState.DETACHED: "#9e9e9e",
    RuntimeState.STOPPED: "#b8b8b8",
    RuntimeState.FAILED: "bold #ffffff",
    RuntimeState.UNKNOWN: "#9e9e9e",
}
RAW_TASK_PATTERN = re.compile(
    r"(?i)^(?:claude|copilot|codex|hermes)\s+task:\s*(?P<task>.+?)(?:\s+\([^)]*\))?$"
)


class ActivityNoticeLike(Protocol):
    level: str
    title: str
    agent_state: AgentState
    warning: bool


def tool_style(tool: Tool, *, monochrome: bool = False) -> str:
    return MONO_TOOL_STYLE if monochrome else TOOL_STYLES[tool]


def runtime_style(runtime: RuntimeState, *, monochrome: bool = False) -> str:
    return MONO_RUNTIME_STYLES[runtime] if monochrome else RUNTIME_STYLES[runtime]


def display_state(value: str) -> str:
    return value.replace("_", " ").capitalize()


def display_input(value: InputState) -> str:
    return "Required" if value is InputState.REQUIRED else "Not required"


def humanize_task(value: str) -> str:
    """Turn assessed legacy task labels into conservative descriptions."""
    task = value.strip()
    match = RAW_TASK_PATTERN.fullmatch(task)
    if not match:
        return task
    identifier = match.group("task").strip()
    identifier = re.sub(r"^(?:https?|www)[-_]", "", identifier, flags=re.IGNORECASE)
    words = re.sub(r"[-_]+", " ", identifier).split()
    if not words:
        return ""
    return f"Work on {' '.join(words)}"


def status_badge(
    label: str,
    *,
    kind: str,
    ascii_only: bool,
    monochrome: bool,
) -> Text:
    """Return a text-plus-symbol badge that remains meaningful without colour."""
    symbols = {
        "active": ("●", "[A]"),
        "info": ("▸", "[>]"),
        "waiting": ("?", "[?]"),
        "warning": ("!", "[!]"),
        "error": ("✕", "[X]"),
        "inactive": ("○", "[-]"),
        "agent": ("◆", "[+]"),
    }
    styles = {
        "active": "green",
        "info": "cyan",
        "waiting": "yellow",
        "warning": "yellow",
        "error": "red",
        "inactive": "dim",
        "agent": "#c792ea",
    }
    marker = symbols[kind][1 if ascii_only else 0]
    style = "bold" if monochrome else f"bold {styles[kind]}"
    return Text.assemble((f"{marker} {label}", style))


def session_status_badges(
    session: SessionView,
    notice: ActivityNoticeLike,
    *,
    ascii_only: bool,
    monochrome: bool,
) -> Text:
    """Compose runtime, task, agent, input, and warning badges."""
    result = Text()
    runtime_kind = (
        "active"
        if session.runtime is RuntimeState.ATTACHED
        else "error"
        if session.runtime is RuntimeState.FAILED
        else "inactive"
    )
    task_kind = (
        "active"
        if session.task_state is TaskState.COMPLETED
        else "waiting"
        if session.task_state in {TaskState.BLOCKED, TaskState.NEEDS_INPUT, TaskState.WAITING}
        else "info"
    )
    for index, badge in enumerate(
        (
            status_badge(
                display_state(session.runtime.value),
                kind=runtime_kind,
                ascii_only=ascii_only,
                monochrome=monochrome,
            ),
            status_badge(
                display_state(session.task_state.value),
                kind=task_kind,
                ascii_only=ascii_only,
                monochrome=monochrome,
            ),
            status_badge(
                display_state(notice.agent_state.value),
                kind="agent",
                ascii_only=ascii_only,
                monochrome=monochrome,
            ),
        )
    ):
        if index:
            result.append("  ")
        result.append_text(badge)
    if session.input_state is InputState.REQUIRED:
        result.append("  ")
        result.append_text(
            status_badge(
                "Input required", kind="waiting", ascii_only=ascii_only, monochrome=monochrome
            )
        )
    if notice.warning:
        result.append("  ")
        result.append_text(
            status_badge(
                notice.title,
                kind=notice.level,
                ascii_only=ascii_only,
                monochrome=monochrome,
            )
        )
    return result


def status_chip_line(
    session: SessionView,
    notice: ActivityNoticeLike,
    *,
    ascii_only: bool,
    monochrome: bool,
) -> Text:
    chips = session_status_badges(
        session,
        notice,
        ascii_only=ascii_only,
        monochrome=monochrome,
    )
    if chips:
        chips.append("\n", style="dim")
    return chips


def display_path(path: Path) -> str:
    """Render a home-relative path without producing the invalid `~/.` form."""
    try:
        relative = path.expanduser().relative_to(Path.home())
    except ValueError:
        return str(path)
    return "~" if relative == Path(".") else f"~/{relative}"
