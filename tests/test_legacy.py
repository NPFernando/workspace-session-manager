from pathlib import Path

from wf_session_manager.legacy import LegacyMetadataReader
from wf_session_manager.models import Tool


def test_legacy_reader_reads_sidecars_without_writing(tmp_path: Path) -> None:
    (tmp_path / "claude-old.tool").write_text("claude\n", encoding="utf-8")
    (tmp_path / "claude-old.cwd").write_text("/srv/project\n", encoding="utf-8")
    (tmp_path / "claude-old.note").write_text("Legacy task\n", encoding="utf-8")
    before = sorted(tmp_path.iterdir())
    metadata = LegacyMetadataReader((tmp_path,)).read("claude-old")
    assert metadata is not None
    assert metadata.tool is Tool.CLAUDE
    assert metadata.cwd == Path("/srv/project")
    assert metadata.note == "Legacy task"
    assert sorted(tmp_path.iterdir()) == before


def test_legacy_reader_rejects_symlink_and_unsafe_name(tmp_path: Path) -> None:
    target = tmp_path / "private"
    target.write_text("secret\n", encoding="utf-8")
    (tmp_path / "claude-old.note").symlink_to(target)
    reader = LegacyMetadataReader((tmp_path,))
    metadata = reader.read("claude-old")
    assert metadata is None
    assert reader.read("../private") is None
