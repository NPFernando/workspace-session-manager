from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from workspace_session_manager.models import (
    AgentState,
    InputState,
    RuntimeState,
    SessionView,
    TaskState,
    Tool,
)
from workspace_session_manager.tui_session_details import build_detail_rows


def test_detail_rows_group_overview_and_status_fields() -> None:
    session = SessionView(
        name="codex-api",
        display_name="API work",
        session_id="$1",
        tool=Tool.CODEX,
        cwd=Path("/srv/api"),
        current_command="codex",
        runtime=RuntimeState.DETACHED,
        attached=False,
        attached_clients=0,
        windows=2,
        created_at=datetime.now(UTC),
        project="api",
        note="codex task: review_api",
        tags=["review"],
        task_state=TaskState.IN_PROGRESS,
        input_state=InputState.REQUIRED,
        owned=True,
        logging_enabled=True,
    )
    notice = SimpleNamespace(agent_state=AgentState.ACTIVE)

    rows = build_detail_rows(
        session,
        notice,
        display_name="Codex · api",
        tool_label="Codex",
        directory_label="/srv/api",
        last_active_label="5m",
        medium=False,
    )

    assert ("Task", "Work on review api") in rows.overview
    assert ("Owner", "Managed by ws") in rows.overview
    assert ("Input", "Required") in rows.status
    assert ("Logging", "Enabled") in rows.status


def test_detail_rows_reduce_secondary_fields_at_medium_width() -> None:
    session = SessionView(
        name="shell-one",
        session_id="$2",
        tool=Tool.SHELL,
        cwd=Path("/tmp"),
        current_command="bash",
        runtime=RuntimeState.ATTACHED,
        attached=True,
        attached_clients=1,
        windows=1,
        created_at=datetime.now(UTC),
    )
    notice = SimpleNamespace(agent_state=AgentState.ACTIVE)

    rows = build_detail_rows(
        session,
        notice,
        display_name="Shell · one",
        tool_label="Shell",
        directory_label="/tmp",
        last_active_label="now",
        medium=True,
    )

    assert rows.overview == (("Display name", "Shell · one"),)
    assert len(rows.status) == 4
