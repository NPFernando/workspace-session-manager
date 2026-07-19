"""Textual session-first interface."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Select, Static

from wf_session_manager.errors import WFError
from wf_session_manager.models import CreateRequest, SessionState, SessionView, Tool
from wf_session_manager.service import SessionService

CLASSIC_RESULT = "__wf_classic__"
BindingSpec = Binding | tuple[str, str] | tuple[str, str, str]


def display_path(path: Path) -> str:
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


class CreateSessionScreen(ModalScreen[CreateRequest | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, default_cwd: Path) -> None:
        super().__init__()
        self.default_cwd = default_cwd

    def compose(self) -> ComposeResult:
        with Vertical(id="create-dialog", classes="dialog"):
            yield Label("New session", classes="dialog-title")
            yield Label("Tool", classes="field-label")
            yield Select(
                [(tool.value.title(), tool.value) for tool in Tool],
                value=Tool.CLAUDE.value,
                allow_blank=False,
                id="create-tool",
            )
            yield Label("Session name", classes="field-label")
            yield Input(placeholder="api-refactor", id="create-name")
            yield Label("Working directory", classes="field-label")
            yield Input(value=str(self.default_cwd), id="create-cwd")
            yield Label("Note", classes="field-label")
            yield Input(placeholder="What this session is working on", id="create-note")
            yield Label("Tags", classes="field-label")
            yield Input(placeholder="backend urgent", id="create-tags")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="create")

    def on_mount(self) -> None:
        self.query_one("#create-name", Input).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id != "create":
            return
        try:
            tool_value = str(self.query_one("#create-tool", Select).value)
            request = CreateRequest(
                name=self.query_one("#create-name", Input).value,
                tool=Tool(tool_value),
                cwd=Path(self.query_one("#create-cwd", Input).value),
                note=self.query_one("#create-note", Input).value,
                tags=self.query_one("#create-tags", Input).value.split(),
            )
        except (ValueError, WFError) as error:
            self.notify(str(error), title="Cannot create session", severity="error")
            return
        self.dismiss(request)

    def action_cancel(self) -> None:
        self.dismiss(None)


class OrganizeSessionScreen(ModalScreen[tuple[str, list[str], SessionState, bool] | None]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session: SessionView) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        with Vertical(id="organize-dialog", classes="dialog"):
            yield Label(f"Organize {self.session.name}", classes="dialog-title")
            yield Label("Note", classes="field-label")
            yield Input(value=self.session.note, id="organize-note")
            yield Label("Tags", classes="field-label")
            yield Input(value=" ".join(self.session.tags), id="organize-tags")
            yield Label("State", classes="field-label")
            yield Select(
                [(state.value.title(), state.value) for state in SessionState],
                value=(
                    self.session.state
                    if self.session.state in {state.value for state in SessionState}
                    else SessionState.ACTIVE.value
                ),
                allow_blank=False,
                id="organize-state",
            )
            yield Checkbox("Pinned", value=self.session.pinned, id="organize-pinned")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        self.query_one("#organize-note", Input).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        if event.button.id == "save":
            self.dismiss(
                (
                    self.query_one("#organize-note", Input).value,
                    self.query_one("#organize-tags", Input).value.split(),
                    SessionState(str(self.query_one("#organize-state", Select).value)),
                    self.query_one("#organize-pinned", Checkbox).value,
                )
            )

    def action_cancel(self) -> None:
        self.dismiss(None)


class DeleteSessionScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingSpec]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session_name: str) -> None:
        super().__init__()
        self.session_name = session_name

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-dialog", classes="dialog danger-dialog"):
            yield Label("Delete managed session", classes="dialog-title")
            yield Static(f"Type {self.session_name} to confirm.", classes="confirm-copy")
            yield Input(id="delete-confirm")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Delete", variant="error", id="delete")

    def on_mount(self) -> None:
        self.query_one("#delete-confirm", Input).focus()

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "delete":
            confirmed = self.query_one("#delete-confirm", Input).value == self.session_name
            if not confirmed:
                self.notify("Session name does not match", severity="error")
                return
            self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class WFApp(App[str | None]):
    """Operational session dashboard; it returns the selected attach target."""

    CSS_PATH = "wf.tcss"
    TITLE = "WF - Workflow Session Manager"
    BINDINGS: ClassVar[list[BindingSpec]] = [
        Binding("q", "quit", "Quit"),
        Binding("enter", "attach", "Attach"),
        Binding("n", "new_session", "New"),
        Binding("e", "organize", "Organize"),
        Binding("p", "toggle_pin", "Pin"),
        Binding("d", "delete_session", "Delete"),
        Binding("r", "refresh", "Refresh"),
        Binding("/", "search", "Search"),
        Binding("f", "classic", "Classic"),
    ]

    def __init__(self, service: SessionService) -> None:
        super().__init__()
        self.service = service
        self.sessions: list[SessionView] = []
        self.selected_name: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("WF", id="brand")
        yield Static("Workflow Session Manager", id="subtitle")
        yield Input(placeholder="Search sessions", id="search")
        with Horizontal(id="workspace"):
            with Vertical(id="session-pane"):
                yield DataTable(id="sessions", cursor_type="row", zebra_stripes=True)
                yield Static("", id="status")
            with Vertical(id="detail-pane"):
                yield Static("Session details", id="detail-title")
                yield Static("Select a session", id="details")
                yield Static("", id="preview")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#sessions", DataTable)
        table.add_columns("", "Session", "Tool", "State", "Directory")
        table.focus()
        self._set_layout_classes(self.size.width, self.size.height)
        self.refresh_sessions()
        self.set_interval(self.service.config.refresh_interval, self.refresh_sessions)

    def on_resize(self, event: events.Resize) -> None:
        self._set_layout_classes(event.size.width, event.size.height)

    def _set_layout_classes(self, width: int, height: int) -> None:
        self.set_class(width <= 100, "compact")
        self.set_class(height <= 28, "short")

    def refresh_sessions(self) -> None:
        try:
            self.sessions = self.service.list_sessions()
        except WFError as error:
            self.notify(str(error), title="Refresh failed", severity="error")
            return
        self._render_rows()

    def _render_rows(self) -> None:
        table = self.query_one("#sessions", DataTable)
        search = self.query_one("#search", Input).value.casefold().strip()
        current = self.selected_name
        table.clear(columns=False)
        visible = [
            session
            for session in self.sessions
            if not search
            or search
            in " ".join(
                (session.name, session.tool.value, session.state, session.note, *session.tags)
            ).casefold()
        ]
        for session in visible:
            marker = "*" if session.pinned else " "
            state = "attached" if session.attached else session.state
            ownership = session.tool.value if session.owned else f"{session.tool.value} (classic)"
            table.add_row(
                marker,
                session.name,
                ownership,
                state,
                display_path(session.cwd),
                key=session.name,
            )
        managed = sum(session.owned for session in self.sessions)
        read_only = len(self.sessions) - managed
        self.query_one("#status", Static).update(
            f"{len(visible)} shown  |  {managed} managed  |  {read_only} read-only"
        )
        if current and any(session.name == current for session in visible):
            with suppress(StopIteration):
                table.move_cursor(
                    row=next(index for index, item in enumerate(visible) if item.name == current)
                )

    @on(Input.Changed, "#search")
    def search_changed(self) -> None:
        self._render_rows()

    @on(DataTable.RowHighlighted, "#sessions")
    def row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        self.selected_name = str(event.row_key.value)
        self._render_details(self.selected_name)

    def _selected(self) -> SessionView | None:
        if self.selected_name is None:
            return None
        return next((item for item in self.sessions if item.name == self.selected_name), None)

    def _render_details(self, name: str) -> None:
        try:
            details = self.service.inspect(name)
        except WFError as error:
            self.query_one("#details", Static).update(str(error))
            return
        session = details.session
        text = Text()
        values = (
            ("Status", "attached" if session.attached else "detached"),
            ("Tool", session.tool.value),
            ("Ownership", "managed by WF" if session.owned else "classic / read-only"),
            ("Task state", session.state),
            ("Directory", display_path(session.cwd)),
            ("Windows", str(session.windows)),
            ("Note", session.note or "-"),
            ("Tags", ", ".join(session.tags) or "-"),
        )
        for label, value in values:
            text.append(f"{label}: ", style="bold #a7c7e7")
            text.append(value)
            text.append("\n")
        self.query_one("#detail-title", Static).update(session.name)
        self.query_one("#details", Static).update(text)
        self.query_one("#preview", Static).update(Text(details.preview or "No pane output"))

    def action_attach(self) -> None:
        session = self._selected()
        if session:
            self.exit(session.name)

    def action_new_session(self) -> None:
        self.push_screen(CreateSessionScreen(Path.cwd()), self._create_session)

    def _create_session(self, request: CreateRequest | None) -> None:
        if request is None:
            return
        try:
            session = self.service.create(request)
        except WFError as error:
            self.notify(str(error), title="Create failed", severity="error")
            return
        self.selected_name = session.name
        self.notify(f"Created {session.name}", title="Session ready")
        self.refresh_sessions()

    def action_organize(self) -> None:
        session = self._selected()
        if session is None:
            return
        if not session.owned:
            self.notify(
                "Classic sessions are read-only until migration is approved", severity="warning"
            )
            return
        self.push_screen(OrganizeSessionScreen(session), self._organize_session)

    def _organize_session(self, result: tuple[str, list[str], SessionState, bool] | None) -> None:
        session = self._selected()
        if result is None or session is None:
            return
        note, tags, state, pinned = result
        try:
            self.service.update_note(session.name, note)
            self.service.organize(session.name, tags=tags, state=state, pinned=pinned)
        except WFError as error:
            self.notify(str(error), title="Save failed", severity="error")
            return
        self.refresh_sessions()

    def action_toggle_pin(self) -> None:
        session = self._selected()
        if session is None:
            return
        try:
            self.service.organize(session.name, pinned=not session.pinned)
        except WFError as error:
            self.notify(str(error), severity="warning")
            return
        self.refresh_sessions()

    def action_delete_session(self) -> None:
        session = self._selected()
        if session is None:
            return
        if not session.owned:
            self.notify("WF will not delete a classic session", severity="warning")
            return
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
        self.notify(f"Deleted {session.name}")
        self.refresh_sessions()

    def action_refresh(self) -> None:
        self.refresh_sessions()

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_classic(self) -> None:
        self.exit(CLASSIC_RESULT)
