"""Responsive Textual dashboard for persistent workflow sessions."""

from __future__ import annotations

import locale
import os
import re
import shlex
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any, ClassVar

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.timer import Timer
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    LoadingIndicator,
    OptionList,
    Select,
    Static,
    Switch,
    TextArea,
)
from textual.widgets.option_list import Option

from wf_session_manager import __version__
from wf_session_manager.errors import WFError
from wf_session_manager.models import (
    AgentState,
    CreateRequest,
    DoctorReport,
    HealthCheck,
    HealthStatus,
    InputState,
    RuntimeState,
    SessionView,
    TaskState,
    Tool,
    normalize_tags,
)
from wf_session_manager.service import SessionService, normalized_session_name

BindingSpec = Binding | tuple[str, str] | tuple[str, str, str]
RECENT_WINDOW = timedelta(hours=24)
USAGE_LIMIT_PATTERN = re.compile(
    r"(?im)^(?P<line>[^\n]*(?:(?:usage|session|rate)\s+limit\s+"
    r"(?:has been\s+|was\s+)?(?:reached|exceeded)|"
    r"you(?:'|\u2019)ve\s+hit\s+your\s+(?:session|usage)\s+limit)[^\n]*)$"
)
RETRY_PATTERN = re.compile(
    r"(?im)^(?:retry(?: available)?|try again|available again|resets?)"
    r"\s*(?:at|after|:)?\s*(?P<when>[^\n]+)$"
)
RAW_TASK_PATTERN = re.compile(
    r"(?i)^(?:claude|codex|hermes)\s+task:\s*(?P<task>.+?)(?:\s+\([^)]*\))?$"
)
TOOL_LABELS = {
    Tool.CLAUDE: "Claude Code",
    Tool.CODEX: "Codex",
    Tool.HERMES: "Hermes",
    Tool.SHELL: "Shell",
}
TOOL_STYLES = {
    Tool.CLAUDE: "bold #c792ea",
    Tool.CODEX: "bold #66aaff",
    Tool.HERMES: "bold #e9b44c",
    Tool.SHELL: "bold #72c78e",
}
RUNTIME_STYLES = {
    RuntimeState.ATTACHED: "#72c78e",
    RuntimeState.DETACHED: "#9aa6ad",
    RuntimeState.STOPPED: "#e9b44c",
    RuntimeState.FAILED: "bold #ef6b73",
    RuntimeState.UNKNOWN: "#9aa6ad",
}


def display_path(path: Path) -> str:
    """Render a home-relative path without producing the invalid `~/.` form."""
    try:
        relative = path.expanduser().relative_to(Path.home())
    except ValueError:
        return str(path)
    return "~" if relative == Path(".") else f"~/{relative}"


def display_state(value: str) -> str:
    return value.replace("_", " ").capitalize()


def display_input(value: InputState) -> str:
    return "Required" if value is InputState.REQUIRED else "Not required"


def humanize_task(value: str) -> str:
    """Turn assessed legacy task labels into conservative, readable descriptions."""
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


@dataclass(frozen=True, slots=True)
class ActivityNotice:
    level: str
    title: str
    detail: str
    agent_state: AgentState
    kind: str = "none"

    @property
    def warning(self) -> bool:
        return self.level in {"warning", "error"}


def detect_activity(session: SessionView, output: str) -> ActivityNotice:
    if session.runtime is RuntimeState.FAILED:
        return ActivityNotice(
            "error",
            "Session failed",
            "The active pane exited with a failure status.",
            AgentState.FAILED,
            "runtime-failed",
        )
    if session.runtime is RuntimeState.STOPPED:
        return ActivityNotice(
            "warning",
            "Session stopped",
            "Restart the tool from Manage when you are ready to continue.",
            AgentState.STOPPED,
            "runtime-stopped",
        )
    usage = USAGE_LIMIT_PATTERN.search(output)
    if usage:
        line = usage.group("line")
        tool = next(
            (
                TOOL_LABELS[item]
                for item in (Tool.CLAUDE, Tool.CODEX, Tool.HERMES)
                if item.value in line.casefold()
            ),
            TOOL_LABELS[session.tool],
        )
        limit_kind = "session" if "session limit" in line.casefold() else "usage"
        retry = RETRY_PATTERN.search(output)
        detail = f"Retry available: {retry.group('when').strip()}" if retry else "Try again later."
        return ActivityNotice(
            "warning",
            f"{tool} {limit_kind} limit reached",
            detail,
            AgentState.PAUSED,
            "usage-limit",
        )
    if session.input_state is InputState.REQUIRED or session.task_state is TaskState.NEEDS_INPUT:
        return ActivityNotice(
            "warning",
            "Input required",
            "This status was explicitly set for the session.",
            AgentState.WAITING,
            "input-required",
        )
    if session.task_state is TaskState.BLOCKED:
        return ActivityNotice(
            "warning",
            "Task blocked",
            "Review the task note before continuing.",
            AgentState.WAITING,
            "task-blocked",
        )
    if session.task_state is TaskState.WAITING:
        return ActivityNotice(
            "neutral", "Waiting", "No user input is currently required.", AgentState.WAITING
        )
    if session.task_state is TaskState.COMPLETED:
        return ActivityNotice(
            "neutral", "Task completed", "No action is required.", AgentState.COMPLETED
        )
    return ActivityNotice(
        "neutral", "No action required", "The session can continue normally.", AgentState.ACTIVE
    )


def summarize_output(output: str, notice: ActivityNotice) -> Text:
    """Render a conservative activity summary without exposing CLI chrome by default."""
    summary = Text()
    if notice.kind == "usage-limit":
        summary.append(notice.title, "bold yellow")
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


def relative_activity(value: datetime | None, *, now: datetime | None = None) -> str:
    if value is None:
        return "unknown"
    current = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    seconds = max(0, int((current - value).total_seconds()))
    if seconds < 60:
        return "<1m"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def truncate(value: str, width: int, *, ascii_only: bool = False) -> str:
    if len(value) <= width:
        return value
    marker = "..." if ascii_only else "…"
    return f"{value[: max(1, width - len(marker))]}{marker}"


def is_warning(session: SessionView, notice: ActivityNotice | None = None) -> bool:
    return (notice or detect_activity(session, "")).warning


def session_group(session: SessionView, *, now: datetime | None = None) -> str:
    """Assign each session to exactly one dashboard group."""
    if session.input_state is InputState.REQUIRED or session.task_state is TaskState.NEEDS_INPUT:
        return "Needs Input"
    if session.pinned:
        return "Pinned"
    if session.runtime is RuntimeState.ATTACHED:
        return "Attached"
    if session.runtime is RuntimeState.FAILED:
        return "Failed"
    if session.runtime is RuntimeState.STOPPED:
        return "Stopped"
    return "Detached"


def session_row(
    session: SessionView,
    width: int,
    *,
    ascii_only: bool = False,
    notice: ActivityNotice | None = None,
) -> Text:
    """Build a stable two-line row sized to its current pane."""
    alert = notice or detect_activity(session, "")
    marker = ("*" if ascii_only else "★") if session.pinned else "!" if alert.warning else " "
    tool = session.tool.value.upper()
    when = relative_activity(session.last_active_at)
    name_width = max(10, width - len(tool) - len(when) - 7)
    name = truncate(session.name, name_width, ascii_only=ascii_only)
    first = Text()
    first.append(f"{marker} ", style="yellow" if marker != " " else "")
    first.append(f"{tool:<7}", style=TOOL_STYLES[session.tool])
    first.append(f"{name:<{name_width}} ", style="bold")
    first.append(when, style="dim")
    separator = " / " if ascii_only else " · "
    statuses = [display_state(session.runtime.value), display_state(session.task_state.value)]
    if session.input_state is InputState.REQUIRED:
        statuses.append("Input required")
    second_value = truncate(separator.join(statuses), max(12, width - 3), ascii_only=ascii_only)
    first.append("\n  ")
    first.append(second_value, style=RUNTIME_STYLES[session.runtime])
    return first


def section_title(label: str) -> Text:
    return Text(label, style="bold dim")


def labeled_values(values: list[tuple[str, str]]) -> Text:
    result = Text()
    for label, value in values:
        if not value:
            continue
        result.append(f"{label:<12}", style="dim")
        result.append(value)
        result.append("\n")
    return result


def animate_modal_open(screen: Screen[Any]) -> None:
    """Apply one restrained modal transition when motion is enabled."""
    motion = getattr(screen.app, "motion", "off")
    if motion == "off":
        return
    dialog = screen.query_one(".dialog")
    duration = 0.18 if motion == "full" else 0.14
    dialog.styles.offset = (0, 0)
    final_offset = dialog.styles.offset
    dialog.styles.opacity = 0.0
    dialog.styles.offset = (0, 1)
    screen.call_after_refresh(dialog.styles.animate, "opacity", 1.0, duration=duration)
    screen.call_after_refresh(dialog.styles.animate, "offset", final_offset, duration=duration)


@dataclass(frozen=True, slots=True)
class EditResult:
    name: str
    project: str
    tags: list[str]
    task_state: TaskState
    input_state: InputState
    pinned: bool


@dataclass(frozen=True, slots=True)
class CreateFormResult:
    request: CreateRequest
    start_attached: bool = False


class CreateSessionScreen(ModalScreen[CreateFormResult | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+enter", "submit", "Create"),
    ]

    def __init__(
        self,
        default_cwd: Path,
        service: SessionService | None = None,
        default_tool: Tool = Tool.CLAUDE,
    ) -> None:
        super().__init__()
        self.default_cwd = default_cwd
        self.service = service
        self.default_tool = default_tool
        self._detected_project = ""
        self._touched: set[str] = set()
        self._advanced = False
        self._advanced_focus_id: str | None = None
        self._validation_timer: Timer | None = None
        self._validation_serial = 0
        self._validated_signature: tuple[object, ...] | None = None
        self._validated_request: CreateRequest | None = None
        self._normalized_name = ""
        self._project_user_edited = False

    def _recent_directories(self) -> list[tuple[str, str]]:
        directories = [self.default_cwd]
        if self.service:
            for session in self.service.list_sessions():
                if session.cwd not in directories:
                    directories.append(session.cwd)
        repository_roots = {Path.home() / "workspace" / "projects"}
        try:
            self.default_cwd.parent.relative_to(Path.home())
        except ValueError:
            pass
        else:
            repository_roots.add(self.default_cwd.parent)
        detected_repositories: list[Path] = []
        for root in repository_roots:
            try:
                children = sorted(root.iterdir())
            except OSError:
                continue
            for child in children:
                try:
                    is_repository = child.is_dir() and (child / ".git").exists()
                except OSError:
                    continue
                if is_repository and child not in directories:
                    detected_repositories.append(child)
        options: list[tuple[str, str]] = []
        for index, path in enumerate(directories[:8]):
            kind = "Current directory" if index == 0 else "Recently used"
            options.append((f"{kind}: {display_path(path)}", str(path)))
        for path in detected_repositories[:5]:
            options.append((f"Git repository: {display_path(path)}", str(path)))
        options.append(("Browse or enter another path", "__browse__"))
        return options

    def compose(self) -> ComposeResult:
        disclosure = ">" if getattr(self.app, "ascii_only", False) else "▸"
        with Vertical(id="create-dialog", classes="dialog create-dialog"):
            yield Label("Create Session", classes="dialog-title")
            with Vertical(id="create-basic"):
                with Horizontal(classes="form-row"):
                    yield Label("Tool", classes="field-label")
                    yield Select(
                        [(TOOL_LABELS[tool], tool.value) for tool in Tool],
                        value=self.default_tool.value,
                        allow_blank=False,
                        compact=True,
                        id="create-tool",
                    )
                yield Static("", id="create-tool-status", classes="field-status")
                with Horizontal(classes="form-row"):
                    yield Label("Session name", classes="field-label")
                    yield Input(
                        placeholder="api_refactor",
                        compact=True,
                        max_length=200,
                        id="create-name",
                    )
                yield Static("", id="create-name-status", classes="field-status")
                with Horizontal(classes="form-row task-row"):
                    yield Label("Task", classes="field-label")
                    yield TextArea(
                        placeholder="Improve API authentication",
                        compact=True,
                        soft_wrap=True,
                        tab_behavior="focus",
                        id="create-note",
                    )
                with Horizontal(classes="form-row"):
                    yield Label("Working directory", classes="field-label")
                    yield Input(value=display_path(self.default_cwd), compact=True, id="create-cwd")
                    yield Select(
                        self._recent_directories(),
                        prompt="Recent",
                        allow_blank=True,
                        compact=True,
                        id="create-recent-dir",
                    )
                yield Static("", id="create-cwd-status", classes="field-status")
                with Horizontal(classes="form-row"):
                    yield Label("Project", classes="field-label")
                    yield Input(
                        placeholder="Optional",
                        compact=True,
                        max_length=200,
                        id="create-project",
                    )
                    yield Button("Use home workspace", id="create-home-project", compact=True)
                yield Static("", id="create-project-status", classes="field-status")
                with Horizontal(id="logging-row"):
                    yield Label("Logging", classes="field-label")
                    yield Switch(value=True, id="create-logging")
                    yield Static("Enabled", id="logging-state")
                yield Static("", id="logging-hint")
                yield Button(
                    f"{disclosure} Advanced options",
                    id="create-advanced-toggle",
                    compact=True,
                )
            with (
                VerticalScroll(id="create-advanced", classes="collapsed"),
                Vertical(id="create-advanced-content"),
            ):
                with Horizontal(classes="form-row"):
                    yield Label("Tags", classes="field-label")
                    yield Input(placeholder="backend, urgent", compact=True, id="create-tags")
                yield Static("", id="create-tags-status", classes="field-status")
                with Horizontal(classes="form-row"):
                    yield Label("Command arguments", classes="field-label")
                    yield Input(
                        value="From tool configuration",
                        compact=True,
                        disabled=True,
                        id="create-command-args",
                    )
                yield Static(
                    "Edit the tool profile in config.toml to change arguments.",
                    classes="field-help",
                )
                with Horizontal(classes="form-row"):
                    yield Label("Environment", classes="field-label")
                    yield Input(
                        value="Default profile",
                        compact=True,
                        disabled=True,
                        id="create-environment",
                    )
                with Horizontal(classes="form-row"):
                    yield Label("Log retention", classes="field-label")
                    yield Input(
                        value="Size-limited",
                        compact=True,
                        disabled=True,
                        id="create-retention",
                    )
                with Horizontal(classes="form-row"):
                    yield Label("Executable", classes="field-label")
                    yield Input(compact=True, disabled=True, id="create-executable")
                with Horizontal(classes="form-row"):
                    yield Label("tmux window", classes="field-label")
                    yield Input(value="main", compact=True, disabled=True, id="create-window-name")
                with Horizontal(classes="form-row"):
                    yield Label("Initial status", classes="field-label")
                    yield Select(
                        [(display_state(state.value), state.value) for state in TaskState],
                        value=TaskState.IN_PROGRESS.value,
                        allow_blank=False,
                        compact=True,
                        id="create-task-state",
                    )
                with Horizontal(classes="form-row"):
                    yield Label("Startup", classes="field-label")
                    yield Select(
                        [("Start detached", "detached"), ("Start and attach", "attached")],
                        value="detached",
                        allow_blank=False,
                        compact=True,
                        id="create-startup",
                    )
                with Horizontal(classes="form-row"):
                    yield Label("Tool prefix", classes="field-label")
                    yield Switch(value=True, id="create-prefix")
                    yield Static("Automatic", id="prefix-state")
            with Horizontal(classes="preview-row"):
                yield Label("Command", classes="field-label")
                yield Static("", id="command-preview")
            yield Static(
                "FORM  Tab Next   Shift+Tab Previous   Ctrl+Enter Create   Esc Cancel",
                id="create-form-help",
            )
            yield Static("", id="create-summary")
            yield Static("Enter a session name to continue.", id="create-submit-reason")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="create-cancel")
                yield Button("Create Session", variant="primary", id="create-submit", disabled=True)

    def on_mount(self) -> None:
        animate_modal_open(self)
        self.set_class(self.size.width < 100, "narrow-form")
        self.set_class(self.size.width < 120 or self.size.height < 35, "compact-form")
        self._touched.update(("tool", "cwd"))
        log_root = "WF state/logs"
        if self.service:
            try:
                self.service.paths.logs_dir.relative_to(Path.home())
            except ValueError:
                log_root = "$WF_STATE/logs"
            else:
                log_root = display_path(self.service.paths.logs_dir)
        self.query_one("#logging-hint", Static).update(
            f"Output is sanitized, owner-only, and size-limited.\nStorage: {log_root}/"
        )
        self._schedule_validation()
        self.query_one("#create-name", Input).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 100, "narrow-form")
        self.set_class(event.size.width < 120 or event.size.height < 35, "compact-form")

    def _parse_tags(self) -> list[str]:
        value = self.query_one("#create-tags", Input).value
        return normalize_tags([item for item in re.split(r"[\s,]+", value) if item])

    def _signature(self) -> tuple[object, ...]:
        return (
            self.query_one("#create-tool", Select).value,
            self.query_one("#create-name", Input).value,
            self.query_one("#create-cwd", Input).value,
            self.query_one("#create-project", Input).value,
            self.query_one("#create-note", TextArea).text,
            self.query_one("#create-tags", Input).value,
            self.query_one("#create-logging", Switch).value,
            self.query_one("#create-prefix", Switch).value,
            self.query_one("#create-task-state", Select).value,
            self.query_one("#create-startup", Select).value,
        )

    def _schedule_validation(self) -> None:
        self._validation_serial += 1
        if self._validation_timer is not None:
            self._validation_timer.stop()
        self._validated_signature = None
        self._validated_request = None
        self.query_one("#create-submit", Button).disabled = True
        for field in ("name", "cwd"):
            if field in self._touched:
                self._render_field_status(f"#create-{field}-status", "checking", "Checking...")
        self._render_readiness()
        serial = self._validation_serial
        self._validation_timer = self.set_timer(0.2, lambda: self._validate(serial))

    def _validate(self, serial: int | None = None) -> None:
        if serial is not None and serial != self._validation_serial:
            return
        signature = self._signature()
        tool = Tool(str(self.query_one("#create-tool", Select).value))
        cwd = Path(self.query_one("#create-cwd", Input).value).expanduser()
        name = self.query_one("#create-name", Input).value.strip()
        automatic_prefix = self.query_one("#create-prefix", Switch).value
        if self.service:
            validation = self.service.validate_create(
                tool, name, cwd, automatic_prefix=automatic_prefix
            )
            command = validation.command
            name_error = validation.name_error
            cwd_error = validation.cwd_error
            tool_error = validation.tool_error
            detected_project = validation.detected_project
            resolved_cwd = validation.cwd
            normalized = validation.normalized_name
        else:
            try:
                normalized = normalized_session_name(tool, name, automatic_prefix=automatic_prefix)
                name_error = ""
            except WFError as error:
                normalized = ""
                name_error = str(error)
            resolved_cwd = cwd.resolve() if cwd.is_dir() else None
            cwd_error = "" if resolved_cwd else f"working directory does not exist: {cwd}"
            tool_error = ""
            detected_project = ""
            command = (tool.value,)

        project_input = self.query_one("#create-project", Input)
        if not self._project_user_edited and project_input.value in ("", self._detected_project):
            self._detected_project = detected_project
            with self.prevent(Input.Changed):
                project_input.value = detected_project
        self.query_one("#create-home-project", Button).display = bool(
            resolved_cwd and resolved_cwd == Path.home().resolve()
        )
        project_status = self.query_one("#create-project-status", Static)
        project_status.update(
            f"Detected project: {detected_project}" if detected_project else "Project not detected"
        )
        project_status.set_class(bool(detected_project), "valid")

        tag_error = ""
        try:
            tags = self._parse_tags()
        except ValueError as validation_error:
            tags = []
            tag_error = str(validation_error)

        self.query_one("#command-preview", Static).update(shlex.join(command))
        with self.prevent(Input.Changed):
            self.query_one("#create-executable", Input).value = command[0] if command else ""
        signature = self._signature()
        self._normalized_name = normalized
        self._render_name_status(name, normalized, name_error)
        self._render_field_status(
            "#create-cwd-status",
            "invalid" if cwd_error else "valid",
            cwd_error or f"Directory exists: {display_path(resolved_cwd or cwd)}",
            visible="cwd" in self._touched,
        )
        self._render_field_status(
            "#create-tool-status",
            "invalid" if tool_error else "valid",
            tool_error or "Available",
        )
        self._render_field_status(
            "#create-tags-status",
            "invalid" if tag_error else "valid",
            tag_error or "Tags are valid",
            visible="tags" in self._touched,
        )
        errors = [issue for issue in (name_error, cwd_error, tool_error, tag_error) if issue]
        request: CreateRequest | None = None
        if not errors and resolved_cwd is not None:
            try:
                request = CreateRequest(
                    name=name,
                    display_name=name,
                    tool=tool,
                    cwd=resolved_cwd,
                    project=project_input.value.strip(),
                    note=self.query_one("#create-note", TextArea).text.strip(),
                    tags=tags,
                    task_state=TaskState(str(self.query_one("#create-task-state", Select).value)),
                    logging_enabled=self.query_one("#create-logging", Switch).value,
                    automatic_prefix=automatic_prefix,
                )
            except ValueError as validation_error:
                errors.append(str(validation_error))
        if signature == self._signature():
            self._validated_signature = signature
            self._validated_request = request
            self.query_one("#create-submit", Button).disabled = request is None
        self._render_readiness(errors)

    def _render_field_status(
        self,
        selector: str,
        state: str,
        message: str,
        *,
        visible: bool = True,
    ) -> None:
        target = self.query_one(selector, Static)
        target.display = visible
        target.remove_class("valid", "warning", "invalid", "checking")
        if not visible:
            target.update("")
            return
        markers = {"valid": "+", "warning": "!", "invalid": "x", "checking": "..."}
        target.update(f"{markers.get(state, '')} {message}".strip())
        target.add_class(state)

    def _render_name_status(self, entered: str, normalized: str, error: str) -> None:
        if "name" not in self._touched:
            self._render_field_status("#create-name-status", "neutral", "", visible=False)
            return
        if error:
            self._render_field_status("#create-name-status", "invalid", error)
            return
        message = Text()
        changed = entered.strip() != normalized
        if changed:
            message.append("! Normalized for tmux/WF\n", "#e9b44c")
        message.append(f"Display name  {entered.strip()}\n", "dim")
        message.append(f"+ Available as {normalized}", "#72c78e")
        target = self.query_one("#create-name-status", Static)
        target.display = True
        target.remove_class("valid", "warning", "invalid", "checking")
        target.add_class("warning" if changed else "valid")
        target.update(message)

    def _render_readiness(self, errors: list[str] | None = None) -> None:
        summary = self.query_one("#create-summary", Static)
        reason = self.query_one("#create-submit-reason", Static)
        request = self._validated_request
        if request is not None and self._normalized_name:
            summary.update(
                labeled_values(
                    [
                        ("Ready", "to create"),
                        ("Tool", TOOL_LABELS[request.tool]),
                        ("Session", self._normalized_name),
                        ("Directory", display_path(request.cwd)),
                        ("Command", str(self.query_one("#command-preview", Static).content)),
                        ("Logging", "Enabled" if request.logging_enabled else "Disabled"),
                    ]
                )
            )
            summary.display = True
            reason.display = False
            return
        summary.display = False
        reason.display = True
        reason.remove_class("invalid")
        if "name" not in self._touched or not self.query_one("#create-name", Input).value:
            reason.update("Enter a session name to continue.")
        elif errors:
            reason.update(f"Create Session unavailable: {errors[0]}")
            reason.add_class("invalid")
        else:
            reason.update("Checking validation...")

    @on(Select.Changed, "#create-tool")
    def tool_changed(self) -> None:
        self._touched.add("tool")
        self._schedule_validation()

    @on(Select.Changed, "#create-recent-dir")
    def recent_directory_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.NULL:
            if str(event.value) == "__browse__":
                self.query_one("#create-cwd", Input).focus()
                self.query_one("#create-recent-dir", Select).value = Select.NULL
                return
            selected = display_path(Path(str(event.value)))
            if self.query_one("#create-cwd", Input).value == selected:
                return
            self._touched.add("cwd")
            self.query_one("#create-cwd", Input).value = selected
            self.query_one("#create-recent-dir", Select).value = Select.NULL

    @on(Select.Changed, "#create-task-state, #create-startup")
    def advanced_select_changed(self) -> None:
        self._schedule_validation()

    @on(Input.Changed)
    def input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {"create-name", "create-cwd", "create-project", "create-tags"}:
            if event.input.id == "create-name":
                self._touched.add("name")
            elif event.input.id == "create-cwd":
                self._touched.add("cwd")
            elif event.input.id == "create-tags":
                self._touched.add("tags")
            elif event.input.id == "create-project":
                self._project_user_edited = True
            self._schedule_validation()

    @on(TextArea.Changed, "#create-note")
    def task_changed(self) -> None:
        self._schedule_validation()

    @on(Switch.Changed, "#create-logging, #create-prefix")
    def switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "create-logging":
            self.query_one("#logging-state", Static).update(
                "Enabled" if event.value else "Disabled"
            )
        else:
            self.query_one("#prefix-state", Static).update(
                "Automatic" if event.value else "Disabled"
            )
        self._schedule_validation()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-cancel":
            self.dismiss(None)
            return
        if event.button.id == "create-advanced-toggle":
            self._set_advanced(not self._advanced)
            return
        if event.button.id == "create-home-project":
            self.query_one("#create-project", Input).value = "Home workspace"
            self._project_user_edited = True
            return
        if event.button.id != "create-submit":
            return
        self.action_submit()

    def action_submit(self) -> None:
        button = self.query_one("#create-submit", Button)
        if button.disabled or self._validated_signature != self._signature():
            return
        request = self._validated_request
        if request is None:
            return
        self.dismiss(
            CreateFormResult(
                request=request,
                start_attached=str(self.query_one("#create-startup", Select).value) == "attached",
            )
        )

    def _set_advanced(self, expanded: bool) -> None:
        focused = self.app.focused
        advanced = self.query_one("#create-advanced", VerticalScroll)
        if not expanded and focused is not None and advanced in focused.ancestors:
            self._advanced_focus_id = focused.id
        self._advanced = expanded
        advanced.set_class(not expanded, "collapsed")
        self.query_one("#create-dialog").set_class(expanded, "advanced")
        toggle = self.query_one("#create-advanced-toggle", Button)
        if getattr(self.app, "ascii_only", False):
            toggle.label = "v Advanced options" if expanded else "> Advanced options"
        else:
            toggle.label = "▾ Advanced options" if expanded else "▸ Advanced options"
        if not expanded and focused is not None and advanced in focused.ancestors:
            toggle.focus()
        elif expanded and self._advanced_focus_id:
            self.call_after_refresh(self.query_one(f"#{self._advanced_focus_id}").focus)

    def action_cancel(self) -> None:
        if self._advanced:
            self._set_advanced(False)
            self.query_one("#create-advanced-toggle", Button).focus()
            return
        self.dismiss(None)


class CreateFailureScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "close", "Close")]

    def __init__(self, session_name: str, error: str, *, metadata_exists: bool) -> None:
        super().__init__()
        self.session_name = session_name
        self.error = error
        self.metadata_exists = metadata_exists

    def compose(self) -> ComposeResult:
        with Vertical(id="create-failure-dialog", classes="dialog small-dialog danger-dialog"):
            yield Label("Session Startup Failed", classes="dialog-title danger-title")
            yield Static(
                f"{self.session_name} was not started.\n\n{self.error}",
                classes="confirm-copy",
            )
            yield Static(
                "WF preserved the validated request. Retry after correcting the environment, "
                "or inspect the failure details.",
                classes="dialog-context",
            )
            with Horizontal(classes="dialog-actions failure-actions"):
                yield Button("Retry", variant="primary", id="create-failure-retry")
                yield Button("Open Details", id="create-failure-details")
                yield Button(
                    "Remove Metadata",
                    variant="error",
                    id="create-failure-remove",
                    disabled=not self.metadata_exists,
                )
                yield Button("Close", id="create-failure-close")

    def on_mount(self) -> None:
        animate_modal_open(self)
        self.query_one("#create-failure-close", Button).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "create-failure-retry": "retry",
            "create-failure-details": "details",
            "create-failure-remove": "remove",
            "create-failure-close": "close",
        }
        if event.button.id in actions:
            self.dismiss(actions[event.button.id])

    def action_close(self) -> None:
        self.dismiss("close")


class EditSessionScreen(ModalScreen[EditResult | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session: SessionView) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="edit-dialog", classes="dialog"):
            yield Label("Edit session", classes="dialog-title")
            yield Label("Name", classes="field-label")
            yield Input(value=self.session.name, id="edit-name")
            yield Label("Project", classes="field-label")
            yield Input(value=self.session.project, id="edit-project")
            yield Label("Task state", classes="field-label")
            yield Select(
                [(display_state(state.value), state.value) for state in TaskState],
                value=self.session.task_state.value,
                allow_blank=False,
                id="edit-task-state",
            )
            yield Label("Input", classes="field-label")
            yield Select(
                [(display_state(state.value), state.value) for state in InputState],
                value=self.session.input_state.value,
                allow_blank=False,
                id="edit-input-state",
            )
            yield Label("Tags", classes="field-label")
            yield Input(value=" ".join(self.session.tags), id="edit-tags")
            yield Checkbox("Pinned", value=self.session.pinned, id="edit-pinned")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="edit-cancel")
                yield Button("Save", variant="primary", id="edit-submit")

    def on_mount(self) -> None:
        self.query_one("#edit-name", Input).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "edit-cancel":
            self.dismiss(None)
        elif event.button.id == "edit-submit":
            self.dismiss(
                EditResult(
                    name=self.query_one("#edit-name", Input).value,
                    project=self.query_one("#edit-project", Input).value,
                    tags=self.query_one("#edit-tags", Input).value.split(),
                    task_state=TaskState(str(self.query_one("#edit-task-state", Select).value)),
                    input_state=InputState(str(self.query_one("#edit-input-state", Select).value)),
                    pinned=self.query_one("#edit-pinned", Checkbox).value,
                )
            )

    def action_cancel(self) -> None:
        self.dismiss(None)


class NoteScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session: SessionView) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        with Vertical(id="note-dialog", classes="dialog small-dialog"):
            yield Label("Edit task", classes="dialog-title")
            yield Static(self.session.name, classes="dialog-context")
            yield Input(value=self.session.note, id="note-value")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="note-cancel")
                yield Button("Save", variant="primary", id="note-submit")

    def on_mount(self) -> None:
        self.query_one("#note-value", Input).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "note-cancel":
            self.dismiss(None)
        elif event.button.id == "note-submit":
            self.dismiss(self.query_one("#note-value", Input).value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ManageSessionScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session: SessionView) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        stopped = self.session.runtime is RuntimeState.STOPPED
        with VerticalScroll(id="more-dialog", classes="dialog manage-dialog"):
            yield Label("Manage Session", classes="dialog-title")
            yield Static(self.session.name, classes="dialog-context")
            yield Static("General", classes="manage-section")
            yield Button("Rename or edit organization", id="manage-edit")
            yield Button("Edit task note", id="manage-note")
            yield Button("Set task and input status", id="manage-status")
            yield Button(
                "Disable logging" if self.session.logging_enabled else "Enable logging",
                id="manage-logging",
                disabled=stopped,
            )
            yield Button("Unpin" if self.session.pinned else "Pin", id="manage-pin")
            yield Button("Advanced details", id="manage-advanced")
            yield Static("Runtime", classes="manage-section")
            yield Button("Restart tool", id="manage-restart")
            yield Button("Stop command", id="manage-stop-command", disabled=stopped)
            yield Static("Danger zone", classes="manage-section danger-title")
            yield Button("Stop tmux session", variant="error", id="manage-stop", disabled=stopped)
            yield Button("Remove WF metadata", variant="error", id="manage-remove-metadata")
            yield Button("Delete logs", variant="error", id="manage-delete-logs")
            yield Button("Delete session and metadata", variant="error", id="more-delete")
            yield Button("Cancel", id="more-cancel")

    def on_mount(self) -> None:
        animate_modal_open(self)
        self.query_one("#more-cancel", Button).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "more-cancel":
            self.dismiss(None)
            return
        actions = {
            "manage-edit": "edit",
            "manage-note": "note",
            "manage-status": "edit",
            "manage-logging": "logging",
            "manage-pin": "pin",
            "manage-advanced": "advanced",
            "manage-restart": "restart",
            "manage-stop-command": "stop-command",
            "manage-stop": "stop-session",
            "manage-remove-metadata": "remove-metadata",
            "manage-delete-logs": "delete-logs",
            "more-delete": "delete",
        }
        action = actions.get(event.button.id or "")
        if action:
            self.dismiss(action)

    def action_cancel(self) -> None:
        self.dismiss(None)


MoreActionsScreen = ManageSessionScreen


class DeleteSessionScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session_name: str) -> None:
        super().__init__()
        self.session_name = session_name

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-dialog", classes="dialog danger-dialog"):
            yield Label("Delete session and metadata", classes="dialog-title danger-title")
            yield Static(
                "This stops the tmux session. Type the exact session name to continue.",
                classes="confirm-copy",
            )
            yield Static(self.session_name, classes="confirm-name")
            yield Input(id="delete-confirm")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="delete-cancel")
                yield Button("Delete", variant="error", id="delete-submit")

    def on_mount(self) -> None:
        self.query_one("#delete-cancel", Button).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "delete-cancel":
            self.dismiss(False)
        elif event.button.id == "delete-submit":
            confirmed = self.query_one("#delete-confirm", Input).value == self.session_name
            if not confirmed:
                self.notify("Session name does not match", severity="error")
                return
            self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfirmActionScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, session_name: str, consequence: str) -> None:
        super().__init__()
        self.confirm_title = title
        self.session_name = session_name
        self.consequence = consequence

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog", classes="dialog danger-dialog small-dialog"):
            yield Label(self.confirm_title, classes="dialog-title danger-title")
            yield Static(self.session_name, classes="confirm-name")
            yield Static(self.consequence, classes="confirm-copy")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="confirm-cancel")
                yield Button("Confirm", variant="error", id="confirm-submit")

    def on_mount(self) -> None:
        animate_modal_open(self)
        self.query_one("#confirm-cancel", Button).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-submit")

    def action_cancel(self) -> None:
        self.dismiss(False)


class MessageScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, title: str, content: Text | str) -> None:
        super().__init__()
        self.message_title = title
        self.message_content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="message-dialog", classes="dialog message-dialog"):
            yield Label(self.message_title, classes="dialog-title")
            yield Static(self.message_content, id="message-content")
            yield Button("Close", id="message-close")

    def on_mount(self) -> None:
        self.query_one("#message-close", Button).focus()

    @on(Button.Pressed, "#message-close")
    def close_button(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


@dataclass(frozen=True, slots=True)
class FilterState:
    tool: Tool | None = None
    runtime: RuntimeState | None = None
    task: TaskState | None = None
    warnings_only: bool = False
    recent_only: bool = False

    @property
    def active(self) -> bool:
        return any(
            (
                self.tool,
                self.runtime,
                self.task,
                self.warnings_only,
                self.recent_only,
            )
        )

    def labels(self) -> list[str]:
        values: list[str] = []
        if self.tool:
            values.append(TOOL_LABELS[self.tool])
        if self.runtime:
            values.append(display_state(self.runtime.value))
        if self.task:
            values.append(display_state(self.task.value))
        if self.warnings_only:
            values.append("Warnings")
        if self.recent_only:
            values.append("Recent")
        return values


class FilterScreen(ModalScreen[FilterState | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current: FilterState) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-dialog", classes="dialog small-dialog"):
            yield Label("Filter Sessions", classes="dialog-title")
            yield Label("Tool", classes="field-label")
            yield Select(
                [("Any tool", "any"), *[(TOOL_LABELS[item], item.value) for item in Tool]],
                value=self.current.tool.value if self.current.tool else "any",
                allow_blank=False,
                id="filter-tool",
            )
            yield Label("Runtime", classes="field-label")
            yield Select(
                [
                    ("Any runtime", "any"),
                    *[(display_state(item.value), item.value) for item in RuntimeState],
                ],
                value=self.current.runtime.value if self.current.runtime else "any",
                allow_blank=False,
                id="filter-runtime",
            )
            yield Label("Task", classes="field-label")
            yield Select(
                [
                    ("Any task state", "any"),
                    *[(display_state(item.value), item.value) for item in TaskState],
                ],
                value=self.current.task.value if self.current.task else "any",
                allow_blank=False,
                id="filter-task",
            )
            yield Checkbox("Warnings only", self.current.warnings_only, id="filter-warnings")
            yield Checkbox(
                "Active in the last 24 hours",
                self.current.recent_only,
                id="filter-recent",
            )
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="filter-cancel")
                yield Button("Clear", id="filter-clear")
                yield Button("Apply", variant="primary", id="filter-apply")

    def on_mount(self) -> None:
        self.query_one("#filter-tool", Select).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "filter-cancel":
            self.dismiss(None)
        elif event.button.id == "filter-clear":
            self.dismiss(FilterState())
        elif event.button.id == "filter-apply":
            tool = str(self.query_one("#filter-tool", Select).value)
            runtime = str(self.query_one("#filter-runtime", Select).value)
            task = str(self.query_one("#filter-task", Select).value)
            self.dismiss(
                FilterState(
                    tool=None if tool == "any" else Tool(tool),
                    runtime=None if runtime == "any" else RuntimeState(runtime),
                    task=None if task == "any" else TaskState(task),
                    warnings_only=self.query_one("#filter-warnings", Checkbox).value,
                    recent_only=self.query_one("#filter-recent", Checkbox).value,
                )
            )

    def action_cancel(self) -> None:
        self.dismiss(None)


def diagnostic_name(check: HealthCheck) -> str:
    labels = {
        "tmux": "tmux",
        "tool:claude": "Claude Code",
        "tool:codex": "Codex",
        "tool:hermes": "Hermes",
        "tool:shell": "Shell",
        "state": "State directory",
        "unmanaged-sessions": "Session ownership",
        "legacy-readonly": "Classic metadata",
        "disk-space": "Disk space",
    }
    return labels.get(check.name, display_state(check.name))


def diagnostic_detail(check: HealthCheck, *, expanded: bool) -> str:
    if expanded:
        return check.detail.replace(str(Path.home()), "~")
    if check.name.startswith("tool:"):
        return "Available" if check.status is HealthStatus.PASS else "Unavailable"
    if check.name == "state":
        return "Writable" if check.status is HealthStatus.PASS else "Needs attention"
    if check.name == "legacy-readonly":
        return "Not detected" if check.detail.startswith("no legacy") else "Detected"
    return check.detail.replace(str(Path.home()), "~")


class DiagnosticsScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("r", "run", "Run again"),
        Binding("e", "export", "Export"),
    ]

    def __init__(self, service: SessionService) -> None:
        super().__init__()
        self.service = service
        self.report = DoctorReport(checks=[])
        self.show_details = False
        self.running = False
        self.last_run_at: datetime | None = None
        self.duration_ms: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="diagnostics-dialog", classes="dialog diagnostics-dialog"):
            yield Label("System Diagnostics", classes="dialog-title")
            yield Static("Not run", id="diagnostics-meta")
            yield Static("", id="diagnostics-summary")
            yield LoadingIndicator(id="diagnostics-loading")
            with VerticalScroll(id="diagnostics-list"):
                yield Static("", id="diagnostics-content")
            with Horizontal(classes="dialog-actions diagnostics-actions"):
                yield Button("Run Again", id="diagnostics-run")
                yield Button("Export Report", id="diagnostics-export")
                yield Button("Show Details", id="diagnostics-details")
                yield Button("Close", variant="primary", id="diagnostics-close")

    def on_mount(self) -> None:
        animate_modal_open(self)
        self.query_one("#diagnostics-close", Button).focus()
        self.action_run()

    def _render_report(self) -> None:
        passed = self.report.count(HealthStatus.PASS)
        warnings = self.report.count(HealthStatus.WARN)
        failed = self.report.count(HealthStatus.FAIL)
        information = self.report.count(HealthStatus.INFO)
        self.query_one("#diagnostics-summary", Static).update(
            f"{passed} passed   {warnings} warnings   {failed} failed   {information} information"
        )
        content = Text()
        for check in self.report.checks:
            styles = {
                HealthStatus.PASS: "green",
                HealthStatus.WARN: "yellow",
                HealthStatus.FAIL: "bold red",
                HealthStatus.INFO: "#66aaff",
            }
            style = styles[check.status]
            content.append(f"{check.status.value.upper():<5}", style)
            content.append(f"{diagnostic_name(check):<22}", "bold")
            content.append(f"{diagnostic_detail(check, expanded=self.show_details)}\n")
            if check.status in {HealthStatus.WARN, HealthStatus.FAIL} and check.corrective_action:
                content.append(f"     Action: {check.corrective_action}\n", "dim")
        self.query_one("#diagnostics-content", Static).update(content)
        self.query_one("#diagnostics-details", Button).label = (
            "Hide Details" if self.show_details else "Show Details"
        )

    def _show_loading(self) -> None:
        if self.running:
            self.query_one("#diagnostics-loading", LoadingIndicator).display = True

    def action_run(self) -> None:
        if self.running:
            return
        self.running = True
        self.query_one("#diagnostics-loading", LoadingIndicator).display = False
        self.query_one("#diagnostics-summary", Static).update(
            "Running diagnostics... Checking tmux and tool availability"
        )
        self.query_one("#diagnostics-meta", Static).update("Running now")
        for selector in ("#diagnostics-run", "#diagnostics-export", "#diagnostics-details"):
            self.query_one(selector, Button).disabled = True
        self.set_timer(0.25, self._show_loading)
        self._run_diagnostics()

    @work(thread=True, exclusive=True, group="diagnostics")
    def _run_diagnostics(self) -> None:
        started = perf_counter()
        try:
            report = self.service.doctor()
        except (OSError, WFError) as error:
            report = DoctorReport(
                checks=[
                    HealthCheck(
                        name="diagnostics-run",
                        status=HealthStatus.FAIL,
                        detail=str(error),
                        corrective_action="Close diagnostics, verify the environment, and retry.",
                    )
                ]
            )
        duration_ms = max(1, round((perf_counter() - started) * 1000))
        self.app.call_from_thread(self._finish_diagnostics, report, duration_ms)

    def _finish_diagnostics(self, report: DoctorReport, duration_ms: int) -> None:
        self.report = report
        self.duration_ms = duration_ms
        self.last_run_at = datetime.now().astimezone()
        self.running = False
        self.query_one("#diagnostics-loading", LoadingIndicator).display = False
        for selector in ("#diagnostics-run", "#diagnostics-export", "#diagnostics-details"):
            self.query_one(selector, Button).disabled = False
        duration = "<1 second" if duration_ms < 1000 else f"{duration_ms / 1000:.1f} seconds"
        self.query_one("#diagnostics-meta", Static).update(
            f"Last run: just now   Completed in {duration}"
        )
        self._render_report()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "diagnostics-close":
            self.dismiss(None)
        elif event.button.id == "diagnostics-run":
            self.action_run()
        elif event.button.id == "diagnostics-details":
            self.show_details = not self.show_details
            self._render_report()
        elif event.button.id == "diagnostics-export":
            try:
                destination = self.service.export_doctor_report(self.report)
            except (OSError, WFError) as error:
                self.notify(str(error), title="Export failed", severity="error")
            else:
                self.notify(display_path(destination), title="Privacy-safe report exported")

    def action_export(self) -> None:
        if not self.running:
            self.query_one("#diagnostics-export", Button).press()

    def action_close(self) -> None:
        self.dismiss(None)


class OnboardingScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "close", "Close")]

    STEPS: ClassVar[tuple[tuple[str, str], ...]] = (
        (
            "1 of 3 - Sessions",
            "Sessions continue running through tmux after your SSH connection disconnects.",
        ),
        (
            "2 of 3 - Status",
            "WF keeps tmux runtime, task progress, agent state, and input requirements separate.",
        ),
        (
            "3 of 3 - Safety",
            "Stop and delete operations always require a protected confirmation.",
        ),
    )

    def __init__(self) -> None:
        super().__init__()
        self.step = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="onboarding-dialog", classes="dialog small-dialog"):
            yield Label(self.STEPS[0][0], id="onboarding-title", classes="dialog-title")
            yield Static(self.STEPS[0][1], id="onboarding-copy")
            with Horizontal(classes="dialog-actions"):
                yield Button("Skip", id="onboarding-close")
                yield Button("Next", variant="primary", id="onboarding-next")

    def on_mount(self) -> None:
        animate_modal_open(self)
        self.query_one("#onboarding-close", Button).focus()

    def _render_step(self) -> None:
        title, copy = self.STEPS[self.step]
        self.query_one("#onboarding-title", Label).update(title)
        self.query_one("#onboarding-copy", Static).update(copy)
        self.query_one("#onboarding-next", Button).label = (
            "Start using WF" if self.step == len(self.STEPS) - 1 else "Next"
        )

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "onboarding-close":
            self.dismiss(None)
        elif event.button.id == "onboarding-next":
            if self.step == len(self.STEPS) - 1:
                self.dismiss(None)
            else:
                self.step += 1
                self._render_step()

    def action_close(self) -> None:
        self.dismiss(None)


def advanced_document(session: SessionView) -> Text:
    return labeled_values(
        [
            ("Session ID", session.session_id),
            ("Raw task", session.note),
            ("Command", session.current_command),
            ("Directory", display_path(session.cwd)),
            ("Tool", session.tool.value),
            ("Runtime", session.runtime.value),
            ("Task state", session.task_state.value),
            ("Input state", session.input_state.value),
            ("Logging", "enabled" if session.logging_enabled else "disabled"),
            ("Ownership", "wf-session-manager" if session.owned else "unmanaged"),
        ]
    )


class LogScreen(Screen[str | None]):
    CSS_PATH = "wf.tcss"
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "attach", "Attach"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("t", "toggle_timestamps", "Timestamps"),
        Binding("c", "copy", "Copy"),
    ]

    def __init__(self, service: SessionService, session: SessionView) -> None:
        super().__init__()
        self.service = service
        self.session = session
        self.follow_output = True
        self.show_timestamps = False
        self.rendered_output = ""
        self.captured_at: datetime | None = None

    def compose(self) -> ComposeResult:
        yield Static(f"WF  Logs  {self.session.name}", id="log-header")
        yield Static("", id="log-meta")
        with VerticalScroll(id="log-scroll"):
            yield Static("Loading output...", id="log-output")
        yield Static(
            "Esc Back   r Refresh   f Follow   t Timestamps   c Copy   Enter Attach",
            id="action-bar",
        )

    def on_mount(self) -> None:
        self.action_refresh()

    def action_refresh(self) -> None:
        scroller = self.query_one("#log-scroll", VerticalScroll)
        y = scroller.scroll_offset.y
        try:
            details = self.service.logs(self.session.name)
        except WFError as error:
            self.query_one("#log-output", Static).update(str(error))
            return
        output = details.preview or "No pane output"
        if details.preview_truncated:
            output = f"[older output truncated]\n{output}"
        self.rendered_output = output
        self.captured_at = datetime.now(UTC)
        self._render_output()
        if self.follow_output:
            self.call_after_refresh(scroller.scroll_end, animate=False)
        else:
            self.call_after_refresh(scroller.scroll_to, y=y, animate=False, force=True)

    def _render_output(self) -> None:
        prefix = ""
        if self.show_timestamps and self.captured_at:
            prefix = f"Captured {self.captured_at.astimezone():%Y-%m-%d %H:%M:%S %Z}\n\n"
        self.query_one("#log-output", Static).update(Text(f"{prefix}{self.rendered_output}"))
        lines = len(self.rendered_output.splitlines())
        follow = "following" if self.follow_output else "position preserved"
        self.query_one("#log-meta", Static).update(f"{lines} lines   {follow}")

    def action_toggle_follow(self) -> None:
        self.follow_output = not self.follow_output
        self._render_output()
        if self.follow_output:
            self.query_one("#log-scroll", VerticalScroll).scroll_end(animate=False)

    def action_toggle_timestamps(self) -> None:
        self.show_timestamps = not self.show_timestamps
        self._render_output()

    def action_copy(self) -> None:
        if not self.rendered_output:
            return
        self.app.copy_to_clipboard(self.rendered_output)
        self.notify("Sanitized output copied")

    def action_attach(self) -> None:
        self.dismiss(self.session.name)

    def action_close(self) -> None:
        self.dismiss(None)


class DetailScreen(Screen[str | None]):
    CSS_PATH = "wf.tcss"
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back"),
        Binding("enter", "attach", "Attach"),
        Binding("l", "logs", "Logs"),
    ]

    def __init__(self, service: SessionService, session: SessionView) -> None:
        super().__init__()
        self.service = service
        self.session = session

    def compose(self) -> ComposeResult:
        yield Static(f"WF  Session  {self.session.name}", id="log-header")
        with VerticalScroll(id="detail-screen-scroll"):
            yield Static("", id="detail-screen-content")
        yield Static("Esc Back   Enter Attach   l Logs", id="action-bar")

    def on_mount(self) -> None:
        try:
            details = self.service.inspect(self.session.name)
        except WFError as error:
            self.query_one("#detail-screen-content", Static).update(str(error))
            return
        self.query_one("#detail-screen-content", Static).update(
            inspector_document(details.session, details.preview, details.preview_truncated)
        )

    def action_attach(self) -> None:
        self.dismiss(self.session.name)

    def action_logs(self) -> None:
        self.app.push_screen(LogScreen(self.service, self.session), self._log_result)

    def _log_result(self, target: str | None) -> None:
        if target:
            self.dismiss(target)

    def action_close(self) -> None:
        self.dismiss(None)


def inspector_document(session: SessionView, output: str, truncated: bool) -> Text:
    """Build the narrow-screen inspector as one wrapping document."""
    text = Text()
    notice = detect_activity(session, output)
    text.append(session.name, style="bold")
    text.append(f"\n{session.tool.value.upper()}\n\n", style=TOOL_STYLES[session.tool])
    text.append(section_title("OVERVIEW"))
    text.append("\n")
    text.append(
        labeled_values(
            [
                ("Project", session.project),
                ("Directory", display_path(session.cwd)),
                ("Task", humanize_task(session.note)),
                ("Ownership", "Managed by WF" if session.owned else "Read only"),
                ("Tags", ", ".join(session.tags)),
            ]
        )
    )
    text.append("\n")
    text.append(section_title("STATUS"))
    text.append("\n")
    text.append(
        labeled_values(
            [
                ("Runtime", display_state(session.runtime.value)),
                ("Task", display_state(session.task_state.value)),
                ("Agent", display_state(notice.agent_state.value)),
                ("Input", display_input(session.input_state)),
                ("Windows", str(session.windows)),
                ("Last active", relative_activity(session.last_active_at)),
                ("Logging", "Enabled" if session.logging_enabled else "Disabled"),
            ]
        )
    )
    text.append("\n")
    text.append(section_title("ACTIVITY"))
    text.append("\n")
    style = (
        "bold yellow"
        if notice.level == "warning"
        else "bold red"
        if notice.level == "error"
        else "bold"
    )
    text.append(notice.title, style)
    text.append(f"\n{notice.detail}")
    text.append("\n\n")
    text.append(section_title("RECENT OUTPUT"))
    text.append("\n")
    if truncated:
        text.append("[summary from truncated output]\n", "dim")
    text.append(summarize_output(output, notice))
    text.append("\n\n")
    text.append(section_title("ACTIONS"))
    text.append("\nEnter Attach   l Logs   Esc Back")
    return text


class InteractionMode(StrEnum):
    NORMAL = "normal"
    SEARCH = "search"
    FILTER = "filter"
    FORM = "form"
    PALETTE = "command_palette"
    MANAGE = "manage"
    CONFIRMATION = "confirmation"


@dataclass(frozen=True, slots=True)
class CreateModeContext:
    mode: InteractionMode
    searching: bool
    search_value: str
    selected_name: str | None
    selected_session_id: str | None
    highlighted_option_id: str | None
    scroll_y: int
    focused_id: str | None


class WFApp(App[str | None]):
    """Operational session dashboard; it returns the selected attach target."""

    CSS_PATH = "wf.tcss"
    TITLE = "WF - Workflow Session Manager"
    ENABLE_COMMAND_PALETTE = True
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("q", "quit", "Quit"),
        Binding("enter", "open", "Open"),
        Binding("c", "create", "Create"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("n", "note", "Note"),
        Binding("e", "edit", "Edit"),
        Binding("l", "logs", "Logs"),
        Binding("asterisk", "toggle_pin", "Pin"),
        Binding("d", "manage", "Manage"),
        Binding("r", "refresh", "Refresh"),
        Binding("/", "search", "Search"),
        Binding("f", "filter", "Filter"),
        Binding("p", "command_palette", "Palette"),
        Binding("a", "advanced_details", "Advanced", show=False),
        Binding("t", "cycle_theme", "Theme", show=False),
        Binding("question_mark", "help", "Help"),
        Binding("escape", "escape", "Cancel", show=False),
    ]

    def __init__(
        self,
        service: SessionService,
        *,
        monochrome: bool | None = None,
        hostname: str | None = None,
        theme_mode: str | None = None,
        onboarding: bool = True,
        default_cwd: Path | None = None,
        no_animation: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.sessions: list[SessionView] = []
        self.visible_sessions: list[SessionView] = []
        self.selected_name: str | None = None
        self.selected_session_id: str | None = None
        self.filter_query = ""
        self.filters = FilterState()
        self._search_before = ""
        self._rendering_options = False
        self._expected_option_id: str | None = None
        self._option_sessions: dict[str, SessionView] = {}
        self._option_actions: dict[str, str] = {}
        self._alerts: dict[tuple[str, str], ActivityNotice] = {}
        self.interaction_mode = InteractionMode.NORMAL
        self._create_mode_context: CreateModeContext | None = None
        self._failed_create_result: CreateFormResult | None = None
        self.output_mode = "summary"
        self.tmux_connected = True
        self.refresh_error = ""
        self.last_refreshed_at: datetime | None = None
        self._onboarding_enabled = onboarding
        self._onboarding_checked = False
        self.default_cwd = default_cwd or Path.cwd()
        encoding = locale.getpreferredencoding(False).lower()
        self.ascii_only = os.environ.get("WF_ASCII") == "1" or "utf" not in encoding
        no_color = bool(os.environ.get("NO_COLOR"))
        self.monochrome = no_color if monochrome is None else monochrome
        self.ui_theme = theme_mode or ("monochrome" if self.monochrome else "dark")
        self.hostname = hostname or socket.gethostname()
        configured_motion: str = self.service.config.interface.animations
        env_motion = os.environ.get("WF_MOTION", "").strip().lower()
        if env_motion in {"off", "subtle", "full"}:
            configured_motion = env_motion
        self.motion = (
            "off"
            if no_animation
            or self.service.config.interface.reduce_motion
            or configured_motion == "off"
            or self.monochrome
            else configured_motion
        )

    def compose(self) -> ComposeResult:
        yield Static("", id="app-header")
        with Horizontal(id="search-mode"):
            yield Static("Search", id="search-label")
            yield Input(placeholder="name, tool, task, project, tag", id="search")
            yield Static("Enter apply  Esc cancel", id="search-hint")
        with Horizontal(id="workspace"):
            with Vertical(id="session-pane"):
                yield OptionList(id="sessions")
            with Vertical(id="detail-pane"):
                yield Static("Select a session", id="identity")
                with VerticalScroll(id="inspector-scroll"):
                    with Horizontal(id="overview-status-row"):
                        with Vertical(id="overview-card", classes="inspector-card"):
                            yield Static("OVERVIEW", classes="section-title")
                            yield Static("", id="overview", classes="section-body")
                        with Vertical(id="status-card", classes="inspector-card"):
                            yield Static("STATUS", classes="section-title")
                            yield Static("", id="runtime-status", classes="section-body")
                    with Vertical(id="activity-card", classes="inspector-card"):
                        yield Static("ACTIVITY", classes="section-title")
                        yield Static("", id="activity", classes="section-body")
                    with Vertical(id="output-card", classes="inspector-card output-card"):
                        with Horizontal(id="output-heading"):
                            yield Static("RECENT OUTPUT", classes="section-title")
                            yield Button(
                                "Summary", id="output-summary", classes="output-mode active"
                            )
                            yield Button("Raw", id="output-raw", classes="output-mode")
                            yield Static("", id="output-meta")
                        with VerticalScroll(id="recent-output-scroll"):
                            yield Static("", id="recent-output", classes="section-body output-body")
                with Vertical(id="actions-card", classes="inspector-card"):
                    yield Static("ACTIONS", id="inspector-actions-title", classes="section-title")
                    yield Static("", id="session-actions", classes="section-body")
        yield Static("", id="action-bar")
        yield Static("", id="small-terminal")

    def on_mount(self) -> None:
        self.set_class(self.motion == "off", "motion-off")
        self._set_layout_classes(self.size.width, self.size.height)
        self.refresh_sessions()
        self.query_one("#sessions", OptionList).focus()
        self.set_interval(self.service.config.refresh_interval, self.refresh_sessions)
        self.call_after_refresh(self._maybe_show_onboarding)

    def on_resize(self, event: events.Resize) -> None:
        self._set_layout_classes(event.size.width, event.size.height)
        if not self.has_class("too-small"):
            self._render_options()

    def _set_layout_classes(self, width: int, height: int) -> None:
        for name in (
            "very-wide",
            "wide",
            "medium",
            "narrow",
            "short",
            "too-small",
            "light",
            "monochrome",
        ):
            self.remove_class(name)
        if width < 80 or height < 24:
            self.add_class("too-small")
            self.query_one("#small-terminal", Static).update(
                "The terminal is too small for the WF interface.\n\n"
                f"Minimum: 80x24\nCurrent: {width}x{height}\n\n"
                "Use:\nWF list\nWF --classic"
            )
        elif width >= 140:
            self.add_class("very-wide", "wide")
        elif width >= 120:
            self.add_class("wide")
        elif width >= 100:
            self.add_class("medium")
        else:
            self.add_class("narrow")
        if not self.has_class("too-small") and height <= 35:
            self.add_class("short")
        if self.ui_theme == "light":
            self.add_class("light")
        elif self.ui_theme == "monochrome":
            self.add_class("monochrome")

    def _maybe_show_onboarding(self) -> None:
        if self._onboarding_checked:
            return
        self._onboarding_checked = True
        if self._onboarding_enabled and not self.sessions and not self.service.onboarding_seen():
            self.push_screen(OnboardingScreen(), self._finish_onboarding)

    def _finish_onboarding(self, action: str | None) -> None:
        try:
            self.service.mark_onboarding_seen()
        except (OSError, WFError) as error:
            self.notify(str(error), title="Unable to save onboarding state", severity="warning")
        if action == "create":
            self.action_create()
        elif action == "help":
            self.action_help()

    def _notify_success(self, message: str, *, title: str = "Completed") -> None:
        marker = "OK" if self.ascii_only else "✓"
        self.notify(f"{marker} {message}", title=title)

    def _row_width(self) -> int:
        if self.has_class("wide"):
            return max(28, int(self.size.width * 0.36) - 5)
        if self.has_class("medium"):
            return max(28, int(self.size.width * 0.42) - 5)
        return max(28, self.size.width - 5)

    def refresh_sessions(self) -> None:
        self.add_class("refreshing")
        self._render_header()
        try:
            sessions = self.service.list_sessions()
        except WFError as error:
            self.tmux_connected = False
            self.refresh_error = str(error)
            self.remove_class("refreshing")
            self._render_header()
            self.notify(
                f"{error}\nCheck tmux availability, then press r to retry.",
                title="Refresh failed",
                severity="error",
            )
            return
        self.tmux_connected = True
        self.refresh_error = ""
        if self.selected_name is not None:
            current = next((item for item in sessions if item.name == self.selected_name), None)
            if current is None or current.session_id != self.selected_session_id:
                self.selected_name = None
                self.selected_session_id = None
        self.sessions = sessions
        valid_identities = {(session.name, session.session_id) for session in sessions}
        self._alerts = {
            identity: alert
            for identity, alert in self._alerts.items()
            if identity in valid_identities
        }
        self._render_options()
        self.remove_class("refreshing")
        self.last_refreshed_at = datetime.now(UTC)
        self._render_header()

    def _notice_for(self, session: SessionView) -> ActivityNotice:
        return self._alerts.get((session.name, session.session_id), detect_activity(session, ""))

    def _store_notice(self, session: SessionView, notice: ActivityNotice) -> None:
        identity = (session.name, session.session_id)
        previous = self._alerts.get(identity, detect_activity(session, ""))
        self._alerts[identity] = notice
        option_id = f"session:{session.session_id}"
        if option_id in self._option_sessions:
            prompt = session_row(
                session,
                self._row_width(),
                ascii_only=self.ascii_only,
                notice=notice,
            )
            if self.motion != "off" and notice.warning and notice.kind != previous.kind:
                prompt.stylize("on #4b3b1f")
                self.set_timer(
                    0.45,
                    lambda: self._restore_session_row(session.name, session.session_id),
                )
            self.query_one("#sessions", OptionList).replace_option_prompt(option_id, prompt)

    def _restore_session_row(self, name: str, session_id: str) -> None:
        session = next(
            (item for item in self.sessions if item.name == name and item.session_id == session_id),
            None,
        )
        option_id = f"session:{session_id}"
        if session is None or option_id not in self._option_sessions:
            return
        self.query_one("#sessions", OptionList).replace_option_prompt(
            option_id,
            session_row(
                session,
                self._row_width(),
                ascii_only=self.ascii_only,
                notice=self._notice_for(session),
            ),
        )

    def _matches_query(self, session: SessionView) -> bool:
        if self.filters.tool is not None and session.tool is not self.filters.tool:
            return False
        if self.filters.runtime is not None and session.runtime is not self.filters.runtime:
            return False
        if self.filters.task is not None and session.task_state is not self.filters.task:
            return False
        if self.filters.warnings_only and not is_warning(session, self._notice_for(session)):
            return False
        if self.filters.recent_only:
            if session.last_active_at is None:
                return False
            current = datetime.now(UTC)
            activity = session.last_active_at
            if activity.tzinfo is None:
                activity = activity.replace(tzinfo=UTC)
            if current - activity > RECENT_WINDOW:
                return False
        if not self.filter_query:
            return True
        haystack = " ".join(
            (
                session.name,
                session.display_name,
                session.tool.value,
                session.runtime.value,
                session.task_state.value,
                session.input_state.value,
                session.project,
                session.note,
                str(session.cwd),
                *session.tags,
            )
        ).casefold()
        return self.filter_query.casefold().strip() in haystack

    def _heading_option(self, label: str) -> Option:
        return Option(section_title(label.upper()), id=f"heading:{label.lower()}", disabled=True)

    def _quick_option(self, label: str, action: str, symbol: str) -> Option:
        option_id = f"quick:{action}"
        self._option_actions[option_id] = action
        return Option(Text.assemble((f"{symbol} ", "bold #66aaff"), label), id=option_id)

    def _render_options(self) -> None:
        options = self.query_one("#sessions", OptionList)
        old_scroll = options.scroll_offset.y
        old_identity = (self.selected_name, self.selected_session_id)
        self._rendering_options = True
        options.clear_options()
        self._option_sessions.clear()
        self._option_actions.clear()
        options.add_option(self._heading_option("Quick Actions"))
        options.add_option(self._quick_option("Create session", "create", "+"))
        options.add_option(self._quick_option("Resume recent", "resume", ">"))
        options.add_option(self._quick_option("Open shell", "shell", "$"))
        options.add_option(self._quick_option("Search", "search", "/"))
        options.add_option(self._quick_option("Filter sessions", "filter", "="))
        options.add_option(self._quick_option("Recent activity", "recent", "@"))

        self.visible_sessions = [item for item in self.sessions if self._matches_query(item)]
        groups: dict[str, list[SessionView]] = {
            "Needs Input": [],
            "Pinned": [],
            "Attached": [],
            "Failed": [],
            "Stopped": [],
            "Detached": [],
        }
        now = datetime.now(UTC)
        for session in self.visible_sessions:
            groups[session_group(session, now=now)].append(session)
        selected_index: int | None = None
        first_session_index: int | None = None
        for group_name, group_sessions in groups.items():
            if not group_sessions:
                continue
            options.add_option(self._heading_option(group_name))
            for session in group_sessions:
                option_id = f"session:{session.session_id}"
                self._option_sessions[option_id] = session
                options.add_option(
                    Option(
                        session_row(
                            session,
                            self._row_width(),
                            ascii_only=self.ascii_only,
                            notice=self._notice_for(session),
                        ),
                        id=option_id,
                    )
                )
                if first_session_index is None:
                    first_session_index = options.option_count - 1
                if (session.name, session.session_id) == old_identity:
                    selected_index = options.option_count - 1

        options.add_option(self._heading_option("Maintenance"))
        options.add_option(self._quick_option("Diagnostics", "diagnostics", ">"))
        if selected_index is None:
            selected_index = first_session_index
        if selected_index is not None:
            options.highlighted = selected_index
            selected = options.get_option_at_index(selected_index)
            self._expected_option_id = selected.id
            self._select_option(selected.id)
        else:
            self.selected_name = None
            self.selected_session_id = None
            self._render_empty_state()
        self._rendering_options = False
        self.call_after_refresh(options.scroll_to, y=old_scroll, animate=False, force=True)
        self._render_header()
        self._render_action_bar()

    def _render_header(self) -> None:
        attached = sum(session.runtime is RuntimeState.ATTACHED for session in self.sessions)
        detached = sum(session.runtime is RuntimeState.DETACHED for session in self.sessions)
        warnings = sum(is_warning(session, self._notice_for(session)) for session in self.sessions)
        if not self.tmux_connected:
            warnings += 1
        session_label = "session" if len(self.sessions) == 1 else "sessions"
        warning_text = (
            "No warnings" if warnings == 0 else f"{warnings} warning{'s' if warnings != 1 else ''}"
        )
        separator = " | " if self.ascii_only else " • "
        counts = separator.join(
            (
                f"{len(self.sessions)} {session_label}",
                f"{attached} attached",
                f"{detached} detached",
                warning_text,
            )
        )
        active_filters = self.filters.labels()
        if self.filter_query:
            active_filters.insert(0, f'Search "{self.filter_query}"')
        filter_text = f"{separator}{', '.join(active_filters)}" if active_filters else ""
        connection = "tmux connected" if self.tmux_connected else "tmux unavailable"
        if self.has_class("refreshing"):
            connection = "Refreshing sessions..."
        elif self.last_refreshed_at is not None:
            age = int((datetime.now(UTC) - self.last_refreshed_at).total_seconds())
            updated = "Updated now" if age < 1 else f"Updated {age}s ago"
            connection = f"{connection}{separator}{updated}"
        text = Text()
        text.append("WF", "bold #72c78e")
        if self.has_class("very-wide"):
            text.append(f"  Workflow Session Manager  v{__version__}")
            text.append(f"    {counts}{filter_text}", "dim")
            text.append(f"    {truncate(self.hostname, 22, ascii_only=self.ascii_only)}")
            text.append(f"{separator}{connection}", "green" if self.tmux_connected else "red")
        elif self.has_class("wide"):
            text.append("  Workflow Session Manager")
            text.append(f"    {counts}{filter_text}", "dim")
            text.append(f"{separator}{connection}", "green" if self.tmux_connected else "red")
        elif self.has_class("medium"):
            text.append("  Workflow Session Manager")
            text.append(f"\n{counts}{filter_text}", "dim")
        else:
            text.append(f"  {counts}{filter_text}", "dim")
        self.query_one("#app-header", Static).update(text)

    def _render_action_bar(self) -> None:
        navigation = "Up/Down/jk" if self.ascii_only else "↑↓/jk"
        if self.has_class("searching"):
            query = self.query_one("#search", Input).value
            value = f"SEARCH  {query}_   Enter Apply   Esc Cancel   Ctrl+U Clear"
        elif self.has_class("narrow"):
            value = (
                f"{navigation} Nav   Enter Open   c Create   / Search   f Filter   ? Help   q Quit"
            )
        elif self.has_class("medium"):
            value = (
                f"{navigation} Nav   Enter Attach   c Create   / Search   f Filter   "
                "d Manage   ? Help   q Quit"
            )
        else:
            value = (
                f"{navigation} Navigate   Enter Attach   c Create   / Search   "
                "f Filter   p Palette   d Manage   ? Help   q Quit"
            )
        self.query_one("#action-bar", Static).update(value)

    def action_cursor_down(self) -> None:
        self.query_one("#sessions", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#sessions", OptionList).action_cursor_up()

    def _select_option(self, option_id: str | None) -> None:
        if option_id is None or option_id not in self._option_sessions:
            return
        session = self._option_sessions[option_id]
        self.selected_name = session.name
        self.selected_session_id = session.session_id
        self._render_details(session.name)

    @on(OptionList.OptionHighlighted, "#sessions")
    def option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self._expected_option_id is not None:
            if event.option.id != self._expected_option_id:
                return
            self._expected_option_id = None
        if not self._rendering_options and event.option_index == event.option_list.highlighted:
            self._select_option(event.option.id)

    @on(OptionList.OptionSelected, "#sessions")
    def option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id
        if option_id in self._option_sessions:
            self._select_option(option_id)
            self.action_open()
            return
        action = self._option_actions.get(option_id or "")
        if action:
            getattr(self, f"action_{action}")()

    def _selected(self) -> SessionView | None:
        if self.selected_name is None:
            return None
        return next(
            (
                item
                for item in self.visible_sessions
                if item.name == self.selected_name and item.session_id == self.selected_session_id
            ),
            None,
        )

    def _render_empty_state(self) -> None:
        filtered = bool(self.filter_query) or self.filters.active
        self.query_one("#identity", Static).update("No matches" if filtered else "No sessions")
        self.query_one("#overview", Static).update(
            "No managed sessions match the active filter."
            if filtered
            else "Create a managed session to get started."
        )
        for widget_id in ("#runtime-status", "#activity", "#recent-output", "#session-actions"):
            self.query_one(widget_id, Static).update("")
        self.query_one("#output-meta", Static).update("")

    def _render_details(self, name: str) -> None:
        scroller = self.query_one("#inspector-scroll", VerticalScroll)
        output_scroller = self.query_one("#recent-output-scroll", VerticalScroll)
        old_scroll = scroller.scroll_offset.y
        old_output_scroll = output_scroller.scroll_offset.y
        try:
            details = self.service.inspect(name)
        except WFError as error:
            self.query_one("#overview", Static).update(str(error))
            return
        session = details.session
        notice = detect_activity(session, details.preview)
        self._store_notice(session, notice)
        separator = " / " if self.ascii_only else " · "
        identity = Text()
        identity.append(f"{session.tool.value.upper():<7}", style=TOOL_STYLES[session.tool])
        identity.append(session.name, style="bold")
        if session.pinned:
            identity.append("  *" if self.ascii_only else "  ★", "yellow")
        if notice.warning:
            alert_style = "bold yellow" if notice.level == "warning" else "bold red"
            identity.append(f"  ! {notice.title}", alert_style)
        identity.append(
            "\n"
            + separator.join(
                (
                    display_state(session.runtime.value),
                    display_state(session.task_state.value),
                    f"Last active {relative_activity(session.last_active_at)} ago",
                )
            ),
            RUNTIME_STYLES[session.runtime],
        )
        self.query_one("#identity", Static).update(identity)
        overview_values = [
            ("Task", humanize_task(session.note)),
            ("Project", session.project),
            ("Directory", display_path(session.cwd)),
            ("Ownership", "Managed by WF" if session.owned else "Read only"),
            ("Tags", ", ".join(session.tags)),
        ]
        if session.display_name and session.display_name != session.name:
            overview_values.insert(0, ("Display name", session.display_name))
        status_values = [
            ("Runtime", display_state(session.runtime.value)),
            ("Task", display_state(session.task_state.value)),
            ("Agent", display_state(notice.agent_state.value)),
            ("Input", display_input(session.input_state)),
            ("Windows", str(session.windows)),
            ("Logging", "Enabled" if session.logging_enabled else "Disabled"),
            ("Last active", relative_activity(session.last_active_at)),
        ]
        if self.has_class("medium"):
            overview_values = overview_values[:1]
            status_values = status_values[:4]
        self.query_one("#overview", Static).update(labeled_values(overview_values))
        self.query_one("#runtime-status", Static).update(labeled_values(status_values))
        activity = Text(notice.title, style="bold")
        activity.append(f"\n{notice.detail}")
        activity_card = self.query_one("#activity-card", Vertical)
        activity_card.remove_class("warning", "error", "success")
        if notice.level == "warning":
            activity.stylize("yellow", 0, len(notice.title))
            activity_card.add_class("warning")
        elif notice.level == "error":
            activity.stylize("red", 0, len(notice.title))
            activity_card.add_class("error")
        else:
            activity_card.add_class("success")
        self.query_one("#activity", Static).update(activity)
        preview = Text()
        if self.output_mode == "summary":
            preview = summarize_output(details.preview, notice)
        else:
            if details.preview_truncated:
                preview.append("[older output truncated]\n", "dim")
            preview.append(details.preview or "No pane output")
        self.query_one("#recent-output", Static).update(preview)
        line_count = len(details.preview.splitlines())
        truncated = "truncated" if details.preview_truncated else "complete"
        self.query_one("#output-meta", Static).update(
            f"{self.output_mode.title()}  {line_count} lines  {truncated}  sanitized  l full logs"
        )
        self.query_one("#session-actions", Static).update(
            "Enter Attach   e Edit   n Task   l Logs   r Refresh   * Pin   d Manage"
        )
        self.call_after_refresh(scroller.scroll_to, y=old_scroll, animate=False, force=True)
        self.call_after_refresh(
            output_scroller.scroll_to,
            y=old_output_scroll,
            animate=False,
            force=True,
        )
        self._render_header()

    @on(Button.Pressed, ".output-mode")
    def output_mode_changed(self, event: Button.Pressed) -> None:
        self.output_mode = "raw" if event.button.id == "output-raw" else "summary"
        for mode in ("summary", "raw"):
            self.query_one(f"#output-{mode}", Button).set_class(self.output_mode == mode, "active")
        if self.selected_name:
            self._render_details(self.selected_name)

    @on(Input.Changed, "#search")
    def search_changed(self, event: Input.Changed) -> None:
        if not self.has_class("searching"):
            return
        self.filter_query = event.value.strip()
        self._render_options()

    @on(Input.Submitted, "#search")
    def search_submitted(self) -> None:
        self._finish_search()

    def _finish_search(self) -> None:
        self.remove_class("searching")
        self.interaction_mode = InteractionMode.NORMAL
        self.query_one("#sessions", OptionList).focus()
        self._render_header()
        self._render_action_bar()

    def action_search(self) -> None:
        self._search_before = self.filter_query
        self.add_class("searching")
        self.interaction_mode = InteractionMode.SEARCH
        search = self.query_one("#search", Input)
        search.value = self.filter_query
        search.focus()
        self._render_action_bar()

    def action_filter(self) -> None:
        self.push_screen(FilterScreen(self.filters), self._apply_filter)

    def _apply_filter(self, filters: FilterState | None) -> None:
        if filters is None:
            return
        self.filters = filters
        self._render_options()

    def action_recent(self) -> None:
        self.filters = FilterState(recent_only=True)
        self._render_options()

    def action_cycle_theme(self) -> None:
        modes = ("dark", "light", "monochrome")
        self.ui_theme = modes[(modes.index(self.ui_theme) + 1) % len(modes)]
        self.monochrome = self.ui_theme == "monochrome"
        self._set_layout_classes(self.size.width, self.size.height)
        self._render_options()
        self.notify(f"Theme: {self.ui_theme}")

    def action_escape(self) -> None:
        if not self.has_class("searching"):
            return
        self.filter_query = self._search_before
        self.query_one("#search", Input).value = self.filter_query
        self._finish_search()
        self._render_options()

    def action_open(self) -> None:
        session = self._selected()
        if session is None:
            return
        if session.runtime is RuntimeState.STOPPED:
            self.notify("Restart the stopped session from d Manage.", severity="warning")
            self.action_manage()
            return
        if self.has_class("narrow"):
            self.push_screen(DetailScreen(self.service, session), self._detail_result)
        else:
            self.exit(session.name)

    def _detail_result(self, target: str | None) -> None:
        if target:
            self.exit(target)

    def action_attach(self) -> None:
        self.action_open()

    def action_create(self, tool: Tool = Tool.CLAUDE) -> None:
        options = self.query_one("#sessions", OptionList)
        highlighted_option_id: str | None = None
        if options.highlighted is not None:
            highlighted_option_id = options.get_option_at_index(options.highlighted).id
        focused = self.focused
        self._create_mode_context = CreateModeContext(
            mode=self.interaction_mode,
            searching=self.has_class("searching"),
            search_value=self.query_one("#search", Input).value,
            selected_name=self.selected_name,
            selected_session_id=self.selected_session_id,
            highlighted_option_id=highlighted_option_id,
            scroll_y=options.scroll_offset.y,
            focused_id=focused.id if focused is not None else None,
        )
        self.remove_class("searching")
        self.add_class("form-active")
        self.interaction_mode = InteractionMode.FORM
        self._render_action_bar()
        self.push_screen(
            CreateSessionScreen(self.default_cwd, self.service, tool), self._create_session
        )

    def action_new_session(self) -> None:
        self.action_create()

    def action_shell(self) -> None:
        self.action_create(Tool.SHELL)

    def action_resume(self) -> None:
        try:
            target = self.service.resume_target()
        except WFError as error:
            self.notify(str(error), severity="warning")
            return
        self.exit(target.name)

    def _restore_create_mode(self) -> None:
        context = self._create_mode_context
        self._create_mode_context = None
        self.remove_class("form-active")
        if context is None:
            self.interaction_mode = InteractionMode.NORMAL
            self._render_action_bar()
            return
        self.selected_name = context.selected_name
        self.selected_session_id = context.selected_session_id
        search = self.query_one("#search", Input)
        search.value = context.search_value
        if context.searching:
            self.add_class("searching")
            self.interaction_mode = InteractionMode.SEARCH
        else:
            self.interaction_mode = context.mode
        options = self.query_one("#sessions", OptionList)
        option_ids = {
            options.get_option_at_index(index).id for index in range(options.option_count)
        }
        highlighted_option_id = context.highlighted_option_id
        if highlighted_option_id is not None and highlighted_option_id in option_ids:
            options.highlighted = options.get_option_index(highlighted_option_id)
        self.call_after_refresh(options.scroll_to, y=context.scroll_y, animate=False, force=True)
        focus_target = self.query_one(f"#{context.focused_id}") if context.focused_id else options
        self.call_after_refresh(focus_target.focus)
        self._render_header()
        self._render_action_bar()

    def _insert_created_session(self, session: SessionView) -> None:
        self.sessions.insert(0, session)
        self.visible_sessions.append(session)
        options = self.query_one("#sessions", OptionList)
        option_ids = {
            options.get_option_at_index(index).id for index in range(options.option_count)
        }
        self._rendering_options = True
        for option_id in ("quick:diagnostics", "heading:maintenance"):
            if option_id in option_ids:
                options.remove_option(option_id)
        self._option_actions.pop("quick:diagnostics", None)
        if "heading:detached" not in option_ids:
            options.add_option(self._heading_option("Detached"))
        option_id = f"session:{session.session_id}"
        prompt = session_row(
            session,
            self._row_width(),
            ascii_only=self.ascii_only,
            notice=self._notice_for(session),
        )
        self._option_sessions[option_id] = session
        options.add_option(Option(prompt, id=option_id))
        created_index = options.option_count - 1
        options.add_option(self._heading_option("Maintenance"))
        options.add_option(self._quick_option("Diagnostics", "diagnostics", ">"))
        self._rendering_options = False
        self.selected_name = session.name
        self.selected_session_id = session.session_id
        self._expected_option_id = option_id
        options.highlighted = created_index
        self._select_option(option_id)
        self.call_after_refresh(options.scroll_to_highlight)
        if self.motion != "off":
            self.call_after_refresh(
                self._highlight_created_session, session.name, session.session_id
            )
        self.last_refreshed_at = datetime.now(UTC)
        self._render_header()
        self._render_action_bar()

    def _highlight_created_session(self, name: str, session_id: str) -> None:
        session = next(
            (item for item in self.sessions if item.name == name and item.session_id == session_id),
            None,
        )
        option_id = f"session:{session_id}"
        if session is None or option_id not in self._option_sessions:
            return
        prompt = session_row(
            session,
            self._row_width(),
            ascii_only=self.ascii_only,
            notice=self._notice_for(session),
        )
        prompt.stylize("on #243d55")
        self.query_one("#sessions", OptionList).replace_option_prompt(option_id, prompt)
        self.set_timer(0.5, lambda: self._restore_session_row(name, session_id))

    def _create_session(self, result: CreateFormResult | None) -> None:
        if result is None:
            self._restore_create_mode()
            return
        self._attempt_create(result)

    def _attempt_create(self, result: CreateFormResult) -> None:
        try:
            session = self.service.create(result.request)
        except WFError as error:
            self._failed_create_result = result
            try:
                session_name = normalized_session_name(
                    result.request.tool,
                    result.request.name,
                    automatic_prefix=result.request.automatic_prefix,
                )
                metadata_exists = self.service.store.load(session_name) is not None
            except WFError:
                session_name = result.request.name
                metadata_exists = False
            self.interaction_mode = InteractionMode.CONFIRMATION
            self.notify(
                f"{error}\nRetry, open details, or remove partial metadata if present.",
                title="Session startup failed",
                severity="error",
                timeout=0,
            )
            self.push_screen(
                CreateFailureScreen(
                    session_name,
                    str(error),
                    metadata_exists=metadata_exists,
                ),
                self._creation_failure_action,
            )
            return
        self._failed_create_result = None
        self._restore_create_mode()
        self._insert_created_session(session)
        self._notify_success(f"Session created: {session.name}", title="Session ready")
        if result.start_attached:
            self.exit(session.name)

    def _creation_failure_action(self, action: str | None) -> None:
        result = self._failed_create_result
        if action == "retry" and result is not None:
            self.interaction_mode = InteractionMode.FORM
            self._attempt_create(result)
            return
        if action == "remove" and result is not None:
            try:
                session_name = normalized_session_name(
                    result.request.tool,
                    result.request.name,
                    automatic_prefix=result.request.automatic_prefix,
                )
                self.service.remove_metadata(session_name)
                self._notify_success(f"Metadata removed: {session_name}")
            except WFError as error:
                self.notify(str(error), title="Metadata removal failed", severity="error")
        self._failed_create_result = None
        self._restore_create_mode()
        if action == "details" and result is not None:
            self.push_screen(
                MessageScreen(
                    "Startup Failure Details",
                    "The tool process did not start. No active session was adopted or renamed.\n\n"
                    "Run System Diagnostics, verify the configured executable, and retry creation.",
                )
            )

    def action_edit(self) -> None:
        session = self._selected()
        if session:
            self.push_screen(EditSessionScreen(session), self._edit_session)

    def _edit_session(self, result: EditResult | None) -> None:
        session = self._selected()
        if result is None or session is None:
            return
        try:
            updated = session
            if result.name != session.name:
                updated = self.service.rename(session.name, result.name)
            updated = self.service.organize(
                updated.name,
                tags=result.tags,
                state=result.task_state,
                input_state=result.input_state,
                project=result.project,
                pinned=result.pinned,
            )
        except WFError as error:
            self.notify(str(error), title="Save failed", severity="error")
            return
        self.selected_name = updated.name
        self.selected_session_id = updated.session_id
        self._notify_success("Session details updated")
        self.refresh_sessions()

    def action_note(self) -> None:
        session = self._selected()
        if session:
            self.push_screen(NoteScreen(session), self._save_note)

    def _save_note(self, note: str | None) -> None:
        session = self._selected()
        if note is None or session is None:
            return
        try:
            self.service.update_note(session.name, note)
        except WFError as error:
            self.notify(str(error), title="Save failed", severity="error")
            return
        self._notify_success("Task updated")
        self.refresh_sessions()

    def action_logs(self) -> None:
        session = self._selected()
        if session:
            self.push_screen(LogScreen(self.service, session), self._detail_result)

    def action_toggle_pin(self) -> None:
        session = self._selected()
        if session is None:
            return
        try:
            updated = self.service.organize(session.name, pinned=not session.pinned)
        except WFError as error:
            self.notify(str(error), severity="warning")
            return
        self.selected_name = updated.name
        self.selected_session_id = updated.session_id
        self._notify_success("Session unpinned" if session.pinned else "Session pinned")
        self.refresh_sessions()

    def action_manage(self) -> None:
        session = self._selected()
        if session:
            self.push_screen(ManageSessionScreen(session), self._manage_action)

    def action_more_actions(self) -> None:
        self.action_manage()

    def action_delete_session(self) -> None:
        self.action_manage()

    def _manage_action(self, action: str | None) -> None:
        session = self._selected()
        if action is None or session is None:
            return
        if action == "edit" or action == "status":
            self.action_edit()
        elif action == "note":
            self.action_note()
        elif action == "pin":
            self.action_toggle_pin()
        elif action == "advanced":
            self.action_advanced_details()
        elif action == "logging":
            try:
                updated = self.service.set_logging(session.name, not session.logging_enabled)
            except (WFError, OSError) as error:
                self.notify(str(error), title="Logging update failed", severity="error")
                return
            self.selected_name = updated.name
            self.selected_session_id = updated.session_id
            self._notify_success(
                "Logging enabled" if updated.logging_enabled else "Logging disabled"
            )
            self.refresh_sessions()
        elif action == "delete":
            self.push_screen(DeleteSessionScreen(session.name), self._delete_session)
        else:
            confirmations = {
                "restart": (
                    "Restart Tool",
                    "The current pane command will be replaced and restarted.",
                ),
                "stop-command": (
                    "Stop Command",
                    "WF will send Ctrl+C to the active pane. The tmux session remains available.",
                ),
                "stop-session": (
                    "Stop tmux Session",
                    "The tmux session will stop. WF metadata and sanitized logs are retained.",
                ),
                "remove-metadata": (
                    "Remove WF Metadata",
                    "The tmux session remains running but disappears from managed WF views.",
                ),
                "delete-logs": (
                    "Delete Logs",
                    "Persisted sanitized logs will be permanently removed.",
                ),
            }
            title, consequence = confirmations[action]
            self.push_screen(
                ConfirmActionScreen(title, session.name, consequence),
                lambda confirmed, selected=action, name=session.name: self._confirmed_manage(
                    selected, name, confirmed
                ),
            )

    def _confirmed_manage(self, action: str, name: str, confirmed: bool) -> None:
        if not confirmed:
            return
        try:
            if action == "restart":
                updated = self.service.restart(name)
                self.selected_name = updated.name
                self.selected_session_id = updated.session_id
                message = "Session restarted"
            elif action == "stop-command":
                self.service.stop_command(name)
                message = "Interrupt sent"
            elif action == "stop-session":
                updated = self.service.stop_session(name)
                self.selected_name = updated.name
                self.selected_session_id = updated.session_id
                message = "tmux session stopped; metadata retained"
            elif action == "remove-metadata":
                self.service.remove_metadata(name)
                self.selected_name = None
                self.selected_session_id = None
                message = "WF metadata removed"
            elif action == "delete-logs":
                self.service.delete_logs(name)
                message = "Sanitized logs deleted"
            else:
                return
        except (WFError, OSError) as error:
            self.notify(str(error), title=f"{display_state(action)} failed", severity="error")
            return
        self._notify_success(message)
        self.refresh_sessions()

    def action_advanced_details(self) -> None:
        session = self._selected()
        if session:
            self.push_screen(MessageScreen("Advanced Details", advanced_document(session)))

    def _delete_session(self, confirmed: bool | None) -> None:
        session = self._selected()
        if not confirmed or session is None:
            return
        try:
            self.service.delete(session.name)
        except (WFError, OSError) as error:
            self.notify(str(error), title="Delete failed", severity="error")
            return
        self.selected_name = None
        self.selected_session_id = None
        self._notify_success(f"Deleted {session.name}")
        self.refresh_sessions()

    def action_diagnostics(self) -> None:
        self.push_screen(DiagnosticsScreen(self.service))

    def action_help(self) -> None:
        self.push_screen(
            MessageScreen(
                "Keyboard help",
                "Up/Down or j/k  Navigate\n"
                "Enter    Attach or open details\n"
                "c        Create session\n"
                "/        Search\n"
                "f        Filter sessions\n"
                "e        Edit selected session\n"
                "n        Edit task\n"
                "l        View logs\n"
                "*        Toggle pin\n"
                "d        Manage session\n"
                "r        Refresh\n"
                "p        Command palette\n"
                "t        Cycle color theme\n"
                "q        Quit",
            )
        )

    def action_refresh(self) -> None:
        self.refresh_sessions()
