from pathlib import Path

import pytest

from conftest import FakeBackend
from wf_session_manager.errors import OwnershipError, StateError, ToolUnavailableError
from wf_session_manager.models import CreateRequest, SessionMetadata, SessionState, Tool
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
        state=SessionState.WAITING,
        pinned=True,
    )
    assert organized.note == "Updated task"
    assert organized.tags == ["backend", "urgent"]
    assert organized.pinned

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
