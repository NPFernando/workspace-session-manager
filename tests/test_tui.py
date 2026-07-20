from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest
from textual.command import CommandPalette
from textual.containers import VerticalScroll
from textual.widgets import Button, Input, OptionList, Select, Static, Switch, TextArea

from conftest import FakeBackend
from wf_session_manager.errors import TmuxError
from wf_session_manager.models import (
    AgentState,
    CreateRequest,
    InputState,
    RuntimeState,
    Tool,
)
from wf_session_manager.service import SessionService
from wf_session_manager.tui import (
    ConfirmActionScreen,
    CreateFailureScreen,
    CreateSessionScreen,
    DeleteSessionScreen,
    DetailScreen,
    DiagnosticsScreen,
    FilterScreen,
    InteractionMode,
    ManageSessionScreen,
    MoreActionsScreen,
    OnboardingScreen,
    WFApp,
    detect_activity,
    display_path,
    humanize_task,
    relative_activity,
    session_group,
)


def create_managed(service: SessionService, name: str, tool: Tool) -> str:
    return service.create(CreateRequest(name=name, tool=tool, cwd=Path("/tmp"))).name


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
async def test_narrow_enter_opens_detail_then_attaches(service: SessionService) -> None:
    create_managed(service, "first", Tool.CLAUDE)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        await pilot.press("enter")
    assert app.return_value == "claude-first"


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
        assert app.query_one("#sessions", OptionList).option_count == 9
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
async def test_delete_requires_more_menu_and_exact_confirmation(
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = create_managed(service, "delete-me", Tool.SHELL)
    app = WFApp(service, monochrome=False)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press("d")
        assert isinstance(app.screen, MoreActionsScreen)
        assert app.focused is app.screen.query_one("#more-cancel", Button)

        app.screen.query_one("#more-delete", Button).scroll_visible()
        await pilot.pause()
        await pilot.click("#more-delete")
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
        await pilot.pause(0.25)
        assert submit.disabled
        assert "already exists" in str(app.screen.query_one("#create-name-status", Static).content)

        app.screen.query_one("#create-name", Input).value = "new-work"
        await pilot.pause(0.25)
        assert not submit.disabled
        assert app.screen.query_one("#create-project", Input).value == "detected-project"

        app.screen.query_one("#create-cwd", Input).value = str(project / "missing")
        await pilot.pause(0.25)
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
        await pilot.pause(0.25)
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
        await pilot.pause(0.25)
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
        await pilot.pause(0.25)
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
        await pilot.pause(0.25)
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
        await pilot.pause(0.25)
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
        assert "Agent       Paused" in str(app.query_one("#runtime-status", Static).content)
        session = app.sessions[0]
        option = app.query_one("#sessions", OptionList).get_option(f"session:{session.session_id}")
        assert "!" in str(option.prompt)
        summary = str(app.query_one("#recent-output", Static).content)
        assert "tmux session remains active" in summary
        assert "You've hit" not in summary
        await pilot.click("#output-raw")
        assert "You've hit" in str(app.query_one("#recent-output", Static).content)


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
        assert app.focused is app.screen.query_one("#more-cancel", Button)
        app.screen.query_one("#manage-stop", Button).scroll_visible()
        await pilot.pause()
        await pilot.click("#manage-stop")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmActionScreen)
        assert app.focused is app.screen.query_one("#confirm-cancel", Button)
        await pilot.press("escape")
        await pilot.pause()
        assert fake_backend.session_exists(name)
        assert isinstance(app.screen, ManageSessionScreen)
        assert app.interaction_mode is InteractionMode.MANAGE
        assert app.focused is app.screen.query_one("#manage-stop", Button)


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
        app.screen.query_one("#manage-stop", Button).scroll_visible()
        await pilot.pause()
        await pilot.click("#manage-stop")
        await pilot.pause()
        await pilot.click("#confirm-submit")
        await pilot.pause()

        assert not fake_backend.session_exists(original_name)
        assert fake_backend.session_exists(other_name)


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
