"""Responsive Textual dashboard for persistent workflow sessions."""

from __future__ import annotations

import locale
import os
import re
import shlex
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Checkbox, Input, Label, OptionList, Select, Static, Switch
from textual.widgets.option_list import Option

from wf_session_manager import __version__
from wf_session_manager.errors import WFError
from wf_session_manager.models import (
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
from wf_session_manager.service import SessionService

BindingSpec = Binding | tuple[str, str] | tuple[str, str, str]
RECENT_WINDOW = timedelta(hours=24)
USAGE_LIMIT_PATTERN = re.compile(
    r"(?im)^(?P<tool>codex|claude|hermes)?[^\n]{0,32}usage limit "
    r"(?:has been )?(?:reached|exceeded)[^\n]*$"
)
RETRY_PATTERN = re.compile(
    r"(?im)^(?:retry(?: available)?|try again|available again)"
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


def detect_activity(session: SessionView, output: str) -> ActivityNotice:
    usage = USAGE_LIMIT_PATTERN.search(output)
    if usage:
        tool = (usage.group("tool") or session.tool.value).title()
        retry = RETRY_PATTERN.search(output)
        detail = f"Retry available: {retry.group('when').strip()}" if retry else "Try again later."
        return ActivityNotice("warning", f"{tool} usage limit reached", detail)
    if session.input_state is InputState.REQUIRED or session.task_state is TaskState.NEEDS_INPUT:
        return ActivityNotice(
            "warning",
            "Input required",
            "This status was explicitly set for the session.",
        )
    if session.runtime is RuntimeState.FAILED:
        return ActivityNotice(
            "error", "Session failed", "The active pane exited with a failure status."
        )
    if session.task_state is TaskState.BLOCKED:
        return ActivityNotice("warning", "Task blocked", "Review the task note before continuing.")
    return ActivityNotice("neutral", "No action required", "The session can continue normally.")


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


def is_warning(session: SessionView) -> bool:
    return (
        session.input_state is InputState.REQUIRED
        or session.task_state is TaskState.NEEDS_INPUT
        or session.task_state is TaskState.BLOCKED
        or session.runtime is RuntimeState.FAILED
    )


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


def session_row(session: SessionView, width: int, *, ascii_only: bool = False) -> Text:
    """Build a stable two-line row sized to its current pane."""
    marker = ("*" if ascii_only else "★") if session.pinned else "!" if is_warning(session) else " "
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


@dataclass(frozen=True, slots=True)
class EditResult:
    name: str
    project: str
    tags: list[str]
    task_state: TaskState
    input_state: InputState
    pinned: bool


class CreateSessionScreen(ModalScreen[CreateRequest | None]):
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

    def _recent_directories(self) -> list[tuple[str, str]]:
        directories = [self.default_cwd]
        if self.service:
            for session in self.service.list_sessions():
                if session.cwd not in directories:
                    directories.append(session.cwd)
        return [(display_path(path), str(path)) for path in directories[:8]]

    def compose(self) -> ComposeResult:
        with Vertical(id="create-dialog", classes="dialog create-dialog"):
            yield Label("Create Session", classes="dialog-title")
            with VerticalScroll(id="create-form"):
                with Horizontal(classes="form-row"):
                    yield Label("Tool", classes="field-label")
                    yield Select(
                        [(TOOL_LABELS[tool], tool.value) for tool in Tool],
                        value=self.default_tool.value,
                        allow_blank=False,
                        id="create-tool",
                    )
                with Horizontal(classes="form-row"):
                    yield Label("Session name", classes="field-label")
                    yield Input(placeholder="api-refactor", id="create-name")
                with Horizontal(classes="form-row"):
                    yield Label("Task", classes="field-label")
                    yield Input(placeholder="Improve API authentication", id="create-note")
                with Horizontal(classes="form-row"):
                    yield Label("Working directory", classes="field-label")
                    yield Input(value=display_path(self.default_cwd), id="create-cwd")
                with Horizontal(classes="form-row"):
                    yield Label("Recent directory", classes="field-label secondary-field")
                    yield Select(
                        self._recent_directories(),
                        value=str(self.default_cwd),
                        allow_blank=False,
                        id="create-recent-dir",
                    )
                with Horizontal(classes="form-row"):
                    yield Label("Project", classes="field-label")
                    yield Input(placeholder="api-platform", id="create-project")
                with Horizontal(classes="form-row"):
                    yield Label("Tags", classes="field-label")
                    yield Input(placeholder="backend, urgent", id="create-tags")
                with Horizontal(id="logging-row"):
                    yield Label("Logging", classes="field-label")
                    yield Switch(value=True, id="create-logging")
                    yield Static("Sanitized, owner-only, size-limited", id="logging-hint")
            with Horizontal(classes="preview-row"):
                yield Label("Command", classes="field-label")
                yield Static("", id="command-preview")
            with Horizontal(classes="validation-row"):
                yield Label("Validation", classes="field-label")
                yield Static("", id="create-validation")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="create-cancel")
                yield Button("Create Session", variant="primary", id="create-submit", disabled=True)

    def on_mount(self) -> None:
        self._validate()
        self.query_one("#create-name", Input).focus()

    def _parse_tags(self) -> list[str]:
        value = self.query_one("#create-tags", Input).value
        return normalize_tags([item for item in re.split(r"[\s,]+", value) if item])

    def _validate(self) -> None:
        tool = Tool(str(self.query_one("#create-tool", Select).value))
        cwd = Path(self.query_one("#create-cwd", Input).value).expanduser()
        name = self.query_one("#create-name", Input).value
        if self.service:
            validation = self.service.validate_create(tool, name, cwd)
            command = validation.command
            errors = list(validation.errors)
            project_input = self.query_one("#create-project", Input)
            if validation.detected_project and (
                not project_input.value or project_input.value == self._detected_project
            ):
                self._detected_project = validation.detected_project
                project_input.value = validation.detected_project
        else:
            validation = None
            command = (tool.value,)
            errors = [] if name and cwd.is_dir() else ["Enter a name and existing directory"]
        try:
            self._parse_tags()
        except ValueError as validation_error:
            errors.append(str(validation_error))
        preview = shlex.join(command)
        self.query_one("#command-preview", Static).update(preview)
        status = Text()
        if errors:
            for issue in errors[:3]:
                status.append("x ", "bold red")
                status.append(f"{issue}\n")
        else:
            normalized = validation.normalized_name if validation else name
            status.append(f"+ Session name available: {normalized}\n", "green")
            status.append("+ Working directory exists", "green")
        self.query_one("#create-validation", Static).update(status)
        self.query_one("#create-submit", Button).disabled = bool(errors)

    @on(Select.Changed, "#create-tool")
    def tool_changed(self) -> None:
        self._validate()

    @on(Select.Changed, "#create-recent-dir")
    def recent_directory_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK:
            self.query_one("#create-cwd", Input).value = display_path(Path(str(event.value)))

    @on(Input.Changed)
    def input_changed(self, event: Input.Changed) -> None:
        if event.input.id and event.input.id.startswith("create-"):
            self._validate()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-cancel":
            self.dismiss(None)
            return
        if event.button.id != "create-submit":
            return
        self.action_submit()

    def action_submit(self) -> None:
        button = self.query_one("#create-submit", Button)
        if button.disabled:
            return
        try:
            request = CreateRequest(
                name=self.query_one("#create-name", Input).value,
                tool=Tool(str(self.query_one("#create-tool", Select).value)),
                cwd=Path(self.query_one("#create-cwd", Input).value).expanduser(),
                project=self.query_one("#create-project", Input).value.strip(),
                note=self.query_one("#create-note", Input).value.strip(),
                tags=self._parse_tags(),
                logging_enabled=self.query_one("#create-logging", Switch).value,
            )
        except ValueError as error:
            self.notify(str(error), title="Cannot create session", severity="error")
            return
        self.dismiss(request)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
            yield Button("Restart tool", id="manage-restart")
            yield Static("Protected operations", classes="manage-section danger-title")
            yield Button("Stop command", id="manage-stop-command", disabled=stopped)
            yield Button("Stop tmux session", variant="error", id="manage-stop", disabled=stopped)
            yield Button("Remove WF metadata", variant="error", id="manage-remove-metadata")
            yield Button("Delete logs", variant="error", id="manage-delete-logs")
            yield Button("Delete session and metadata", variant="error", id="more-delete")
            yield Button("Cancel", id="more-cancel")

    def on_mount(self) -> None:
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
        return "Detected" if check.status is HealthStatus.PASS else "Not detected"
    return check.detail.replace(str(Path.home()), "~")


class DiagnosticsScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, service: SessionService) -> None:
        super().__init__()
        self.service = service
        self.report: DoctorReport = service.doctor()
        self.show_details = False

    def compose(self) -> ComposeResult:
        with Vertical(id="diagnostics-dialog", classes="dialog diagnostics-dialog"):
            yield Label("System Diagnostics", classes="dialog-title")
            yield Static("", id="diagnostics-summary")
            with VerticalScroll(id="diagnostics-list"):
                yield Static("", id="diagnostics-content")
            with Horizontal(classes="dialog-actions diagnostics-actions"):
                yield Button("Run Again", id="diagnostics-run")
                yield Button("Export Report", id="diagnostics-export")
                yield Button("Show Details", id="diagnostics-details")
                yield Button("Close", variant="primary", id="diagnostics-close")

    def on_mount(self) -> None:
        self._render_report()
        self.query_one("#diagnostics-close", Button).focus()

    def _render_report(self) -> None:
        passed = self.report.count(HealthStatus.PASS)
        warnings = self.report.count(HealthStatus.WARN)
        failed = self.report.count(HealthStatus.FAIL)
        self.query_one("#diagnostics-summary", Static).update(
            f"{passed} passed   {warnings} warnings   {failed} failed"
        )
        content = Text()
        for check in self.report.checks:
            style = "green" if check.status is HealthStatus.PASS else "yellow"
            if check.status is HealthStatus.FAIL:
                style = "bold red"
            content.append(f"{check.status.value.upper():<5}", style)
            content.append(f"{diagnostic_name(check):<22}", "bold")
            content.append(f"{diagnostic_detail(check, expanded=self.show_details)}\n")
            if check.status is not HealthStatus.PASS and check.corrective_action:
                content.append(f"     Action: {check.corrective_action}\n", "dim")
        self.query_one("#diagnostics-content", Static).update(content)
        self.query_one("#diagnostics-details", Button).label = (
            "Hide Details" if self.show_details else "Show Details"
        )

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "diagnostics-close":
            self.dismiss(None)
        elif event.button.id == "diagnostics-run":
            self.report = self.service.doctor()
            self._render_report()
            self.notify("Diagnostics refreshed")
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

    def action_close(self) -> None:
        self.dismiss(None)


class OnboardingScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="onboarding-dialog", classes="dialog small-dialog"):
            yield Label("Welcome to WF", classes="dialog-title")
            yield Static(
                "WF keeps Claude Code, Codex, Hermes, and shell work running in tmux after SSH "
                "disconnects. Create a session or review the keyboard help to begin.",
                id="onboarding-copy",
            )
            with Horizontal(classes="dialog-actions"):
                yield Button("View Help", id="onboarding-help")
                yield Button("Create Session", id="onboarding-create")
                yield Button("Close", variant="primary", id="onboarding-close")

    def on_mount(self) -> None:
        self.query_one("#onboarding-close", Button).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "onboarding-help": "help",
            "onboarding-create": "create",
            "onboarding-close": None,
        }
        self.dismiss(actions.get(event.button.id or ""))

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
    notice = detect_activity(session, output)
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
        text.append("[older output truncated]\n", "dim")
    text.append(output or "No pane output")
    text.append("\n\n")
    text.append(section_title("ACTIONS"))
    text.append("\nEnter Attach   l Logs   Esc Back")
    return text


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
        self._output_warnings: set[str] = set()
        self.tmux_connected = True
        self._onboarding_enabled = onboarding
        self._onboarding_checked = False
        encoding = locale.getpreferredencoding(False).lower()
        self.ascii_only = os.environ.get("WF_ASCII") == "1" or "utf" not in encoding
        no_color = bool(os.environ.get("NO_COLOR"))
        self.monochrome = no_color if monochrome is None else monochrome
        self.ui_theme = theme_mode or ("monochrome" if self.monochrome else "dark")
        self.hostname = hostname or socket.gethostname()

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
                            yield Static("", id="output-meta")
                        with VerticalScroll(id="recent-output-scroll"):
                            yield Static("", id="recent-output", classes="section-body output-body")
                with Vertical(id="actions-card", classes="inspector-card"):
                    yield Static("ACTIONS", id="inspector-actions-title", classes="section-title")
                    yield Static("", id="session-actions", classes="section-body")
        yield Static("", id="action-bar")
        yield Static("", id="small-terminal")

    def on_mount(self) -> None:
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
            self.remove_class("refreshing")
            self._render_header()
            self.notify(
                f"{error}\nCheck tmux availability, then press r to retry.",
                title="Refresh failed",
                severity="error",
            )
            return
        self.tmux_connected = True
        if self.selected_name is not None:
            current = next((item for item in sessions if item.name == self.selected_name), None)
            if current is None or current.session_id != self.selected_session_id:
                self.selected_name = None
                self.selected_session_id = None
        self.sessions = sessions
        self._render_options()
        self.remove_class("refreshing")
        self._render_header()

    def _matches_query(self, session: SessionView) -> bool:
        if self.filters.tool is not None and session.tool is not self.filters.tool:
            return False
        if self.filters.runtime is not None and session.runtime is not self.filters.runtime:
            return False
        if self.filters.task is not None and session.task_state is not self.filters.task:
            return False
        if self.filters.warnings_only and not is_warning(session):
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
                        session_row(session, self._row_width(), ascii_only=self.ascii_only),
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
        warnings = sum(
            is_warning(session) or session.name in self._output_warnings
            for session in self.sessions
        )
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
            connection = "refreshing"
        text = Text()
        text.append("WF", "bold #72c78e")
        if self.has_class("very-wide"):
            text.append(f"  Workflow Session Manager  v{__version__}")
            text.append(f"    {counts}{filter_text}", "dim")
            text.append(f"    {truncate(self.hostname, 22, ascii_only=self.ascii_only)}")
            text.append(f"{separator}{connection}", "green" if self.tmux_connected else "red")
        elif self.has_class("wide"):
            text.append(f"  Workflow Session Manager  v{__version__}")
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
            value = "Type to filter   Enter Apply   Esc Cancel"
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
        separator = " / " if self.ascii_only else " · "
        identity = Text()
        identity.append(f"{session.tool.value.upper():<7}", style=TOOL_STYLES[session.tool])
        identity.append(session.name, style="bold")
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
        status_values = [
            ("Runtime", display_state(session.runtime.value)),
            ("Task", display_state(session.task_state.value)),
            ("Input", display_input(session.input_state)),
            ("Windows", str(session.windows)),
            ("Logging", "Enabled" if session.logging_enabled else "Disabled"),
            ("Last active", relative_activity(session.last_active_at)),
        ]
        if self.has_class("medium"):
            overview_values = overview_values[:1]
            status_values = status_values[:3]
        self.query_one("#overview", Static).update(labeled_values(overview_values))
        self.query_one("#runtime-status", Static).update(labeled_values(status_values))
        notice = detect_activity(session, details.preview)
        activity = Text(notice.title, style="bold")
        activity.append(f"\n{notice.detail}")
        activity_card = self.query_one("#activity-card", Vertical)
        activity_card.remove_class("warning", "error", "success")
        if notice.level == "warning":
            activity.stylize("yellow", 0, len(notice.title))
            activity_card.add_class("warning")
            self._output_warnings.add(session.name)
        elif notice.level == "error":
            activity.stylize("red", 0, len(notice.title))
            activity_card.add_class("error")
            self._output_warnings.add(session.name)
        else:
            activity_card.add_class("success")
            self._output_warnings.discard(session.name)
        self.query_one("#activity", Static).update(activity)
        preview = Text()
        if details.preview_truncated:
            preview.append("[older output truncated]\n", "dim")
        preview.append(details.preview or "No pane output")
        self.query_one("#recent-output", Static).update(preview)
        line_count = len(details.preview.splitlines())
        truncated = "truncated" if details.preview_truncated else "complete"
        self.query_one("#output-meta", Static).update(
            f"{line_count} lines  {truncated}  sanitized  l full logs"
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
        self.query_one("#sessions", OptionList).focus()
        self._render_header()
        self._render_action_bar()

    def action_search(self) -> None:
        self._search_before = self.filter_query
        self.add_class("searching")
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
        self.push_screen(CreateSessionScreen(Path.cwd(), self.service, tool), self._create_session)

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

    def _create_session(self, request: CreateRequest | None) -> None:
        if request is None:
            return
        try:
            session = self.service.create(request)
        except WFError as error:
            self.notify(str(error), title="Create failed", severity="error")
            return
        self.selected_name = session.name
        self.selected_session_id = session.session_id
        self.notify(f"Created {session.name}", title="Session ready")
        self.refresh_sessions()

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
            self.notify("Logging enabled" if updated.logging_enabled else "Logging disabled")
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
        self.notify(message)
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
        self.notify(f"Deleted {session.name}")
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
