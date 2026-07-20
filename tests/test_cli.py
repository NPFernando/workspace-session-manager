import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import FakeBackend
from wf_session_manager import cli
from wf_session_manager.cli import Runtime
from wf_session_manager.config import AppConfig
from wf_session_manager.legacy import LegacyMetadataReader
from wf_session_manager.migration import MigrationManager
from wf_session_manager.models import CreateRequest, InputState, TaskState, Tool
from wf_session_manager.paths import AppPaths
from wf_session_manager.service import SessionService
from wf_session_manager.store import MetadataStore


def test_version() -> None:
    result = CliRunner().invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("WF ")


def test_no_animation_option_reaches_tui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = AppPaths(tmp_path / "config", tmp_path / "state", tmp_path / "cache")
    runtime = Runtime(paths=paths, config=AppConfig())
    received: list[bool] = []
    monkeypatch.setattr(cli, "build_runtime", lambda config=None: runtime)
    monkeypatch.setattr(
        cli,
        "run_tui",
        lambda runtime, *, no_animation=False: received.append(no_animation),
    )
    result = CliRunner().invoke(cli.app, ["--no-animation"])
    assert result.exit_code == 0, result.output
    assert received == [True]


def test_classic_launcher_requires_owner_only_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classic = tmp_path / ".local" / "libexec" / "wf-classic"
    classic.parent.mkdir(parents=True)
    classic.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    classic.chmod(0o700)
    executed: list[tuple[Path, list[str]]] = []
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(
        cli.os,
        "execv",
        lambda path, args: executed.append((Path(path), args)),
    )
    cli.run_classic()
    assert executed == [(classic, [str(classic)])]

    classic.chmod(0o755)
    with pytest.raises(cli.WFError, match="unsafe classic"):
        cli.run_classic()


def test_json_list(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_backend.add("shell-one")
    monkeypatch.setattr(Runtime, "service", lambda self: service)
    result = CliRunner().invoke(cli.app, ["list", "--all", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload[0]["name"] == "shell-one"
    assert payload[0]["owned"] is False


def test_dry_run_does_not_create(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Runtime, "service", lambda self: service)
    result = CliRunner().invoke(
        cli.app,
        [
            "create",
            "--tool",
            "shell",
            "--name",
            "preview",
            "--cwd",
            str(tmp_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Would create: preview" in result.stdout
    assert fake_backend.sessions == {}


def test_default_list_hides_unmanaged_session(
    service: SessionService,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_backend.add("shell-hidden")
    monkeypatch.setattr(Runtime, "service", lambda self: service)
    result = CliRunner().invoke(cli.app, ["list", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


def test_explicit_edit_command_updates_task_input_and_project(
    service: SessionService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = service.create(CreateRequest(name="edit", tool=Tool.SHELL, cwd=tmp_path))
    monkeypatch.setattr(Runtime, "service", lambda self: service)
    result = CliRunner().invoke(
        cli.app,
        [
            "edit",
            session.name,
            "--state",
            "waiting",
            "--input",
            "required",
            "--project",
            "workflow-core",
        ],
    )
    assert result.exit_code == 0, result.output
    updated = service.get(session.name)
    assert updated.task_state is TaskState.WAITING
    assert updated.input_state is InputState.REQUIRED
    assert updated.project == "workflow-core"


def test_legacy_organize_alias_is_hidden_from_help() -> None:
    commands = {command.name: command for command in cli.app.registered_commands if command.name}
    assert not commands["edit"].hidden
    assert commands["organize"].hidden


def test_migration_cli_preview_apply_status_and_rollback(
    tmp_path: Path,
    fake_backend: FakeBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    name = "claude-import"
    (legacy / f"{name}.tool").write_text("claude\n", encoding="utf-8")
    (legacy / f"{name}.cwd").write_text(f"{tmp_path}\n", encoding="utf-8")
    (legacy / f"{name}.note").write_text("private migration note\n", encoding="utf-8")
    fake_backend.add(name, session_id="$cli-import")
    paths = AppPaths(tmp_path / "config", tmp_path / "state", tmp_path / "cache")
    manager = MigrationManager(
        backend=fake_backend,
        store=MetadataStore(paths),
        legacy=LegacyMetadataReader((legacy,)),
        paths=paths,
    )
    monkeypatch.setattr(Runtime, "migration", lambda self: manager)
    plan_path = tmp_path / "plan.json"
    runner = CliRunner()

    preview = runner.invoke(
        cli.app,
        ["migrate", "preview", "--all", "--output", str(plan_path)],
    )
    assert preview.exit_code == 0, preview.output
    assert "Notes are included" in preview.stdout
    assert plan_path.is_file()

    validation = runner.invoke(cli.app, ["migrate", "validate", str(plan_path), "--json"])
    assert validation.exit_code == 0, validation.output
    validation_payload = json.loads(validation.stdout)
    assert validation_payload["valid"] is True
    assert validation_payload["sessions"][0]["tmux_session_id"] == "$cli-import"
    assert "private migration note" not in validation.stdout

    gate = runner.invoke(cli.app, ["migrate", "apply", str(plan_path)])
    assert gate.exit_code == 2
    apply = runner.invoke(cli.app, ["migrate", "apply", str(plan_path), "--approve"])
    assert apply.exit_code == 0, apply.output
    migration_id = manager.status()[0].migration_id

    status = runner.invoke(cli.app, ["migrate", "status", "--json"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout)[0]["status"] == "applied"

    rollback = runner.invoke(
        cli.app,
        ["migrate", "rollback", str(migration_id), "--approve"],
    )
    assert rollback.exit_code == 0, rollback.output
    assert fake_backend.session_exists(name)
    assert fake_backend.get_option(name, "@wf_owner") is None


def test_migration_preview_requires_explicit_selection() -> None:
    result = CliRunner().invoke(cli.app, ["migrate", "preview"])
    assert result.exit_code == 2
    assert "choose --all or at least one --session" in result.output
