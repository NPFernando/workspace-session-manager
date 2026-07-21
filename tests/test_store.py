import stat
from pathlib import Path

import pytest

from workspace_session_manager.errors import StateError
from workspace_session_manager.models import SessionMetadata, Tool
from workspace_session_manager.paths import AppPaths
from workspace_session_manager.store import MetadataStore


def make_record(name: str = "claude-test") -> SessionMetadata:
    return SessionMetadata(
        tmux_session_id="$1",
        name=name,
        tool=Tool.CLAUDE,
        cwd=Path("/tmp"),
    )


def test_store_writes_owner_only_atomic_json(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "config", tmp_path / "state", tmp_path / "cache")
    store = MetadataStore(paths)
    record = make_record()
    store.save(record)
    stored_path = paths.sessions_dir / "claude-test.json"
    assert store.load("claude-test") == record
    assert stat.S_IMODE(stored_path.stat().st_mode) == 0o600
    assert not list(paths.sessions_dir.glob(".claude-test.json.*"))


def test_store_rejects_symlinked_metadata(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "config", tmp_path / "state", tmp_path / "cache")
    paths.sessions_dir.mkdir(parents=True)
    target = tmp_path / "outside"
    target.write_text(make_record().model_dump_json(), encoding="utf-8")
    (paths.sessions_dir / "claude-test.json").symlink_to(target)
    with pytest.raises(StateError, match="symlinked"):
        MetadataStore(paths).load("claude-test")
