"""Read-only adapter for legacy WF sidecar metadata."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from wf_session_manager.models import SESSION_NAME_PATTERN, LegacyMetadata, Tool

MAX_SIDECAR_BYTES = 4096


class LegacyMetadataReader:
    def __init__(self, roots: tuple[Path, ...]) -> None:
        self.roots = tuple(root.expanduser() for root in roots)

    def _first_line(self, path: Path) -> str:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SIDECAR_BYTES:
                return ""
            with path.open(encoding="utf-8", errors="replace") as stream:
                return stream.readline(MAX_SIDECAR_BYTES).strip()
        except OSError:
            return ""

    def _lines(self, path: Path) -> list[str]:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SIDECAR_BYTES:
                return []
            return [
                line.strip()
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.strip()
            ]
        except OSError:
            return []

    def _read_root(self, root: Path, name: str) -> LegacyMetadata | None:
        values = {
            suffix: self._first_line(root / f"{name}.{suffix}")
            for suffix in ("tool", "cwd", "project", "note", "state", "last")
        }
        pinned_path = root / f"{name}.pinned"
        pinned = pinned_path.is_file() and not pinned_path.is_symlink()
        tags = self._lines(root / f"{name}.tags")
        if not any(values.values()) and not tags and not pinned:
            return None

        try:
            tool = Tool(values["tool"]) if values["tool"] else None
        except ValueError:
            tool = None
        try:
            last_used = datetime.fromisoformat(values["last"]) if values["last"] else None
            if last_used and last_used.tzinfo is None:
                last_used = last_used.astimezone()
        except ValueError:
            last_used = None

        return LegacyMetadata(
            tool=tool,
            cwd=Path(values["cwd"]) if values["cwd"] else None,
            project=Path(values["project"]) if values["project"] else None,
            note=values["note"],
            tags=tags,
            state=values["state"],
            last_used=last_used,
            pinned=pinned,
            source=root,
        )

    def read_all(self, name: str) -> list[LegacyMetadata]:
        if not SESSION_NAME_PATTERN.fullmatch(name):
            return []
        return [metadata for root in self.roots if (metadata := self._read_root(root, name))]

    def read(self, name: str) -> LegacyMetadata | None:
        values = self.read_all(name)
        return values[0] if values else None
