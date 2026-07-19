import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import FakeBackend
from wf_session_manager import cli
from wf_session_manager.cli import Runtime
from wf_session_manager.legacy import LegacyMetadataReader
from wf_session_manager.migration import MigrationManager
from wf_session_manager.paths import AppPaths
from wf_session_manager.service import SessionService
from wf_session_manager.store import MetadataStore


def test_version() -> None:
    result = CliRunner().invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("WF ")


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
