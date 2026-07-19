"""Read-only adapter for classic WF sidecar metadata."""

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

    def read(self, name: str) -> LegacyMetadata | None:
        if not SESSION_NAME_PATTERN.fullmatch(name):
            return None
        for root in self.roots:
            values = {
                suffix: self._first_line(root / f"{name}.{suffix}")
                for suffix in ("tool", "cwd", "project", "note", "state", "last")
            }
            pinned = (root / f"{name}.pinned").is_file()
            if not any(values.values()) and not pinned:
                continue

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
                state=values["state"],
                last_used=last_used,
                pinned=pinned,
                source=root,
            )
        return None
