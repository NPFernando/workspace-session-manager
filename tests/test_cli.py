import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import FakeBackend
from wf_session_manager import cli
from wf_session_manager.cli import Runtime
from wf_session_manager.service import SessionService


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
    result = CliRunner().invoke(cli.app, ["list", "--json"])
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
