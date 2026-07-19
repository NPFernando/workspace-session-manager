#!/usr/bin/env python3
"""Approval-gated replacement of the assessed legacy SSH startup hook."""

from __future__ import annotations

import argparse
import difflib
import os
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

OLD_HOOK = """# Auto-open workspace cockpit for SSH logins
if [[ $- == *i* ]] \\
  && [[ -n "${SSH_CONNECTION:-}" ]] \\
  && [[ -z "${TMUX:-}" ]] \\
  && [[ -z "${NO_WS_MENU:-}" ]] \\
  && [[ -z "${WS_MENU_SHOWN:-}" ]] \\
  && [[ "${TERM:-}" != "dumb" ]] \\
  && command -v tmux >/dev/null 2>&1 \\
  && [[ -x "$HOME/ws" ]]; then
  export WS_MENU_SHOWN=1
  if [[ "${WS_MENU_AUTO_RESUME:-0}" == "1" ]]; then
    "$HOME/ws" resume || "$HOME/ws" menu
  else
    case "${WS_MENU_DEFAULT:-start}" in
      resume) "$HOME/ws" resume || "$HOME/ws" start ;;
      status) "$HOME/ws" status ;;
      shell) ;;
      smart|start|startup) "$HOME/ws" start ;;
      cockpit|today) "$HOME/ws" cockpit ;;
      dashboard|project) "$HOME/ws" project ;;
      recent-projects) "$HOME/ws" recent-projects ;;
      search|switch) "$HOME/ws" switch ;;
      doctor) "$HOME/ws" doctor ;;
      config) "$HOME/ws" config ;;
      menu|"") "$HOME/ws" menu ;;
      *) "$HOME/ws" start ;;
    esac
  fi
fi
"""

NEW_HOOK = """# BEGIN WF SESSION MANAGER SSH HOOK
if [[ $- == *i* ]] \\
  && [[ -n "${SSH_CONNECTION:-}" ]] \\
  && [[ -z "${TMUX:-}" ]] \\
  && [[ -z "${NO_WF_MENU:-}" ]] \\
  && [[ -z "${NO_WS_MENU:-}" ]] \\
  && [[ -z "${WF_MENU_SHOWN:-}" ]] \\
  && [[ -z "${WS_MENU_SHOWN:-}" ]] \\
  && [[ "${TERM:-}" != "dumb" ]] \\
  && command -v tmux >/dev/null 2>&1 \\
  && command -v WF >/dev/null 2>&1; then
  export WF_MENU_SHOWN=1
  export WS_MENU_SHOWN=1
  WF
fi
# END WF SESSION MANAGER SSH HOOK
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or approve replacement of the assessed SSH startup hook."
    )
    parser.add_argument("--profile", type=Path, default=Path.home() / ".bashrc")
    parser.add_argument("--approve-cutover", action="store_true")
    return parser.parse_args()


def atomic_write(path: Path, content: str, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> int:
    args = parse_args()
    profile = args.profile.expanduser().absolute()
    if profile.is_symlink() or not profile.is_file():
        raise SystemExit(f"Refusing unsafe or missing profile: {profile}")
    content = profile.read_text(encoding="utf-8")
    if NEW_HOOK in content:
        print(f"SSH hook is already migrated: {profile}")
        return 0
    occurrences = content.count(OLD_HOOK)
    if occurrences != 1:
        raise SystemExit(
            f"Expected the assessed SSH hook exactly once in {profile}; found {occurrences}."
        )

    if not args.approve_cutover:
        print(f"Dry run; no files changed: {profile}")
        print(
            "".join(
                difflib.unified_diff(
                    OLD_HOOK.splitlines(keepends=True),
                    NEW_HOOK.splitlines(keepends=True),
                    fromfile="current SSH hook",
                    tofile="WF SSH hook",
                )
            ),
            end="",
        )
        print("Re-run with --approve-cutover after reviewing this diff.")
        return 0

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup = profile.with_name(f"{profile.name}.wf-pre-cutover.{timestamp}")
    mode = stat.S_IMODE(profile.stat().st_mode)
    atomic_write(backup, content, mode)
    atomic_write(profile, content.replace(OLD_HOOK, NEW_HOOK), mode)
    print(f"Migrated SSH hook: {profile}")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
