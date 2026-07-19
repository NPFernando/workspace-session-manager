import pytest
from textual.widgets import DataTable, Input

from conftest import FakeBackend
from wf_session_manager.service import SessionService
from wf_session_manager.tui import CreateSessionScreen, WFApp


@pytest.mark.asyncio
async def test_tui_loads_and_filters_sessions(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    fake_backend.add("claude-first")
    fake_backend.add("codex-second")
    app = WFApp(service)
    async with app.run_test(size=(120, 36)) as pilot:
        table = app.query_one("#sessions", DataTable)
        assert table.row_count == 2
        search = app.query_one("#search", Input)
        search.value = "codex"
        await pilot.pause()
        assert table.row_count == 1


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
