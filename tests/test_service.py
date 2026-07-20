from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from conftest import FakeBackend
from wf_session_manager.errors import OwnershipError, StateError, TmuxError, ToolUnavailableError
from wf_session_manager.models import (
    CreateRequest,
    DoctorReport,
    HealthCheck,
    HealthStatus,
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
    assert created.display_name == "API Refactor"
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

    monkeypatch.setattr(service.store, "save_new", fail_save)
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


def test_create_validation_detects_duplicate_directory_and_git_project(
    service: SessionService,
    tmp_path: Path,
) -> None:
    project = tmp_path / "api-platform"
    nested = project / "src"
    nested.mkdir(parents=True)
    (project / ".git").mkdir()
    validation = service.validate_create(Tool.CLAUDE, "api", nested)
    assert validation.valid
    assert validation.normalized_name == "claude-api"
    assert validation.cwd == nested
    assert validation.detected_project == "api-platform"

    service.create(CreateRequest(name="api", tool=Tool.CLAUDE, cwd=nested))
    duplicate = service.validate_create(Tool.CLAUDE, "api", nested)
    assert not duplicate.valid
    assert duplicate.name_error
    assert not duplicate.cwd_error
    assert "already exists" in duplicate.errors[0]

    missing = service.validate_create(Tool.CLAUDE, "api-refactor", nested / "missing")
    assert not missing.valid
    assert not missing.name_error
    assert missing.cwd_error


def test_create_collision_uses_final_normalized_name(
    service: SessionService,
    tmp_path: Path,
) -> None:
    service.create(CreateRequest(name="api_refactor", tool=Tool.CLAUDE, cwd=tmp_path))
    duplicate = service.validate_create(Tool.CLAUDE, "api-refactor", tmp_path)
    assert duplicate.normalized_name == "claude-api-refactor"
    assert "already exists" in duplicate.name_error

    without_prefix = service.validate_create(
        Tool.CLAUDE, "api-refactor", tmp_path, automatic_prefix=False
    )
    assert without_prefix.valid
    assert without_prefix.normalized_name == "api-refactor"


def test_rename_validation_and_display_name_update(
    service: SessionService,
    tmp_path: Path,
) -> None:
    current = service.create(CreateRequest(name="current", tool=Tool.CLAUDE, cwd=tmp_path))
    service.create(CreateRequest(name="existing", tool=Tool.CLAUDE, cwd=tmp_path))

    valid = service.validate_rename(current.name, "api_refactor")
    assert valid.valid
    assert valid.normalized_name == "claude-api-refactor"

    duplicate = service.validate_rename(current.name, "existing")
    assert not duplicate.valid
    assert duplicate.normalized_name == "claude-existing"
    assert "already exists" in duplicate.name_error

    unchanged = service.validate_rename(current.name, current.name)
    assert unchanged.valid
    assert unchanged.normalized_name == current.name

    updated = service.organize(current.name, display_name="API Refactor")
    assert updated.display_name == "API Refactor"


def test_project_detection_uses_metadata_and_never_names_home_ubuntu(
    service: SessionService,
) -> None:
    with TemporaryDirectory(prefix="wf-project-", dir="/var/tmp") as directory:
        project = Path(directory)
        (project / "pyproject.toml").write_text(
            '[project]\nname = "metadata-project"\n', encoding="utf-8"
        )
        assert service.detect_project(project) == "metadata-project"
    assert service.detect_project(Path.home()) == ""


def test_diagnostics_classifies_environment_facts_as_information(
    service: SessionService,
) -> None:
    report = service.doctor()
    statuses = {check.name: check.status for check in report.checks}
    assert statuses["unmanaged-sessions"] is HealthStatus.INFO
    assert statuses["legacy-readonly"] is HealthStatus.INFO


def test_logging_stop_restart_and_metadata_removal_are_explicit(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
) -> None:
    created = service.create(
        CreateRequest(
            name="protected",
            tool=Tool.CODEX,
            cwd=tmp_path,
            logging_enabled=True,
        )
    )
    assert created.logging_enabled
    record = service.store.load(created.name)
    assert record is not None
    log_path = service.paths.logs_dir / f"{record.record_id}.log"
    assert log_path.is_file()
    assert log_path.stat().st_mode & 0o777 == 0o600

    service.stop_command(created.name)
    assert fake_backend.interrupted == [created.name]

    stopped = service.stop_session(created.name)
    assert stopped.runtime is RuntimeState.STOPPED
    assert not fake_backend.session_exists(created.name)
    organized = service.organize(created.name, state=TaskState.WAITING)
    assert organized.task_state is TaskState.WAITING

    restarted = service.restart(created.name)
    assert restarted.runtime is RuntimeState.DETACHED
    assert restarted.session_id != created.session_id
    service.remove_metadata(created.name)
    assert fake_backend.session_exists(created.name)
    assert fake_backend.get_option(created.name, "@wf_owner") is None
    assert service.list_sessions() == []


def test_delete_logs_preserves_enabled_logging(
    service: SessionService,
    tmp_path: Path,
) -> None:
    created = service.create(
        CreateRequest(name="logged", tool=Tool.SHELL, cwd=tmp_path, logging_enabled=True)
    )
    record = service.store.load(created.name)
    assert record is not None
    path = service.paths.logs_dir / f"{record.record_id}.log"
    path.write_text("sanitized output\n", encoding="utf-8")
    updated = service.delete_logs(created.name)
    assert updated.logging_enabled
    assert path.read_text(encoding="utf-8") == ""


def test_live_restart_reestablishes_logging(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
) -> None:
    created = service.create(
        CreateRequest(name="restart-logging", tool=Tool.SHELL, cwd=tmp_path, logging_enabled=True)
    )
    restarted = service.restart(created.name)
    assert restarted.logging_enabled
    assert fake_backend.restarted == [created.name]
    assert created.name in fake_backend.logging_paths


def test_stopped_restart_rolls_back_new_tmux_session_when_state_save_fails(
    service: SessionService,
    fake_backend: FakeBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = service.create(CreateRequest(name="restart-rollback", tool=Tool.SHELL, cwd=tmp_path))
    service.stop_session(created.name)
    original = service.store.load(created.name)
    assert original is not None

    def fail_save(record: SessionMetadata) -> None:
        del record
        raise StateError("simulated save failure")

    monkeypatch.setattr(service.store, "save", fail_save)
    with pytest.raises(StateError, match="simulated save failure"):
        service.restart(created.name)
    assert not fake_backend.session_exists(created.name)
    assert service.store.load(created.name) == original


def test_privacy_safe_diagnostic_export_redacts_sensitive_values(
    service: SessionService,
) -> None:
    report = DoctorReport(
        checks=[
            HealthCheck(
                name="state",
                status=HealthStatus.FAIL,
                detail=f"{Path.home()}/private password=not-safe 192.168.1.1",
                corrective_action="Repair state.",
            )
        ]
    )
    destination = service.export_doctor_report(report)
    exported = destination.read_text(encoding="utf-8")
    assert str(Path.home()) not in exported
    assert "not-safe" not in exported
    assert "192.168.1.1" not in exported
    assert destination.stat().st_mode & 0o777 == 0o600
