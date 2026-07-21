from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from textual.command import CommandPalette
from textual.containers import VerticalScroll
from textual.pilot import Pilot
from textual.widgets import Button, Input, OptionList, Select, Static, Switch, TextArea

from conftest import FakeBackend
from wf_session_manager.errors import TmuxError
from wf_session_manager.models import (
    AgentState,
    CreateRequest,
    InputState,
    OutputSource,
    RuntimeState,
    SessionDetails,
    SessionView,
    TaskState,
    Tool,
)
from wf_session_manager.service import SessionService
from wf_session_manager.tui import (
    ConfirmActionScreen,
    CreateFailureScreen,
    CreateSessionScreen,
    DeleteSessionScreen,
    DiagnosticsScreen,
    FilterScreen,
    FilterState,
    IdentityOrganizationScreen,
    InteractionMode,
    LogScreen,
    ManageSessionScreen,
    MoreActionsScreen,
    NoteScreen,
    OnboardingScreen,
    StatusScreen,
    WFApp,
    detect_activity,
    display_path,
    humanize_task,
    relative_activity,
    session_group,
)


def create_managed(service: SessionService, name: str, tool: Tool) -> str:
    return service.create(CreateRequest(name=name, tool=tool, cwd=Path("/tmp"))).name


async def wait_for_create_validation(pilot: Pilot[object], screen: CreateSessionScreen) -> None:
    for _ in range(40):
        if screen._validated_signature == screen._signature():
            return
        await pilot.pause(0.05)
    raise AssertionError("create-session validation did not complete")


async def wait_for_confirmation(pilot: Pilot[object], app: WFApp) -> ConfirmActionScreen:
    for _ in range(40):
        if isinstance(app.screen, ConfirmActionScreen):
            return app.screen
        await pilot.pause(0.05)
    raise AssertionError("confirmation screen did not open")


async def wait_for_manage(pilot: Pilot[object], app: WFApp) -> ManageSessionScreen:
    for _ in range(40):
        if isinstance(app.screen, ManageSessionScreen):
            return app.screen
        await pilot.pause(0.05)
    raise AssertionError("manage screen did not open")


async def wait_for_identity_validation(
    pilot: Pilot[object], screen: IdentityOrganizationScreen
) -> None:
    for _ in range(40):
        status = screen.query_one("#identity-name-status", Static)
        if not status.has_class("checking"):
            return
        await pilot.pause(0.05)
    raise AssertionError("identity validation did not complete")


async def wait_for_log_refresh(pilot: Pilot[object], screen: LogScreen) -> None:
    for _ in range(80):
        if not screen.refreshing and screen.captured_at is not None:
            return
        await pilot.pause(0.05)
    raise AssertionError("log refresh did not complete")


async def wait_for_attention_scan(pilot: Pilot[object], app: WFApp) -> None:
    for _ in range(120):
        if not app._attention_scanning:
            return
        await pilot.pause(0.05)
    raise AssertionError("attention scan did not complete")


@pytest.mark.asyncio
async def test_tui_loads_grouped_rows_and_searches_on_demand(
    service: SessionService,
) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    create_managed(service, "second", Tool.CODEX)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 36)) as pilot:
        assert len(app.visible_sessions) == 2
        assert not app.has_class("searching")
        assert app.query_one("#search-mode").display is False

        await pilot.press("/")
        await pilot.press("c", "o", "d", "e", "x")
        await pilot.pause()
        assert app.has_class("searching")
        assert [item.tool for item in app.visible_sessions] == [Tool.CODEX]

        await pilot.press("escape")
        await pilot.pause()
        assert not app.has_class("searching")
        assert app.filter_query == ""
        assert len(app.visible_sessions) == 2


@pytest.mark.asyncio
async def test_search_enter_commits_filter_without_attaching(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    create_managed(service, "second", Tool.CODEX)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("/")
        await pilot.press("c", "o", "d", "e", "x", "enter")
        await pilot.pause()
        assert app.filter_query == "codex"
        assert not app.has_class("searching")
        assert app.return_value is None
        assert app.selected_name == "codex-second"


@pytest.mark.asyncio
async def test_wide_enter_attaches_selected_session(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
    assert app.return_value == "claude-first"


@pytest.mark.asyncio
async def test_narrow_enter_opens_in_place_detail_then_attaches(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert app.narrow_detail_open
        assert app.has_class("narrow-detail")
        assert app.query_one("#detail-pane").display
        assert not app.query_one("#session-pane").display
        assert "Enter Attach" in str(app.query_one("#action-bar", Static).content)
        await pilot.press("enter")
    assert app.return_value == "claude-first"


@pytest.mark.asyncio
async def test_narrow_detail_restores_viewports_after_forms_logs_and_back(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "narrow-workspace", Tool.CLAUDE)
    service.update_note(name, "\n".join(f"Task detail {index}" for index in range(24)))
    fake_backend.previews[name] = "\n".join(f"output line {index}" for index in range(40))
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("enter")
        assert app.narrow_detail_open
        app.output_mode = "raw"
        app._render_details(name)
        await pilot.pause()
        inspector = app.query_one("#inspector-scroll", VerticalScroll)
        output = app.query_one("#recent-output-scroll", VerticalScroll)
        await pilot.press("j")
        await pilot.pause()
        assert inspector.scroll_offset.y > 0
        inspector.scroll_to(y=5, animate=False, force=True)
        output.scroll_to(y=7, animate=False, force=True)
        await pilot.pause()
        expected_inspector_y = inspector.scroll_offset.y
        expected_output_y = output.scroll_offset.y
        assert expected_inspector_y > 0
        assert expected_output_y > 0

        app.refresh_sessions()
        await pilot.pause()
        assert app.narrow_detail_open
        assert app.output_mode == "raw"
        assert inspector.scroll_offset.y == expected_inspector_y
        assert output.scroll_offset.y == expected_output_y

        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, IdentityOrganizationScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.narrow_detail_open
        assert inspector.scroll_offset.y == expected_inspector_y
        assert output.scroll_offset.y == expected_output_y

        await pilot.press("l")
        assert isinstance(app.screen, LogScreen)
        await wait_for_log_refresh(pilot, app.screen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.narrow_detail_open
        assert inspector.scroll_offset.y == expected_inspector_y
        assert output.scroll_offset.y == expected_output_y

        await pilot.press("question_mark")
        await pilot.pause()
        assert "Scroll details" in str(app.screen.query_one("#message-content", Static).content)
        await pilot.press("escape")
        await pilot.pause()
        assert app.narrow_detail_open

        await pilot.press("escape")
        assert not app.narrow_detail_open
        assert app.query_one("#session-pane").display
        await pilot.press("enter")
        await pilot.pause()
        assert app.narrow_detail_open
        assert app.output_mode == "raw"
        assert inspector.scroll_offset.y == expected_inspector_y
        assert output.scroll_offset.y == expected_output_y


@pytest.mark.asyncio
async def test_narrow_detail_search_and_filter_return_to_list(service: SessionService) -> None:
    create_managed(service, "narrow-modes", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("enter", "/")
        assert not app.narrow_detail_open
        assert app.interaction_mode is InteractionMode.SEARCH
        assert app.has_class("searching")
        await pilot.press("escape", "enter", "f")
        await pilot.pause()
        assert isinstance(app.screen, FilterScreen)
        assert not app.narrow_detail_open
        await pilot.press("escape")
        await pilot.pause()
        assert app.interaction_mode is InteractionMode.NORMAL
        assert not app.narrow_detail_open
        assert app.query_one("#session-pane").display


@pytest.mark.asyncio
async def test_narrow_stopped_detail_opens_manage_and_restores_detail(
    service: SessionService,
) -> None:
    name = create_managed(service, "stopped-narrow", Tool.SHELL)
    service.stop_session(name)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("enter")
        assert app.narrow_detail_open
        assert "Enter Manage" in str(app.query_one("#action-bar", Static).content)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ManageSessionScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert app.narrow_detail_open


@pytest.mark.asyncio
async def test_narrow_detail_closes_on_identity_loss_and_wide_resize(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "resize-detail", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("enter")
        assert app.narrow_detail_open
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert not app.narrow_detail_open
        assert app.query_one("#session-pane").display
        assert app.query_one("#detail-pane").display
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert not app.narrow_detail_open
        assert app.query_one("#session-pane").display
        assert not app.query_one("#detail-pane").display

        await pilot.press("enter")
        assert app.narrow_detail_open
        fake_backend.sessions[name] = fake_backend.sessions[name].model_copy(
            update={"session_id": "$replacement"}
        )
        app.refresh_sessions()
        await pilot.pause()
        assert not app.narrow_detail_open
        assert app.query_one("#session-pane").display


@pytest.mark.asyncio
async def test_logs_follow_pause_manual_refresh_and_restore_dashboard_timer(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "live-logs", Tool.SHELL)
    fake_backend.previews[name] = "first line\nsecond line"
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        dashboard_timer = app._dashboard_refresh_timer
        assert dashboard_timer is not None and dashboard_timer._active.is_set()

        await pilot.press("l")
        assert isinstance(app.screen, LogScreen)
        screen = app.screen
        await wait_for_log_refresh(pilot, screen)
        assert screen.output_source is OutputSource.PANE
        assert screen.follow_output
        assert "second line" in screen.query_one("#log-output", TextArea).text
        assert not dashboard_timer._active.is_set()

        await pilot.press("f")
        assert not screen.follow_output
        fake_backend.previews[name] = "updated while paused"
        screen._poll_if_following()
        await pilot.pause()
        assert "second line" in screen.rendered_output

        await pilot.press("r")
        await wait_for_log_refresh(pilot, screen)
        assert screen.rendered_output == "updated while paused"
        assert not screen.follow_output

        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is app.screen_stack[0]
        assert dashboard_timer._active.is_set()
        assert app.interaction_mode is InteractionMode.NORMAL


@pytest.mark.asyncio
async def test_logs_switch_between_live_and_saved_sources(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    created = service.create(
        CreateRequest(
            name="source-switch",
            tool=Tool.SHELL,
            cwd=Path("/tmp"),
            logging_enabled=True,
        )
    )
    record = service.store.load(created.name)
    assert record is not None
    path = service.paths.logs_dir / f"{record.record_id}.log"
    path.write_text("saved history\n", encoding="utf-8")
    fake_backend.previews[created.name] = "live output"
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("l")
        assert isinstance(app.screen, LogScreen)
        screen = app.screen
        await wait_for_log_refresh(pilot, screen)
        assert screen.output_source is OutputSource.PANE
        assert screen.rendered_output == "live output"
        assert not screen.query_one("#log-source-saved", Button).disabled

        await pilot.click("#log-source-saved")
        await wait_for_log_refresh(pilot, screen)
        assert screen.output_source is OutputSource.SAVED
        assert screen.rendered_output == "saved history"
        assert screen.query_one("#log-source-saved", Button).has_class("active")


@pytest.mark.asyncio
async def test_logs_find_navigation_pauses_follow_and_copy_uses_selection(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = create_managed(service, "find-logs", Tool.SHELL)
    fake_backend.previews[name] = "alpha one\nbeta\nalpha two"
    copied: list[str] = []
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("l")
        assert isinstance(app.screen, LogScreen)
        screen = app.screen
        await wait_for_log_refresh(pilot, screen)

        await pilot.press("/", *"alpha")
        await pilot.pause()
        assert screen.finding
        assert not screen.follow_output
        assert len(screen.matches) == 2
        assert screen.match_index == 0
        assert screen.query_one("#log-output", TextArea).selected_text == "alpha"

        search = screen.query_one("#log-find-input", Input)
        search.value = "missing"
        await pilot.pause()
        assert screen.matches == []
        assert "No matches" in str(screen.query_one("#log-find-count", Static).content)
        await pilot.press("ctrl+u")
        assert search.value == ""
        assert "Type to find" in str(screen.query_one("#log-find-count", Static).content)
        search.value = "alpha"
        await pilot.pause()

        await pilot.press("enter")
        assert screen.match_index == 1
        await pilot.press("shift+enter")
        assert screen.match_index == 0
        await pilot.press("escape")
        assert not screen.finding
        assert not screen.follow_output

        await pilot.press("c")
        assert copied == ["alpha"]
        screen.query_one("#log-output", TextArea).move_cursor((0, 0))
        await pilot.press("c")
        assert copied[-1] == screen.rendered_output


@pytest.mark.asyncio
async def test_logs_surface_warning_refresh_error_and_identity_guard(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "warning-logs", Tool.CODEX)
    fake_backend.previews[name] = (
        "Warning: Codex usage limit reached\nRetry available: tomorrow at 10:00"
    )
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("l")
        assert isinstance(app.screen, LogScreen)
        screen = app.screen
        await wait_for_log_refresh(pilot, screen)
        assert screen.has_class("has-log-alert")
        assert "usage limit reached" in str(screen.query_one("#log-alert", Static).content)

        fake_backend.sessions[name] = fake_backend.sessions[name].model_copy(
            update={"session_id": "$replacement"}
        )
        await pilot.press("r")
        for _ in range(80):
            if screen.error_message:
                break
            await pilot.pause(0.05)
        assert screen.error_message
        assert not screen.follow_output
        assert screen.has_class("has-log-error")

        screen.action_attach()
        assert app.return_value is None


@pytest.mark.asyncio
async def test_logs_retry_time_refresh_guards_and_stale_result(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = create_managed(service, "retry-logs", Tool.SHELL)
    fake_backend.previews[name] = "Recovered output"
    original_logs = service.logs
    should_fail = True

    def flaky_logs(session_name: str, *, source: OutputSource | None = None) -> SessionDetails:
        if should_fail:
            raise TmuxError("tmux socket unavailable")
        return original_logs(session_name, source=source)

    monkeypatch.setattr(service, "logs", flaky_logs)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("l")
        assert isinstance(app.screen, LogScreen)
        screen = app.screen
        for _ in range(80):
            if screen.error_message:
                break
            await pilot.pause(0.05)
        assert screen.error_message == "tmux socket unavailable"
        assert not screen.refreshing
        assert "Output unavailable" in screen.query_one("#log-output", TextArea).placeholder
        assert "Attach unavailable" in str(screen.query_one("#log-action-bar", Static).content)

        should_fail = False
        await pilot.press("r")
        await wait_for_log_refresh(pilot, screen)
        assert screen.rendered_output == "Recovered output"
        assert screen.error_message == ""

        await pilot.press("t")
        assert "Captured" in str(screen.query_one("#log-status", Static).content)

        details = original_logs(name, source=OutputSource.PANE)
        screen.rendered_output = "Keep newer output"
        screen._finish_refresh(screen._refresh_generation - 1, details, "")
        assert screen.rendered_output == "Keep newer output"

        screen.refreshing = True
        generation = screen._refresh_generation
        screen.action_refresh()
        assert screen._refresh_generation == generation
        screen.refreshing = False


@pytest.mark.asyncio
async def test_logs_restore_viewport_for_each_source(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    created = service.create(
        CreateRequest(
            name="viewport-logs",
            tool=Tool.SHELL,
            cwd=Path("/tmp"),
            logging_enabled=True,
        )
    )
    record = service.store.load(created.name)
    assert record is not None
    path = service.paths.logs_dir / f"{record.record_id}.log"
    path.write_text("\n".join(f"saved line {index}" for index in range(20)), encoding="utf-8")
    fake_backend.previews[created.name] = "\n".join(f"live line {index}" for index in range(20))
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.press("l")
        assert isinstance(app.screen, LogScreen)
        screen = app.screen
        await wait_for_log_refresh(pilot, screen)
        await pilot.press("f")
        area = screen.query_one("#log-output", TextArea)
        area.move_cursor((6, 0))
        area.move_cursor((6, 4), select=True)
        live_selection = area.selection

        await pilot.click("#log-source-saved")
        await wait_for_log_refresh(pilot, screen)
        area.move_cursor((3, 0))
        area.move_cursor((3, 5), select=True)
        saved_selection = area.selection

        await pilot.click("#log-source-pane")
        await wait_for_log_refresh(pilot, screen)
        await pilot.pause()
        assert area.selection == live_selection

        await pilot.click("#log-source-saved")
        await wait_for_log_refresh(pilot, screen)
        await pilot.pause()
        assert area.selection == saved_selection


@pytest.mark.asyncio
async def test_logs_resize_and_stopped_session_disable_attach(
    service: SessionService,
) -> None:
    name = create_managed(service, "stopped-view", Tool.SHELL)
    service.stop_session(name)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("l")
        assert isinstance(app.screen, LogScreen)
        screen = app.screen
        await wait_for_log_refresh(pilot, screen)
        assert screen.output_source is OutputSource.SAVED
        assert screen.session.runtime is RuntimeState.STOPPED
        assert screen.query_one("#log-source-pane", Button).disabled
        screen.action_attach()
        assert app.return_value is None

        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert screen.has_class("log-narrow")
        await pilot.resize_terminal(72, 20)
        await pilot.pause()
        assert screen.has_class("log-too-small")
        assert screen.query_one("#log-small-terminal", Static).display


@pytest.mark.asyncio
async def test_zero_search_results_clear_actionable_selection(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("/")
        app.query_one("#search", Input).value = "no-match"
        await pilot.pause()
        assert app.visible_sessions == []
        assert app.selected_name is None
        assert "No matches" in str(app.query_one("#identity", Static).content)


@pytest.mark.asyncio
async def test_empty_inventory_has_quick_actions_but_no_session_action(
    service: SessionService,
) -> None:
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        assert app.selected_name is None
        assert app.visible_sessions == []
        assert app.query_one("#sessions", OptionList).option_count == 10
        app.action_more_actions()
        assert app.screen is app.screen_stack[0]


@pytest.mark.asyncio
async def test_refresh_clears_removed_or_reused_tmux_identity(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(120, 36)) as pilot:
        assert app.selected_name == name
        fake_backend.sessions[name] = fake_backend.sessions[name].model_copy(
            update={"session_id": "$replacement"}
        )
        app.refresh_sessions()
        await pilot.pause()
        assert app.selected_name is None
        assert app.visible_sessions == []


@pytest.mark.asyncio
async def test_create_dialog_is_keyboard_accessible(service: SessionService) -> None:
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(100, 30)) as pilot:
        base_screen = app.screen
        await pilot.press("c")
        assert isinstance(app.screen, CreateSessionScreen)
        await pilot.press("escape")
        assert app.screen is base_screen


@pytest.mark.asyncio
async def test_delete_requires_manage_and_exact_confirmation(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "delete-me", Tool.SHELL)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("d")
        assert isinstance(app.screen, MoreActionsScreen)
        assert app.focused is app.screen.query_one("#manage-actions", OptionList)

        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, DeleteSessionScreen)
        assert app.focused is app.screen.query_one("#delete-cancel", Button)
        await pilot.click("#delete-confirm")
        await pilot.press(*name)
        await pilot.click("#delete-submit")
        await pilot.pause()
        assert not fake_backend.session_exists(name)


@pytest.mark.asyncio
async def test_refresh_preserves_selection_filter_and_list_scroll(
    service: SessionService,
) -> None:
    for index in range(40):
        create_managed(service, f"session-{index:02d}", Tool.SHELL)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(100, 30)) as pilot:
        options = app.query_one("#sessions", OptionList)
        target = app.visible_sessions[20]
        options.highlighted = options.get_option_index(f"session:{target.session_id}")
        app.filter_query = "session"
        options.scroll_to(y=20, animate=False, force=True)
        await pilot.pause()
        assert app.selected_name == target.name
        before_scroll = options.scroll_offset.y
        app.refresh_sessions()
        await pilot.pause()
        assert app.selected_name == target.name
        assert app.filter_query == "session"
        assert options.scroll_offset.y == before_scroll


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("size", "layout"),
    [
        ((160, 45), "wide"),
        ((120, 35), "wide"),
        ((100, 30), "medium"),
        ((80, 24), "narrow"),
        ((79, 24), "too-small"),
        ((80, 23), "too-small"),
    ],
)
async def test_responsive_layout_modes(
    service: SessionService,
    size: tuple[int, int],
    layout: str,
) -> None:
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert app.has_class(layout)
        if layout == "too-small":
            fallback = str(app.query_one("#small-terminal", Static).content)
            assert "Minimum: 80x24" in fallback
            assert "WF list" in fallback
            assert "WF --classic" in fallback


@pytest.mark.asyncio
async def test_ascii_mode_uses_text_separators_and_navigation(
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_managed(service, "ascii", Tool.SHELL)
    monkeypatch.setenv("WF_ASCII", "1")
    app = WFApp(service, monochrome=True, hostname="ascii-host")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = str(app.query_one("#action-bar", Static).content)
        assert "Up/Down/jk Nav" in footer
        options = app.query_one("#sessions", OptionList)
        option = options.get_option(f"session:{app.visible_sessions[0].session_id}")
        assert " · " not in str(option.prompt)


def test_grouping_is_exclusive_and_prioritized(service: SessionService) -> None:
    name = create_managed(service, "grouped", Tool.CLAUDE)
    session = service.get(name)
    now = datetime.now(UTC)
    session = session.model_copy(
        update={
            "runtime": RuntimeState.ATTACHED,
            "pinned": True,
            "input_state": InputState.REQUIRED,
            "last_active_at": now,
        }
    )
    assert session_group(session, now=now) == "Needs Input"
    session = session.model_copy(update={"input_state": InputState.NONE})
    assert session_group(session, now=now) == "Pinned"
    session = session.model_copy(update={"pinned": False})
    assert session_group(session, now=now) == "Attached"
    session = session.model_copy(update={"runtime": RuntimeState.DETACHED})
    assert session_group(session, now=now) == "Detached"
    session = session.model_copy(update={"last_active_at": now - timedelta(days=2)})
    assert session_group(session, now=now) == "Detached"


def test_path_and_activity_display_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/test")))
    assert display_path(Path("/home/test")) == "~"
    assert display_path(Path("/home/test/project")) == "~/project"
    now = datetime(2026, 7, 20, tzinfo=UTC)
    assert relative_activity(now - timedelta(seconds=5), now=now) == "<1m"
    assert relative_activity(now - timedelta(minutes=2), now=now) == "2m"
    assert relative_activity(now - timedelta(hours=3), now=now) == "3h"


def test_raw_legacy_task_is_humanized() -> None:
    assert (
        humanize_task("codex task: https-astrology-fernandofamily-com-en-pancha-pakshi (ubuntu)")
        == "Work on astrology fernandofamily com en pancha pakshi"
    )


def test_usage_limit_detection_is_structured(service: SessionService) -> None:
    name = create_managed(service, "limited", Tool.CODEX)
    session = service.get(name)
    notice = detect_activity(
        session,
        "Warning: Codex usage limit reached\nRetry available: 23 Jul 2026, 10:46 AM",
    )
    assert notice.level == "warning"
    assert notice.title == "Codex usage limit reached"
    assert notice.detail == "Retry available: 23 Jul 2026, 10:46 AM"
    assert notice.agent_state is AgentState.PAUSED


def test_claude_session_limit_wording_is_detected(service: SessionService) -> None:
    name = create_managed(service, "limited", Tool.CLAUDE)
    notice = detect_activity(
        service.get(name),
        "You've hit your session limit\nAvailable again at 10:10 AM",
    )
    assert notice.warning
    assert notice.title == "Claude Code session limit reached"
    assert notice.detail == "Retry available: 10:10 AM"


@pytest.mark.asyncio
async def test_create_form_validates_duplicates_and_directory_inline(
    service: SessionService,
    tmp_path: Path,
) -> None:
    create_managed(service, "existing", Tool.CLAUDE)
    project = tmp_path / "detected-project"
    project.mkdir()
    (project / ".git").mkdir()
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        assert isinstance(app.screen, CreateSessionScreen)
        submit = app.screen.query_one("#create-submit", Button)
        assert submit.disabled

        app.screen.query_one("#create-name", Input).value = "existing"
        app.screen.query_one("#create-cwd", Input).value = str(project)
        await wait_for_create_validation(pilot, app.screen)
        assert submit.disabled
        assert "already exists" in str(app.screen.query_one("#create-name-status", Static).content)

        app.screen.query_one("#create-name", Input).value = "new-work"
        await wait_for_create_validation(pilot, app.screen)
        assert not submit.disabled
        assert app.screen.query_one("#create-project", Input).value == "detected-project"

        app.screen.query_one("#create-cwd", Input).value = str(project / "missing")
        await wait_for_create_validation(pilot, app.screen)
        assert submit.disabled
        assert app.screen.query_one("#create-name", Input).value == "new-work"


@pytest.mark.asyncio
async def test_create_form_uses_latest_normalized_name_value(
    service: SessionService,
    tmp_path: Path,
) -> None:
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        form = app.screen
        form.query_one("#create-name", Input).value = "_"
        form.query_one("#create-name", Input).value = "api-refactor"
        form.query_one("#create-cwd", Input).value = str(tmp_path)
        await wait_for_create_validation(pilot, form)
        status = str(form.query_one("#create-name-status", Static).content)
        assert "Available as claude-api-refactor" in status
        assert not form.query_one("#create-submit", Button).disabled


@pytest.mark.asyncio
async def test_create_suspends_and_restores_search_mode(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    create_managed(service, "second", Tool.CODEX)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("/")
        await pilot.press("c", "o", "d", "e", "x")
        visible_before = [session.name for session in app.visible_sessions]
        app.action_create()
        await pilot.pause()

        assert isinstance(app.screen, CreateSessionScreen)
        assert app.interaction_mode is InteractionMode.FORM
        assert not app.has_class("searching")
        assert app.filter_query == "codex"
        assert app.query_one("#search", Input).value == "codex"
        assert app.query_one("#search-mode").display is False
        assert app.query_one("#action-bar").display is False
        assert app.screen.query_one("#create-form-help").display is True
        assert len(app.screen.query("#create-form-help")) == 1

        await pilot.click("#create-cancel")
        await pilot.pause()
        assert app.interaction_mode is InteractionMode.SEARCH
        assert app.has_class("searching")
        assert app.filter_query == "codex"
        assert [session.name for session in app.visible_sessions] == visible_before
        assert app.focused is app.query_one("#search", Input)
        assert app.query_one("#action-bar").display is True


@pytest.mark.asyncio
async def test_filter_suspends_and_restores_search_mode(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    create_managed(service, "second", Tool.CODEX)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("/", "c", "o", "d", "e", "x")
        visible_before = [session.name for session in app.visible_sessions]
        app.action_filter()
        await pilot.pause()

        assert isinstance(app.screen, FilterScreen)
        assert app.interaction_mode is InteractionMode.FILTER
        assert not app.has_class("searching")
        assert app.query_one("#search-mode").display is False
        assert app.query_one("#action-bar").display is False
        assert len(app.screen.query(".mode-help")) == 1

        await pilot.press("escape")
        await pilot.pause()
        assert app.interaction_mode is InteractionMode.SEARCH
        assert app.has_class("searching")
        assert app.filter_query == "codex"
        assert [session.name for session in app.visible_sessions] == visible_before
        assert app.focused is app.query_one("#search", Input)


@pytest.mark.asyncio
async def test_palette_has_exclusive_mode_and_restores_search(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("/", "f", "i", "r", "s", "t")
        app.action_command_palette()
        await pilot.pause()

        assert isinstance(app.screen, CommandPalette)
        assert app.interaction_mode is InteractionMode.PALETTE
        assert not app.has_class("searching")
        assert app.query_one("#search-mode").display is False
        assert app.query_one("#action-bar").display is False

        await pilot.press("escape")
        await pilot.pause()
        assert app.interaction_mode is InteractionMode.SEARCH
        assert app.has_class("searching")
        assert app.filter_query == "first"
        assert app.focused is app.query_one("#search", Input)


@pytest.mark.asyncio
async def test_palette_restores_dashboard_before_dispatching_command(
    service: SessionService,
) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("p")
        app.screen.query_one(Input).value = "filter sessions"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, FilterScreen)
        assert app.interaction_mode is InteractionMode.FILTER
        assert app._mode_context is not None
        assert app._mode_context.mode is InteractionMode.NORMAL


@pytest.mark.asyncio
async def test_global_shortcuts_do_not_stack_over_filter(service: SessionService) -> None:
    create_managed(service, "protected", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("f")
        screen = app.screen
        stack_depth = len(app.screen_stack)

        await pilot.press("c", "/", "d", "p")
        await pilot.pause()
        assert app.screen is screen
        assert len(app.screen_stack) == stack_depth
        assert app.interaction_mode is InteractionMode.FILTER


@pytest.mark.asyncio
async def test_basic_create_form_fits_without_scrolling(
    service: SessionService,
    tmp_path: Path,
) -> None:
    app = WFApp(service, monochrome=False, onboarding=False, default_cwd=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CreateSessionScreen)
        assert not isinstance(screen.query_one("#create-basic"), VerticalScroll)
        assert screen.query_one("#create-advanced").display is False
        assert screen.query_one(".dialog-actions").region.bottom <= 35


@pytest.mark.asyncio
async def test_advanced_options_preserve_values_and_focus(
    service: SessionService,
) -> None:
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        await pilot.click("#create-advanced-toggle")
        tags = app.screen.query_one("#create-tags", Input)
        tags.value = "backend, urgent"
        tags.focus()
        await pilot.pause()

        app.screen.action_cancel()
        await pilot.pause()
        assert isinstance(app.screen, CreateSessionScreen)
        assert app.screen.query_one("#create-advanced").display is False
        assert tags.value == "backend, urgent"

        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.query_one("#create-advanced").display is True
        assert app.focused is tags
        assert tags.value == "backend, urgent"


@pytest.mark.asyncio
async def test_home_directory_does_not_become_ubuntu_project(
    service: SessionService,
) -> None:
    app = WFApp(service, monochrome=False, onboarding=False, default_cwd=Path.home())
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        app.screen.query_one("#create-name", Input).value = "home-task"
        await wait_for_create_validation(pilot, app.screen)
        assert app.screen.query_one("#create-project", Input).value == ""
        assert "Project not detected" in str(
            app.screen.query_one("#create-project-status", Static).content
        )
        assert app.screen.query_one("#create-home-project", Button).display is True


@pytest.mark.asyncio
async def test_recent_directory_selection_updates_working_directory(
    service: SessionService,
    tmp_path: Path,
) -> None:
    recent = tmp_path / "recent-project"
    recent.mkdir()
    service.create(CreateRequest(name="recent", tool=Tool.SHELL, cwd=recent))
    app = WFApp(service, monochrome=False, onboarding=False, default_cwd=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        app.screen.query_one("#create-recent-dir", Select).value = str(recent)
        await pilot.pause()
        assert app.screen.query_one("#create-cwd", Input).value == display_path(recent)


@pytest.mark.asyncio
async def test_ctrl_enter_requires_current_validation_and_creates_incrementally(
    service: SessionService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = WFApp(service, monochrome=False, onboarding=False, default_cwd=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        base_screen = app.screen
        await pilot.press("c")
        await pilot.press("ctrl+enter")
        assert isinstance(app.screen, CreateSessionScreen)

        app.screen.query_one("#create-name", Input).value = "api_refactor"
        await wait_for_create_validation(pilot, app.screen)
        assert not app.screen.query_one("#create-submit", Button).disabled
        render_calls = 0
        original_render = app._render_options

        def tracked_render() -> None:
            nonlocal render_calls
            render_calls += 1
            original_render()

        monkeypatch.setattr(app, "_render_options", tracked_render)
        await pilot.press("ctrl+enter")
        await pilot.pause()

        assert app.screen is base_screen
        assert render_calls == 0
        assert app.selected_name == "claude-api-refactor"
        assert service.get("claude-api-refactor").display_name == "api_refactor"
        created = service.get("claude-api-refactor")
        option = app.query_one("#sessions", OptionList).get_option(f"session:{created.session_id}")
        assert any("#243d55" in str(span.style) for span in option.prompt.spans)


@pytest.mark.asyncio
async def test_multiline_task_enter_does_not_submit(
    service: SessionService,
) -> None:
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        task = app.screen.query_one("#create-note", TextArea)
        task.focus()
        await pilot.press("a", "enter", "b")
        assert isinstance(app.screen, CreateSessionScreen)
        assert task.text == "a\nb"


@pytest.mark.asyncio
async def test_prefix_can_be_disabled_without_changing_the_backend(
    service: SessionService,
    tmp_path: Path,
) -> None:
    app = WFApp(service, monochrome=False, onboarding=False, default_cwd=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        app.screen.query_one("#create-name", Input).value = "api_refactor"
        app.screen.query_one("#create-prefix", Switch).value = False
        await wait_for_create_validation(pilot, app.screen)
        assert "Available as api-refactor" in str(
            app.screen.query_one("#create-name-status", Static).content
        )


@pytest.mark.asyncio
async def test_failed_startup_is_actionable_and_leaves_no_metadata(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, dict[str, object]]] = []

    def fail_start(*args: object, **kwargs: object) -> None:
        raise TmuxError("isolated startup failed")

    monkeypatch.setattr(fake_backend, "create_session", fail_start)
    app = WFApp(service, monochrome=False, onboarding=False, default_cwd=tmp_path)
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, **kwargs: notifications.append((message, kwargs)),
    )
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("c")
        app.screen.query_one("#create-name", Input).value = "will-fail"
        await wait_for_create_validation(pilot, app.screen)
        await pilot.press("ctrl+enter")
        await pilot.pause()

        assert service.store.load("claude-will-fail") is None
        assert not fake_backend.session_exists("claude-will-fail")
        assert isinstance(app.screen, CreateFailureScreen)
        assert app.interaction_mode is InteractionMode.CONFIRMATION
        assert app.screen.query_one("#create-failure-remove", Button).disabled
        assert app.focused is app.screen.query_one("#create-failure-close", Button)
        assert notifications
        message, options = notifications[-1]
        assert "Retry" in message
        assert options["title"] == "Session startup failed"
        assert options["timeout"] == 0
        await pilot.click("#create-failure-close")
        await pilot.pause()
        assert app.interaction_mode is InteractionMode.NORMAL


@pytest.mark.asyncio
async def test_usage_limit_updates_header_row_activity_and_agent_state(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "limited", Tool.CLAUDE)
    fake_backend.previews[name] = "You've hit your session limit\nAvailable again at 10:10 AM"
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        assert "1 warning" in str(app.query_one("#app-header", Static).content)
        assert "Claude Code session limit reached" in str(
            app.query_one("#activity", Static).content
        )
        assert "Agent         Paused" in str(app.query_one("#runtime-status", Static).content)
        session = app.sessions[0]
        option = app.query_one("#sessions", OptionList).get_option(f"session:{session.session_id}")
        assert "!" in str(option.prompt)
        summary = str(app.query_one("#recent-output", Static).content)
        assert "tmux session remains active" in summary
        assert "You've hit" not in summary
        await pilot.click("#output-raw")
        assert "You've hit" in str(app.query_one("#recent-output", Static).content)


@pytest.mark.asyncio
async def test_attention_scan_finds_unselected_warning_and_restores_temporary_view(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limited = create_managed(service, "a-limited", Tool.CODEX)
    selected = create_managed(service, "z-selected", Tool.CLAUDE)
    service.organize(selected, pinned=True)
    fake_backend.previews[limited] = (
        "Warning: Codex usage limit reached\nRetry available: tomorrow at 10:00"
    )
    fake_backend.previews[selected] = "Ready"
    notifications: list[tuple[str, dict[str, object]]] = []
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, **kwargs: notifications.append((message, kwargs)),
    )

    async with app.run_test(size=(120, 35)) as pilot:
        await wait_for_attention_scan(pilot, app)
        assert app.selected_name == selected
        assert "1 warning" in str(app.query_one("#app-header", Static).content)
        limited_view = next(session for session in app.sessions if session.name == limited)
        prompt = (
            app.query_one("#sessions", OptionList)
            .get_option(f"session:{limited_view.session_id}")
            .prompt
        )
        assert "!" in str(prompt)
        assert notifications == []

        app.filter_query = "z-selected"
        app.filters = FilterState(tool=Tool.CLAUDE)
        app.query_one("#search", Input).value = app.filter_query
        app._render_options()
        await pilot.pause()
        assert [session.name for session in app.visible_sessions] == [selected]

        app.action_attention()
        await pilot.pause()
        assert app.has_class("attention-view")
        assert [session.name for session in app.visible_sessions] == [limited]
        assert "Attention" in str(app.query_one("#app-header", Static).content)
        assert "Esc Back" in str(app.query_one("#action-bar", Static).content)

        await pilot.press("escape")
        await pilot.pause()
        assert not app.has_class("attention-view")
        assert app.filter_query == "z-selected"
        assert app.filters == FilterState(tool=Tool.CLAUDE)
        assert app.selected_name == selected
        assert [session.name for session in app.visible_sessions] == [selected]

        app.action_attention()
        await pilot.press("/")
        assert app._attention_context is None
        assert app.has_class("searching")
        assert app.query_one("#search", Input).value == "z-selected"
        await pilot.press("escape")

        app.action_attention()
        await pilot.press("f")
        await pilot.pause()
        assert app._attention_context is None
        assert isinstance(app.screen, FilterScreen)
        assert app.screen.query_one("#filter-tool", Select).value == Tool.CLAUDE.value
        await pilot.press("escape")
        await pilot.pause()
        assert app.filter_query == "z-selected"
        assert app.filters == FilterState(tool=Tool.CLAUDE)


@pytest.mark.asyncio
async def test_attention_scan_notifies_once_after_baseline_and_clears_resolution(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = create_managed(service, "a-candidate", Tool.CODEX)
    selected = create_managed(service, "z-selected", Tool.CLAUDE)
    service.organize(selected, pinned=True)
    fake_backend.previews[candidate] = "Ready"
    fake_backend.previews[selected] = "Ready"
    notifications: list[tuple[str, dict[str, object]]] = []
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, **kwargs: notifications.append((message, kwargs)),
    )

    async with app.run_test(size=(120, 35)) as pilot:
        await wait_for_attention_scan(pilot, app)
        assert app._attention_baseline_established
        assert notifications == []

        fake_backend.previews[candidate] = "You've hit your session limit"
        app.refresh_sessions()
        await wait_for_attention_scan(pilot, app)
        warning_notifications = [
            item for item in notifications if item[1].get("title") == "New session warning"
        ]
        assert len(warning_notifications) == 1
        assert "a-candidate" in warning_notifications[0][0]

        app.refresh_sessions()
        await wait_for_attention_scan(pilot, app)
        assert (
            len([item for item in notifications if item[1].get("title") == "New session warning"])
            == 1
        )

        fake_backend.previews[candidate] = "Recovered and ready"
        app.refresh_sessions()
        await wait_for_attention_scan(pilot, app)
        assert "No warnings" in str(app.query_one("#app-header", Static).content)
        app.action_attention()
        await pilot.pause()
        assert app.visible_sessions == []
        assert "No sessions need attention" in str(app.query_one("#identity", Static).content)


def test_attention_batch_reserves_priority_and_rotates_detached_sessions(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    service.config = service.config.model_copy(update={"attention_scan_budget": 4})
    attached_names: set[str] = set()
    detached_names: set[str] = set()
    for index in range(4):
        name = create_managed(service, f"attached-{index}", Tool.CLAUDE)
        fake_backend.sessions[name] = fake_backend.sessions[name].model_copy(
            update={"attached_clients": 1}
        )
        attached_names.add(name)
    for index in range(6):
        detached_names.add(create_managed(service, f"detached-{index}", Tool.CODEX))

    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    app.sessions = service.list_sessions()
    now = datetime.now(UTC)
    app._attention_scanned_at = {
        (session.name, session.session_id): now
        for session in app.sessions
        if session.name in attached_names
    }
    seen_detached: set[str] = set()
    for offset in range(3):
        batch = app._attention_batch()
        assert len(batch) == 4
        assert sum(item.session.name in attached_names for item in batch) == 2
        seen_detached.update(
            item.session.name for item in batch if item.session.name in detached_names
        )
        observed = now + timedelta(seconds=offset + 1)
        for item in batch:
            app._attention_scanned_at[(item.session.name, item.session.session_id)] = observed
    assert seen_detached == detached_names


@pytest.mark.asyncio
async def test_attention_scan_error_is_deduplicated_and_recovers(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = create_managed(service, "a-failing", Tool.CODEX)
    selected = create_managed(service, "z-selected", Tool.CLAUDE)
    service.organize(selected, pinned=True)
    fake_backend.previews[selected] = "Ready"
    original = service.inspect_snapshot

    def inspect_with_failure(session: SessionView, **kwargs: object) -> SessionDetails:
        if session.name == failing:
            raise TmuxError("capture unavailable")
        return original(session, **kwargs)

    monkeypatch.setattr(service, "inspect_snapshot", inspect_with_failure)
    notifications: list[tuple[str, dict[str, object]]] = []
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, **kwargs: notifications.append((message, kwargs)),
    )

    async with app.run_test(size=(120, 35)) as pilot:
        await wait_for_attention_scan(pilot, app)
        assert "capture unavailable" in app._attention_scan_error
        assert (
            len(
                [item for item in notifications if item[1].get("title") == "Attention scan delayed"]
            )
            == 1
        )

        app.refresh_sessions()
        await wait_for_attention_scan(pilot, app)
        assert (
            len(
                [item for item in notifications if item[1].get("title") == "Attention scan delayed"]
            )
            == 1
        )

        monkeypatch.setattr(service, "inspect_snapshot", original)
        fake_backend.previews[failing] = "Recovered"
        app.refresh_sessions()
        await wait_for_attention_scan(pilot, app)
        assert app._attention_scan_error == ""
        assert app._attention_complete()


@pytest.mark.asyncio
async def test_attention_scan_discards_removed_exact_identity(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = create_managed(service, "a-stale", Tool.CODEX)
    selected = create_managed(service, "z-selected", Tool.CLAUDE)
    service.organize(selected, pinned=True)
    fake_backend.previews[candidate] = "You've hit your session limit"
    fake_backend.previews[selected] = "Ready"
    started = Event()
    release = Event()
    original = service.inspect_snapshot

    def delayed_inspect(session: SessionView, **kwargs: object) -> SessionDetails:
        if session.name == candidate:
            started.set()
            release.wait(timeout=5)
        return original(session, **kwargs)

    monkeypatch.setattr(service, "inspect_snapshot", delayed_inspect)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)

    async with app.run_test(size=(120, 35)) as pilot:
        for _ in range(80):
            if started.is_set():
                break
            await pilot.pause(0.05)
        assert started.is_set()
        stale_identity = next(
            (session.name, session.session_id)
            for session in app.sessions
            if session.name == candidate
        )
        fake_backend.sessions[candidate] = fake_backend.sessions[candidate].model_copy(
            update={"session_id": "$replacement"}
        )
        app.refresh_sessions()
        release.set()
        await wait_for_attention_scan(pilot, app)
        assert stale_identity not in app._alerts
        assert stale_identity not in app._attention_scanned_at
        assert all(session.name != candidate for session in app.sessions)


@pytest.mark.asyncio
async def test_diagnostics_is_centered_modal_with_safe_default_details(
    service: SessionService,
) -> None:
    create_managed(service, "diagnostics", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        app.action_diagnostics()
        await pilot.pause()
        assert isinstance(app.screen, DiagnosticsScreen)
        assert app.focused is app.screen.query_one("#diagnostics-close", Button)
        summary = str(app.screen.query_one("#diagnostics-summary", Static).content)
        assert "passed" in summary and "failed" in summary and "information" in summary
        content = str(app.screen.query_one("#diagnostics-content", Static).content)
        assert str(service.paths.state_dir) not in content
        await pilot.click("#diagnostics-details")
        await pilot.pause()
        assert "~" in str(
            app.screen.query_one("#diagnostics-content", Static).content
        ) or "tmp" in str(app.screen.query_one("#diagnostics-content", Static).content)
        await pilot.press("escape")
        assert app.screen is app.screen_stack[0]


@pytest.mark.asyncio
async def test_slow_diagnostics_shows_progress_then_duration(
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = service.doctor
    started = Event()
    release = Event()

    def slow_doctor():  # type: ignore[no-untyped-def]
        started.set()
        release.wait(timeout=2)
        return original()

    monkeypatch.setattr(service, "doctor", slow_doctor)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        app.action_diagnostics()
        await pilot.pause(0.28)
        assert started.is_set()
        assert app.screen.running
        assert app.screen.query_one("#diagnostics-loading").display
        release.set()
        await pilot.pause(0.1)
        assert not app.screen.running
        assert "Completed in" in str(app.screen.query_one("#diagnostics-meta", Static).content)


@pytest.mark.asyncio
async def test_manage_requires_cancel_focused_confirmation_for_stop(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "protected", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("d")
        assert isinstance(app.screen, ManageSessionScreen)
        assert isinstance(app.screen, MoreActionsScreen)
        assert app.focused is app.screen.query_one("#manage-actions", OptionList)
        await pilot.press("t")
        await wait_for_confirmation(pilot, app)
        assert app.focused is app.screen.query_one("#confirm-cancel", Button)
        await pilot.press("escape")
        await pilot.pause()
        assert fake_backend.session_exists(name)
        assert isinstance(app.screen, ManageSessionScreen)
        assert app.interaction_mode is InteractionMode.MANAGE
        options = app.screen.query_one("#manage-actions", OptionList)
        assert app.focused is options
        assert options.get_option_at_index(options.highlighted or 0).id == (
            "manage-action:stop-session"
        )


@pytest.mark.asyncio
async def test_manage_confirmation_keeps_original_session_target(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    original_name = create_managed(service, "original", Tool.SHELL)
    other_name = create_managed(service, "other", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        original = next(session for session in app.sessions if session.name == original_name)
        other = next(session for session in app.sessions if session.name == other_name)
        app.selected_name = original.name
        app.selected_session_id = original.session_id
        app.action_manage()
        await pilot.pause()

        app.selected_name = other.name
        app.selected_session_id = other.session_id
        app.screen.action_choose("stop-session")
        await wait_for_confirmation(pilot, app)
        app.screen.query_one("#confirm-submit", Button).press()
        await pilot.pause()

        assert not fake_backend.session_exists(original_name)
        assert fake_backend.session_exists(other_name)


@pytest.mark.asyncio
async def test_manage_fits_all_categories_at_120x35(service: SessionService) -> None:
    create_managed(service, "managed", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("d")
        screen = await wait_for_manage(pilot, app)
        options = screen.query_one("#manage-actions", OptionList)
        option_ids = {
            options.get_option_at_index(index).id for index in range(options.option_count)
        }

        assert options.option_count == 15
        assert options.max_scroll_y == 0
        assert {
            "manage-category:general",
            "manage-category:runtime",
            "manage-category:danger",
            "manage-action:identity",
            "manage-action:restart",
            "manage-action:delete",
        } <= option_ids
        assert options.get_option_at_index(options.highlighted or 0).id == (
            "manage-action:identity"
        )


@pytest.mark.asyncio
async def test_manage_find_is_local_and_cancellable(service: SessionService) -> None:
    create_managed(service, "managed", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("d", "/")
        screen = await wait_for_manage(pilot, app)
        search = screen.query_one("#manage-search", Input)
        assert app.interaction_mode is InteractionMode.MANAGE
        assert screen.has_class("finding")
        assert app.focused is search

        await pilot.press(*"leave tmux")
        options = screen.query_one("#manage-actions", OptionList)
        assert options.option_count == 2
        assert options.get_option_at_index(1).id == "manage-action:remove-metadata"

        await pilot.press("escape")
        assert not screen.has_class("finding")
        assert options.option_count == 15
        assert app.focused is options

        await pilot.press("/", *"identity", "enter")
        assert not screen.has_class("finding")
        assert options.option_count == 2
        assert app.interaction_mode is InteractionMode.MANAGE


@pytest.mark.asyncio
async def test_manage_disabled_actions_explain_stopped_state(service: SessionService) -> None:
    name = create_managed(service, "stopped", Tool.SHELL)
    service.stop_session(name)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("d")
        screen = await wait_for_manage(pilot, app)
        options = screen.query_one("#manage-actions", OptionList)
        stop = options.get_option("manage-action:stop-session")
        logging = options.get_option("manage-action:logging")

        assert stop.disabled
        assert logging.disabled
        assert "Unavailable: stopped" in str(stop.prompt)


@pytest.mark.asyncio
async def test_manage_identity_edit_returns_with_filter_and_new_identity(
    service: SessionService,
) -> None:
    original_name = create_managed(service, "original", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("d", "/", *"identity", "enter", "enter")
        assert isinstance(app.screen, IdentityOrganizationScreen)
        identity = app.screen
        identity.query_one("#identity-display-name", Input).value = "Renamed Workflow"
        identity.query_one("#identity-name", Input).value = "renamed session"
        await wait_for_identity_validation(pilot, identity)
        assert not identity.query_one("#identity-submit", Button).disabled

        await pilot.press("ctrl+enter")
        manage = await wait_for_manage(pilot, app)
        assert service.store.load(original_name) is None
        updated = service.get("renamed-session")
        assert updated.display_name == "Renamed Workflow"
        assert manage.state.query == "identity"
        assert manage.query_one("#manage-actions", OptionList).option_count == 2

        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is app.screen_stack[0]
        assert app.selected_name == "renamed-session"


@pytest.mark.asyncio
async def test_manage_task_status_and_pin_stay_in_workflow(service: SessionService) -> None:
    name = create_managed(service, "workflow", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("d", "n")
        assert isinstance(app.screen, NoteScreen)
        app.screen.query_one("#note-value", TextArea).text = "First line\nSecond line"
        await pilot.press("ctrl+enter")
        await wait_for_manage(pilot, app)
        assert service.get(name).note == "First line\nSecond line"

        await pilot.press("s")
        assert isinstance(app.screen, StatusScreen)
        app.screen.query_one("#status-task-state", Select).value = TaskState.BLOCKED.value
        app.screen.query_one("#status-input-state", Select).value = InputState.REQUIRED.value
        await pilot.press("ctrl+enter")
        await wait_for_manage(pilot, app)
        updated = service.get(name)
        assert updated.task_state is TaskState.BLOCKED
        assert updated.input_state is InputState.REQUIRED

        await pilot.press("*")
        manage = await wait_for_manage(pilot, app)
        assert service.get(name).pinned
        pin = manage.query_one("#manage-actions", OptionList).get_option("manage-action:pin")
        assert "Unpin session" in str(pin.prompt)


@pytest.mark.asyncio
async def test_manage_is_full_screen_at_narrow_width(service: SessionService) -> None:
    create_managed(service, "narrow-manage", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("d")
        screen = await wait_for_manage(pilot, app)
        await pilot.pause()
        assert screen.has_class("narrow-manage")
        assert screen.query_one("#more-dialog").region.size == screen.size


@pytest.mark.asyncio
async def test_filter_dialog_applies_tool_and_warning_filters(service: SessionService) -> None:
    claude = create_managed(service, "decision", Tool.CLAUDE)
    create_managed(service, "other", Tool.CODEX)
    service.organize(claude, input_state=InputState.REQUIRED)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("f")
        assert isinstance(app.screen, FilterScreen)
        app.screen.query_one("#filter-tool", Select).value = Tool.CLAUDE.value
        await pilot.click("#filter-warnings")
        await pilot.click("#filter-apply")
        await pilot.pause()
        assert [session.name for session in app.visible_sessions] == [claude]
        assert "Claude Code" in str(app.query_one("#app-header", Static).content)


@pytest.mark.asyncio
async def test_onboarding_is_safe_and_recorded(service: SessionService) -> None:
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, OnboardingScreen)
        assert app.focused is app.screen.query_one("#onboarding-close", Button)
        await pilot.press("escape")
        await pilot.pause()
        assert service.onboarding_seen()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [50, 200])
async def test_large_inventories_render_once_per_session(
    service: SessionService,
    count: int,
) -> None:
    for index in range(count):
        create_managed(service, f"load-{index:03d}", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(160, 45)) as pilot:
        await pilot.pause()
        assert len(app.visible_sessions) == count
        assert len(app._option_sessions) == count
        assert len(set(app._option_sessions)) == count


@pytest.mark.asyncio
async def test_terminal_resizing_preserves_selection_and_switches_modes(
    service: SessionService,
) -> None:
    create_managed(service, "resize", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(160, 45)) as pilot:
        selected = app.selected_name
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert app.has_class("medium")
        assert app.selected_name == selected
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert app.has_class("narrow")
        assert app.selected_name == selected
        await pilot.resize_terminal(72, 20)
        await pilot.pause()
        assert app.has_class("too-small")


@pytest.mark.asyncio
async def test_light_and_monochrome_theme_cycle(service: SessionService) -> None:
    create_managed(service, "theme", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False)
    async with app.run_test(size=(120, 35)) as pilot:
        app.action_cycle_theme()
        await pilot.pause()
        assert app.has_class("light")
        app.action_cycle_theme()
        await pilot.pause()
        assert app.has_class("monochrome")


@pytest.mark.asyncio
async def test_no_color_starts_in_monochrome_mode(
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    app = WFApp(service, hostname="no-color-host", onboarding=False)
    assert app.monochrome
    assert app.ui_theme == "monochrome"
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        assert app.has_class("monochrome")


def test_motion_can_be_disabled_by_cli_env_and_monochrome(
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WF_MOTION", "off")
    assert WFApp(service, monochrome=False, onboarding=False).motion == "off"
    monkeypatch.delenv("WF_MOTION")
    assert WFApp(service, monochrome=False, onboarding=False, no_animation=True).motion == "off"
    assert WFApp(service, monochrome=True, onboarding=False).motion == "off"


@pytest.mark.asyncio
async def test_modal_cancel_restores_dashboard_focus(service: SessionService) -> None:
    create_managed(service, "focus", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        sessions = app.query_one("#sessions", OptionList)
        assert app.focused is sessions
        await pilot.press("c", "escape")
        await pilot.pause()
        assert app.screen is app.screen_stack[0]
        assert app.focused is sessions


@pytest.mark.asyncio
async def test_failed_refresh_preserves_selection_and_filters(
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_managed(service, "refresh", Tool.SHELL)
    app = WFApp(service, monochrome=False, onboarding=False, no_animation=True)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("/", "r", "e", "f", "enter")
        selected = app.selected_name

        def fail_refresh(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise TmuxError("simulated refresh interruption")

        monkeypatch.setattr(service, "list_sessions", fail_refresh)
        app.refresh_sessions()
        await pilot.pause()
        assert app.selected_name == selected
        assert app.filter_query == "ref"
        assert not app.tmux_connected
        assert "tmux unavailable" in str(app.query_one("#app-header", Static).content)
