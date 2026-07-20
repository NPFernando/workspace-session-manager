from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Input

from conftest import FakeBackend
from wf_session_manager.models import CreateRequest, InputState, TaskState, Tool
from wf_session_manager.service import SessionService
from wf_session_manager.tui import WFApp

SnapCompare = Callable[..., bool]
FUTURE_ACTIVITY = datetime(2099, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def deterministic_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)


def add_session(
    service: SessionService,
    backend: FakeBackend,
    name: str,
    tool: Tool,
    *,
    note: str = "",
    project: str = "",
    task_state: TaskState = TaskState.IN_PROGRESS,
    input_state: InputState = InputState.NONE,
    pinned: bool = False,
    attached: bool = False,
    failed: bool = False,
) -> str:
    view = service.create(
        CreateRequest(
            name=name,
            tool=tool,
            cwd=Path("/tmp"),
            project=project,
            note=note,
        )
    )
    service.organize(
        view.name,
        state=task_state,
        input_state=input_state,
        pinned=pinned,
    )
    backend.sessions[view.name] = backend.sessions[view.name].model_copy(
        update={
            "attached_clients": 1 if attached else 0,
            "last_activity_at": FUTURE_ACTIVITY,
            "pane_dead": failed,
            "pane_dead_status": 1 if failed else None,
        }
    )
    backend.previews[view.name] = (
        "Loading project context\n"
        "Validated configuration\n"
        "Reviewing implementation details\n"
        "Ready for the next workflow action"
    )
    return view.name


def populated_app(
    service: SessionService,
    backend: FakeBackend,
    *,
    monochrome: bool = False,
) -> WFApp:
    add_session(
        service,
        backend,
        "astrology-pancha-pakshi",
        Tool.CLAUDE,
        note="Build a bilingual astrology platform",
        project="fernandofamily-astrology",
        input_state=InputState.REQUIRED,
        attached=True,
    )
    add_session(
        service,
        backend,
        "astrology-website",
        Tool.CODEX,
        note="Refine responsive birth-chart pages",
        project="astrology-web",
    )
    add_session(
        service,
        backend,
        "graphify",
        Tool.CLAUDE,
        task_state=TaskState.WAITING,
        pinned=True,
    )
    add_session(
        service,
        backend,
        "maintenance-shell",
        Tool.SHELL,
        task_state=TaskState.UNSPECIFIED,
    )
    return WFApp(
        service,
        monochrome=monochrome,
        hostname="wf-test-host",
        onboarding=False,
        default_cwd=Path("/"),
    )


def test_wide_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    assert snap_compare(populated_app(service, fake_backend), terminal_size=(160, 45))


def test_standard_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    assert snap_compare(populated_app(service, fake_backend), terminal_size=(120, 35))


def test_medium_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    assert snap_compare(populated_app(service, fake_backend), terminal_size=(100, 30))


def test_narrow_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    assert snap_compare(populated_app(service, fake_backend), terminal_size=(80, 24))


def test_empty_snapshot(snap_compare: SnapCompare, service: SessionService) -> None:
    assert snap_compare(
        WFApp(service, monochrome=False, hostname="wf-test-host", onboarding=False),
        terminal_size=(120, 35),
    )


def test_warning_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    add_session(
        service,
        fake_backend,
        "decision-required",
        Tool.HERMES,
        note="Choose the deployment target before continuing",
        input_state=InputState.REQUIRED,
    )
    assert snap_compare(
        WFApp(service, monochrome=False, hostname="wf-test-host", onboarding=False),
        terminal_size=(120, 35),
    )


def test_failure_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    add_session(
        service,
        fake_backend,
        "failed-build",
        Tool.CODEX,
        note="Repair the packaging pipeline",
        failed=True,
    )
    assert snap_compare(
        WFApp(service, monochrome=False, hostname="wf-test-host", onboarding=False),
        terminal_size=(120, 35),
    )


def test_monochrome_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    assert snap_compare(
        populated_app(service, fake_backend, monochrome=True),
        terminal_size=(120, 35),
    )


def test_long_content_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = add_session(
        service,
        fake_backend,
        "extremely-long-session-name-for-responsive-terminal-layout-validation",
        Tool.CLAUDE,
        note=(
            "Build and validate a deliberately long workflow description that must wrap cleanly "
            "inside the inspector without hiding status, output, or available actions."
        ),
        project="long-content-and-responsive-layout-validation-project",
        attached=True,
    )
    fake_backend.previews[name] = "\n".join(
        f"Output line {index}: validating bounded rendering and horizontal clipping"
        for index in range(20)
    )
    assert snap_compare(
        WFApp(service, monochrome=False, hostname="wf-test-host", onboarding=False),
        terminal_size=(160, 45),
    )


def test_light_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    app = populated_app(service, fake_backend)
    app.ui_theme = "light"
    assert snap_compare(app, terminal_size=(120, 35))


def test_diagnostics_modal_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    app = populated_app(service, fake_backend)

    async def open_diagnostics(pilot: Pilot) -> None:
        app.action_diagnostics()
        await pilot.pause()

    assert snap_compare(app, terminal_size=(120, 35), run_before=open_diagnostics)


def test_create_form_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    assert snap_compare(
        populated_app(service, fake_backend),
        press=("c", "_"),
        terminal_size=(120, 35),
    )


def test_create_validation_error_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    app = populated_app(service, fake_backend)

    async def enter_invalid_values(pilot: Pilot) -> None:
        await pilot.press("c")
        app.screen.query_one("#create-name", Input).value = "astrology-website"
        app.screen.query_one("#create-cwd", Input).value = "/missing/wf-directory"
        await pilot.pause()

    assert snap_compare(app, terminal_size=(120, 35), run_before=enter_invalid_values)


def test_usage_limit_warning_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    name = add_session(service, fake_backend, "usage-limited", Tool.CODEX)
    fake_backend.previews[name] = (
        "Warning: Codex usage limit reached\nRetry available: 23 Jul 2026, 10:46 AM"
    )
    assert snap_compare(
        WFApp(service, monochrome=False, hostname="wf-test-host", onboarding=False),
        terminal_size=(120, 35),
    )


def test_destructive_confirmation_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
) -> None:
    app = populated_app(service, fake_backend)

    async def open_confirmation(pilot: Pilot) -> None:
        await pilot.press("d")
        await pilot.click("#manage-stop")
        await pilot.pause()

    assert snap_compare(app, terminal_size=(120, 35), run_before=open_confirmation)


@pytest.mark.parametrize("count", [50, 200])
def test_large_inventory_snapshot(
    snap_compare: SnapCompare,
    service: SessionService,
    fake_backend: FakeBackend,
    count: int,
) -> None:
    for index in range(count):
        add_session(service, fake_backend, f"load-{index:03d}", Tool.SHELL)
    assert snap_compare(
        WFApp(service, monochrome=False, hostname="wf-test-host", onboarding=False),
        terminal_size=(160, 45),
    )
