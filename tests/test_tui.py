from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from textual.widgets import Button, Input, OptionList, Select, Static

from conftest import FakeBackend
from wf_session_manager.models import (
    CreateRequest,
    InputState,
    RuntimeState,
    Tool,
)
from wf_session_manager.service import SessionService
from wf_session_manager.tui import (
    ConfirmActionScreen,
    CreateSessionScreen,
    DeleteSessionScreen,
    DetailScreen,
    DiagnosticsScreen,
    FilterScreen,
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
        await pilot.pause()
        assert submit.disabled
        assert "already exists" in str(app.screen.query_one("#create-validation", Static).content)

        app.screen.query_one("#create-name", Input).value = "new-work"
        await pilot.pause()
        assert not submit.disabled
        assert app.screen.query_one("#create-project", Input).value == "detected-project"

        app.screen.query_one("#create-cwd", Input).value = str(project / "missing")
        await pilot.pause()
        assert submit.disabled
        assert app.screen.query_one("#create-name", Input).value == "new-work"


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
        assert "passed" in summary and "failed" in summary
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
        await pilot.click("#manage-stop")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmActionScreen)
        assert app.focused is app.screen.query_one("#confirm-cancel", Button)
        await pilot.press("escape")
        assert fake_backend.session_exists(name)


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
