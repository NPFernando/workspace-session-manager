from pathlib import Path

import pytest

from conftest import FakeBackend
from wf_session_manager.errors import OwnershipError, StateError, TmuxError, ToolUnavailableError
from wf_session_manager.models import (
    CreateRequest,
    InputState,
    RuntimeState,
    SessionMetadata,
    TaskState,
    Tool,
)
from wf_session_manager.service import SessionService


def test_foreign_session_is_hidden_but_available_for_diagnostics(
    service: SessionService, fake_backend: FakeBackend
) -> None:
    fake_backend.add("claude-existing")
    assert service.list_sessions() == []
    session = service.get("claude-existing", include_unmanaged=True)
    assert not session.owned
    with pytest.raises(OwnershipError, match="not created"):
        service.delete(session.name)
    assert fake_backend.session_exists(session.name)


def test_managed_lifecycle(
    service: SessionService, fake_backend: FakeBackend, tmp_path: Path
) -> None:
    request = CreateRequest(
        name="API Refactor",
        tool=Tool.CLAUDE,
        cwd=tmp_path,
        note="Initial task",
        tags=["backend"],
    )
    created = service.create(request)
    assert created.name == "claude-api-refactor"
    assert created.owned
    assert fake_backend.created_commands[-1] == (("/bin/bash", "-l"), ("/bin/true",))

    service.update_note(created.name, "Updated task")
    organized = service.organize(
        created.name,
        tags=["backend", "urgent"],
        state=TaskState.WAITING,
        input_state=InputState.REQUIRED,
        project="api-platform",
        pinned=True,
    )
    assert organized.note == "Updated task"
    assert organized.tags == ["backend", "urgent"]
    assert organized.pinned
    assert organized.task_state is TaskState.WAITING
    assert organized.input_state is InputState.REQUIRED
    assert organized.project == "api-platform"

    renamed = service.rename(created.name, "api-v2")
    assert renamed.name == "claude-api-v2"
    service.delete(renamed.name)
    assert not fake_backend.session_exists(renamed.name)


def test_stale_record_does_not_grant_ownership(
    service: SessionService, fake_backend: FakeBackend
) -> None:
    session = fake_backend.add("codex-stale", session_id="$live")
    service.store.save(
        SessionMetadata(
            tmux_session_id="$old",
            name=session.name,
            tool=Tool.CODEX,
            cwd=Path("/tmp"),
        )
    )
    assert not service.get(session.name, include_unmanaged=True).owned
    with pytest.raises(OwnershipError):
        service.update_note(session.name, "should fail")


def test_state_failure_rolls_back_only_new_session(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_save(record: SessionMetadata) -> None:
        raise StateError(f"cannot save {record.name}")

    monkeypatch.setattr(service.store, "save", fail_save)
    with pytest.raises(StateError):
        service.create(CreateRequest(name="rollback", tool=Tool.SHELL, cwd=tmp_path))
    assert not fake_backend.session_exists("rollback")


def test_missing_tool_fails_before_tmux_creation(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
) -> None:
    broken = service.config.model_copy(
        update={
            "tools": {
                **service.config.tools,
                Tool.CLAUDE: service.config.tools[Tool.CLAUDE].model_copy(
                    update={"command": ("/definitely/missing",)}
                ),
            }
        }
    )
    service.config = broken
    with pytest.raises(ToolUnavailableError):
        service.create(CreateRequest(name="missing", tool=Tool.CLAUDE, cwd=tmp_path))
    assert fake_backend.sessions == {}


def test_attach_refuses_name_reused_after_ownership_check(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service.create(CreateRequest(name="race", tool=Tool.SHELL, cwd=tmp_path))
    original_get_option = fake_backend.get_option

    def replace_after_check(name: str, option: str, expected_id: str | None = None) -> str | None:
        value = original_get_option(name, option, expected_id=expected_id)
        fake_backend.sessions[name] = fake_backend.sessions[name].model_copy(
            update={"session_id": "$replacement"}
        )
        return value

    monkeypatch.setattr(fake_backend, "get_option", replace_after_check)
    with pytest.raises(TmuxError, match="ID mismatch"):
        service.attach(created.name)
    assert fake_backend.attached == []


def test_runtime_and_activity_come_from_tmux_snapshot(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
) -> None:
    created = service.create(CreateRequest(name="runtime", tool=Tool.SHELL, cwd=tmp_path))
    activity = created.created_at.replace(year=2025)
    fake_backend.sessions[created.name] = fake_backend.sessions[created.name].model_copy(
        update={"attached_clients": 1, "last_activity_at": activity}
    )
    attached = service.get(created.name)
    assert attached.runtime is RuntimeState.ATTACHED
    assert attached.last_active_at is not None

    fake_backend.sessions[created.name] = fake_backend.sessions[created.name].model_copy(
        update={"attached_clients": 0, "pane_dead": True, "pane_dead_status": 7}
    )
    assert service.get(created.name).runtime is RuntimeState.FAILED


def test_logs_are_sanitized_and_report_truncation(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
) -> None:
    created = service.create(CreateRequest(name="logs", tool=Tool.SHELL, cwd=tmp_path))
    fake_backend.previews[created.name] = "\n".join(
        ["password=private", *[f"line-{index}" for index in range(600)]]
    )
    details = service.logs(created.name)
    assert details.preview_truncated
    assert "private" not in details.preview
    assert len(details.preview.splitlines()) == service.config.log_lines
