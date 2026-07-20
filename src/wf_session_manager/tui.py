"""Responsive Textual dashboard for persistent workflow sessions."""

from __future__ import annotations

import locale
import os
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
from textual.widgets import Button, Checkbox, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from wf_session_manager import __version__
from wf_session_manager.errors import WFError
from wf_session_manager.models import (
    CreateRequest,
    InputState,
    RuntimeState,
    SessionView,
    TaskState,
    Tool,
)
from wf_session_manager.service import SessionService

BindingSpec = Binding | tuple[str, str] | tuple[str, str, str]
RECENT_WINDOW = timedelta(hours=24)
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


def relative_activity(value: datetime | None, *, now: datetime | None = None) -> str:
    if value is None:
        return "unknown"
    current = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    seconds = max(0, int((current - value).total_seconds()))
    if seconds < 60:
        return "now"
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
    current = now or datetime.now(UTC)
    if session.last_active_at and current - session.last_active_at <= RECENT_WINDOW:
        return "Recent"
    return "Detached"


def session_row(session: SessionView, width: int, *, ascii_only: bool = False) -> Text:
    """Build a stable two-line row sized to its current pane."""
    marker = "*" if session.pinned else "!" if is_warning(session) else " "
    tool = session.tool.value.upper()
    when = relative_activity(session.last_active_at)
    name_width = max(10, width - len(tool) - len(when) - 7)
    name = truncate(session.name, name_width, ascii_only=ascii_only)
    first = Text()
    first.append(f"{marker} ", style="#e9b44c" if marker != " " else "")
    first.append(f"{tool:<7}", style=TOOL_STYLES[session.tool])
    first.append(f"{name:<{name_width}} ", style="bold #eef3f6")
    first.append(when, style="#9aa6ad")
    separator = " / " if ascii_only else " · "
    statuses = [display_state(session.runtime.value), display_state(session.task_state.value)]
    if session.input_state is InputState.REQUIRED:
        statuses.append("Input required")
    second_value = truncate(separator.join(statuses), max(12, width - 3), ascii_only=ascii_only)
    first.append("\n  ")
    first.append(second_value, style=RUNTIME_STYLES[session.runtime])
    return first


def section_title(label: str) -> Text:
    return Text(label, style="bold #8fa1ac")


def labeled_values(values: list[tuple[str, str]]) -> Text:
    result = Text()
    for label, value in values:
        if not value:
            continue
        result.append(f"{label:<12}", style="#8fa1ac")
        result.append(value, style="#e8edf0")
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
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

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

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="create-dialog", classes="dialog"):
            yield Label("Create session", classes="dialog-title")
            yield Label("Tool", classes="field-label")
            yield Select(
                [(tool.value.title(), tool.value) for tool in Tool],
                value=self.default_tool.value,
                allow_blank=False,
                id="create-tool",
            )
            yield Label("Name", classes="field-label")
            yield Input(placeholder="api-refactor", id="create-name")
            yield Label("Task", classes="field-label")
            yield Input(placeholder="What this session should accomplish", id="create-note")
            yield Label("Directory", classes="field-label")
            yield Input(value=str(self.default_cwd), id="create-cwd")
            yield Label("Project", classes="field-label")
            yield Input(placeholder="api-platform", id="create-project")
            yield Label("Tags", classes="field-label")
            yield Input(placeholder="backend urgent", id="create-tags")
            yield Label("Command preview", classes="field-label")
            yield Static("", id="command-preview")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="create-cancel")
                yield Button("Create", variant="primary", id="create-submit")

    def on_mount(self) -> None:
        self._render_command_preview()
        self.query_one("#create-name", Input).focus()

    def _render_command_preview(self) -> None:
        tool = Tool(str(self.query_one("#create-tool", Select).value))
        command = self.service.config.tools[tool].command if self.service else (tool.value,)
        self.query_one("#command-preview", Static).update(shlex.join(command))

    @on(Select.Changed, "#create-tool")
    def tool_changed(self) -> None:
        self._render_command_preview()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-cancel":
            self.dismiss(None)
            return
        if event.button.id != "create-submit":
            return
        try:
            request = CreateRequest(
                name=self.query_one("#create-name", Input).value,
                tool=Tool(str(self.query_one("#create-tool", Select).value)),
                cwd=Path(self.query_one("#create-cwd", Input).value),
                project=self.query_one("#create-project", Input).value,
                note=self.query_one("#create-note", Input).value,
                tags=self.query_one("#create-tags", Input).value.split(),
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


class MoreActionsScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session_name: str) -> None:
        super().__init__()
        self.session_name = session_name

    def compose(self) -> ComposeResult:
        with Vertical(id="more-dialog", classes="dialog small-dialog"):
            yield Label("More actions", classes="dialog-title")
            yield Static(self.session_name, classes="dialog-context")
            yield Button("Delete session and metadata", variant="error", id="more-delete")
            yield Button("Cancel", id="more-cancel")

    def on_mount(self) -> None:
        self.query_one("#more-cancel", Button).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "more-delete":
            self.dismiss("delete")
        elif event.button.id == "more-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


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


class LogScreen(Screen[str | None]):
    CSS_PATH = "wf.tcss"
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "attach", "Attach"),
    ]

    def __init__(self, service: SessionService, session: SessionView) -> None:
        super().__init__()
        self.service = service
        self.session = session

    def compose(self) -> ComposeResult:
        yield Static(f"WF  Logs  {self.session.name}", id="log-header")
        with VerticalScroll(id="log-scroll"):
            yield Static("Loading output...", id="log-output")
        yield Static("Esc Back   r Refresh   Enter Attach", id="action-bar")

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
        self.query_one("#log-output", Static).update(Text(output))
        self.call_after_refresh(scroller.scroll_to, y=y, animate=False, force=True)

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
    text.append(session.name, style="bold #eef3f6")
    text.append(f"\n{session.tool.value.upper()}\n\n", style=TOOL_STYLES[session.tool])
    text.append(section_title("OVERVIEW"))
    text.append("\n")
    text.append(
        labeled_values(
            [
                ("Project", session.project),
                ("Directory", display_path(session.cwd)),
                ("Task", session.note),
                ("Ownership", "Managed by WF" if session.owned else "Read only"),
                ("Windows", str(session.windows)),
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
                ("Last active", relative_activity(session.last_active_at)),
            ]
        )
    )
    text.append("\n")
    text.append(section_title("ACTIVITY"))
    text.append("\n")
    if session.input_state is InputState.REQUIRED:
        text.append("Input required. This status was explicitly set for the session.", "#e9b44c")
    else:
        text.append(f"Task is {display_state(session.task_state.value).lower()}.")
    text.append("\n\n")
    text.append(section_title("RECENT OUTPUT"))
    text.append("\n")
    if truncated:
        text.append("[older output truncated]\n", "#9aa6ad")
    text.append(output or "No pane output", "#cbd3d8")
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
        Binding("n", "note", "Note"),
        Binding("e", "edit", "Edit"),
        Binding("l", "logs", "Logs"),
        Binding("asterisk", "toggle_pin", "Pin"),
        Binding("d", "more_actions", "More"),
        Binding("r", "refresh", "Refresh"),
        Binding("/", "search", "Search"),
        Binding("p", "command_palette", "Palette"),
        Binding("question_mark", "help", "Help"),
        Binding("escape", "escape", "Cancel", show=False),
    ]

    def __init__(
        self,
        service: SessionService,
        *,
        monochrome: bool | None = None,
        hostname: str | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.sessions: list[SessionView] = []
        self.visible_sessions: list[SessionView] = []
        self.selected_name: str | None = None
        self.selected_session_id: str | None = None
        self.filter_query = ""
        self._search_before = ""
        self._rendering_options = False
        self._expected_option_id: str | None = None
        self._option_sessions: dict[str, SessionView] = {}
        self._option_actions: dict[str, str] = {}
        encoding = locale.getpreferredencoding(False).lower()
        self.ascii_only = os.environ.get("WF_ASCII") == "1" or "utf" not in encoding
        self.monochrome = bool(os.environ.get("NO_COLOR")) if monochrome is None else monochrome
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
                    yield Static("OVERVIEW", classes="section-title")
                    yield Static("", id="overview", classes="section-body")
                    yield Static("STATUS", classes="section-title")
                    yield Static("", id="runtime-status", classes="section-body")
                    yield Static("ACTIVITY", classes="section-title")
                    yield Static("", id="activity", classes="section-body")
                    yield Static("RECENT OUTPUT", classes="section-title")
                    yield Static("", id="recent-output", classes="section-body output-body")
                yield Static("ACTIONS", id="inspector-actions-title", classes="section-title")
                yield Static("", id="session-actions", classes="section-body")
        yield Static("", id="action-bar")
        yield Static("", id="small-terminal")

    def on_mount(self) -> None:
        self._set_layout_classes(self.size.width, self.size.height)
        self.refresh_sessions()
        self.query_one("#sessions", OptionList).focus()
        self.set_interval(self.service.config.refresh_interval, self.refresh_sessions)

    def on_resize(self, event: events.Resize) -> None:
        self._set_layout_classes(event.size.width, event.size.height)
        if not self.has_class("too-small"):
            self._render_options()

    def _set_layout_classes(self, width: int, height: int) -> None:
        for name in ("wide", "medium", "narrow", "short", "too-small", "monochrome"):
            self.remove_class(name)
        if width < 80 or height < 24:
            self.add_class("too-small")
            self.query_one("#small-terminal", Static).update(
                "The terminal is too small for the WF interface.\n\n"
                f"Minimum: 80x24\nCurrent: {width}x{height}\n\nUse: WF list"
            )
        elif width >= 120:
            self.add_class("wide")
        elif width >= 100:
            self.add_class("medium")
        else:
            self.add_class("narrow")
        if not self.has_class("too-small") and height <= 35:
            self.add_class("short")
        if self.monochrome:
            self.add_class("monochrome")

    def _row_width(self) -> int:
        if self.has_class("wide"):
            return max(28, int(self.size.width * 0.36) - 5)
        if self.has_class("medium"):
            return max(28, int(self.size.width * 0.42) - 5)
        return max(28, self.size.width - 5)

    def refresh_sessions(self) -> None:
        try:
            sessions = self.service.list_sessions()
        except WFError as error:
            self.notify(str(error), title="Refresh failed", severity="error")
            return
        if self.selected_name is not None:
            current = next((item for item in sessions if item.name == self.selected_name), None)
            if current is None or current.session_id != self.selected_session_id:
                self.selected_name = None
                self.selected_session_id = None
        self.sessions = sessions
        self._render_options()

    def _matches_query(self, session: SessionView) -> bool:
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

        self.visible_sessions = [item for item in self.sessions if self._matches_query(item)]
        groups: dict[str, list[SessionView]] = {
            "Needs Input": [],
            "Pinned": [],
            "Attached": [],
            "Detached": [],
            "Recent": [],
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
        warnings = sum(is_warning(session) for session in self.sessions)
        filters = f"  filter: {self.filter_query}" if self.filter_query else ""
        session_label = "session" if len(self.sessions) == 1 else "sessions"
        warning_label = "warning" if warnings == 1 else "warnings"
        text = Text()
        text.append("WF", "bold #72c78e")
        text.append(f"  Workflow Session Manager  v{__version__}", "#dce3e7")
        text.append(
            f"    {len(self.sessions)} {session_label}  {attached} attached  "
            f"{warnings} {warning_label}",
            "#aab5bc",
        )
        text.append(f"    {self.hostname}{filters}", "#7f8d96")
        self.query_one("#app-header", Static).update(text)

    def _render_action_bar(self) -> None:
        navigation = "Up/Down" if self.ascii_only else "↑↓"
        if self.has_class("searching"):
            value = "Type to filter   Enter Apply   Esc Cancel"
        elif self.has_class("narrow"):
            value = (
                f"{navigation} Navigate   Enter Open   c Create   / Search   "
                "p Palette   ? Help   q Quit"
            )
        else:
            value = (
                f"{navigation} Navigate   Enter Attach   c Create   / Search   "
                "p Palette   ? Help   q Quit"
            )
        self.query_one("#action-bar", Static).update(value)

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
        filtered = bool(self.filter_query)
        self.query_one("#identity", Static).update("No matches" if filtered else "No sessions")
        self.query_one("#overview", Static).update(
            "No managed sessions match the active filter."
            if filtered
            else "Create a managed session to get started."
        )
        for widget_id in ("#runtime-status", "#activity", "#recent-output", "#session-actions"):
            self.query_one(widget_id, Static).update("")

    def _render_details(self, name: str) -> None:
        scroller = self.query_one("#inspector-scroll", VerticalScroll)
        old_scroll = scroller.scroll_offset.y
        try:
            details = self.service.inspect(name)
        except WFError as error:
            self.query_one("#overview", Static).update(str(error))
            return
        session = details.session
        identity = Text(session.name, style="bold #eef3f6")
        identity.append(f"\n{session.tool.value.upper()}", style=TOOL_STYLES[session.tool])
        identity.append(
            f"    {display_state(session.runtime.value)}", RUNTIME_STYLES[session.runtime]
        )
        self.query_one("#identity", Static).update(identity)
        self.query_one("#overview", Static).update(
            labeled_values(
                [
                    ("Project", session.project),
                    ("Directory", display_path(session.cwd)),
                    ("Task", session.note),
                    ("Ownership", "Managed by WF" if session.owned else "Read only"),
                    ("Windows", str(session.windows)),
                    ("Tags", ", ".join(session.tags)),
                ]
            )
        )
        self.query_one("#runtime-status", Static).update(
            labeled_values(
                [
                    ("Runtime", display_state(session.runtime.value)),
                    ("Task", display_state(session.task_state.value)),
                    ("Input", display_input(session.input_state)),
                    ("Last active", relative_activity(session.last_active_at)),
                ]
            )
        )
        activity = Text()
        if session.input_state is InputState.REQUIRED:
            activity.append("Input required\n", "bold #e9b44c")
            activity.append("This status was explicitly set for the session.", "#cbd3d8")
        elif session.runtime is RuntimeState.FAILED:
            activity.append("The active pane exited with a failure status.", "bold #ef6b73")
        else:
            activity.append(f"Task is {display_state(session.task_state.value).lower()}.")
        self.query_one("#activity", Static).update(activity)
        preview = Text()
        if details.preview_truncated:
            preview.append("[older output truncated]\n", "#8fa1ac")
        preview.append(details.preview or "No pane output", "#cbd3d8")
        self.query_one("#recent-output", Static).update(preview)
        self.query_one("#session-actions", Static).update(
            "Enter Attach   e Edit   n Task   l Logs   r Refresh   * Pin   d More"
        )
        self.call_after_refresh(scroller.scroll_to, y=old_scroll, animate=False, force=True)

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

    def action_more_actions(self) -> None:
        session = self._selected()
        if session:
            self.push_screen(MoreActionsScreen(session.name), self._more_action)

    def action_delete_session(self) -> None:
        self.action_more_actions()

    def _more_action(self, action: str | None) -> None:
        session = self._selected()
        if action == "delete" and session is not None:
            self.push_screen(DeleteSessionScreen(session.name), self._delete_session)

    def _delete_session(self, confirmed: bool | None) -> None:
        session = self._selected()
        if not confirmed or session is None:
            return
        try:
            self.service.delete(session.name)
        except WFError as error:
            self.notify(str(error), title="Delete failed", severity="error")
            return
        self.selected_name = None
        self.selected_session_id = None
        self.notify(f"Deleted {session.name}")
        self.refresh_sessions()

    def action_diagnostics(self) -> None:
        report = self.service.doctor()
        content = Text()
        for check in report.checks:
            style = "#72c78e" if check.status.value == "pass" else "#e9b44c"
            if check.status.value == "fail":
                style = "#ef6b73"
            content.append(f"{check.status.value.upper():<6}", style)
            content.append(f"{check.name}\n", "bold #e8edf0")
            content.append(f"      {check.detail}\n", "#9aa6ad")
        self.push_screen(MessageScreen("Diagnostics", content))

    def action_help(self) -> None:
        self.push_screen(
            MessageScreen(
                "Keyboard help",
                "Up/Down  Navigate\n"
                "Enter    Attach or open details\n"
                "c        Create session\n"
                "/        Search\n"
                "e        Edit selected session\n"
                "n        Edit task\n"
                "l        View logs\n"
                "*        Toggle pin\n"
                "d        More actions\n"
                "r        Refresh\n"
                "p        Command palette\n"
                "q        Quit",
            )
        )

    def action_refresh(self) -> None:
        self.refresh_sessions()
