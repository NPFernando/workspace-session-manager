from pathlib import Path

import pytest
from textual.widgets import DataTable, Input, Static

from conftest import FakeBackend
from wf_session_manager.models import CreateRequest, Tool
from wf_session_manager.service import SessionService
from wf_session_manager.tui import CreateSessionScreen, WFApp


def create_managed(service: SessionService, name: str, tool: Tool) -> None:
    service.create(CreateRequest(name=name, tool=tool, cwd=Path("/tmp")))


@pytest.mark.asyncio
async def test_tui_loads_and_filters_sessions(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    create_managed(service, "second", Tool.CODEX)
    app = WFApp(service)
    async with app.run_test(size=(120, 36)) as pilot:
        table = app.query_one("#sessions", DataTable)
        assert table.row_count == 2
        search = app.query_one("#search", Input)
        search.value = "codex"
        await pilot.pause()
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_tui_enter_attaches_highlighted_table_row(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")

    assert app.return_value == "claude-first"


@pytest.mark.asyncio
async def test_tui_enter_attaches_filtered_search_result(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    create_managed(service, "second", Tool.CODEX)
    app = WFApp(service)
    async with app.run_test() as pilot:
        search = app.query_one("#search", Input)
        search.value = "codex"
        search.focus()
        await pilot.pause()
        await pilot.press("enter")

    assert app.return_value == "codex-second"


@pytest.mark.asyncio
async def test_tui_zero_search_results_clear_hidden_selection(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service)
    async with app.run_test() as pilot:
        search = app.query_one("#search", Input)
        search.value = "no-match"
        search.focus()
        await pilot.pause()

        assert app.query_one("#sessions", DataTable).row_count == 0
        assert app.selected_name is None
        assert str(app.query_one("#detail-title", Static).content) == "No matches"
        await pilot.press("enter")
        await pilot.pause()
        assert app.return_value is None


@pytest.mark.asyncio
async def test_tui_empty_inventory_has_no_actionable_selection(
    service: SessionService,
) -> None:
    app = WFApp(service)
    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.selected_name is None
        assert app.query_one("#sessions", DataTable).row_count == 0
        assert str(app.query_one("#detail-title", Static).content) == "No sessions"
        app.action_delete_session()
        assert app.screen is app.screen_stack[0]


@pytest.mark.asyncio
async def test_tui_refresh_clears_removed_selection(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.selected_name == "claude-first"

        service.delete("claude-first")
        app.refresh_sessions()
        await pilot.pause()

        assert app.selected_name is None
        assert app.query_one("#sessions", DataTable).row_count == 0
        assert str(app.query_one("#detail-title", Static).content) == "No sessions"


@pytest.mark.asyncio
async def test_tui_create_dialog_is_keyboard_accessible(service: SessionService) -> None:
    app = WFApp(service)
    async with app.run_test(size=(100, 30)) as pilot:
        base_screen = app.screen
        await pilot.press("n")
        assert isinstance(app.screen, CreateSessionScreen)
        await pilot.press("escape")
        assert app.screen is base_screen


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("size", "compact"),
    [((80, 24), True), ((120, 36), False)],
)
async def test_tui_layout_adapts_without_pane_overlap(
    service: SessionService,
    size: tuple[int, int],
    compact: bool,
) -> None:
    app = WFApp(service)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert app.has_class("compact") is compact
        session_pane = app.query_one("#session-pane").region
        detail_pane = app.query_one("#detail-pane").region
        assert not session_pane.overlaps(detail_pane)
