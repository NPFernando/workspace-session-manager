#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--restore-classic" ]]; then
  printf '%s\n' 'Refusing rollback without explicit approval.' >&2
  printf '%s\n' 'Run: scripts/uninstall.sh --restore-classic' >&2
  exit 2
fi

install_root="${XDG_DATA_HOME:-$HOME/.local/share}/wf-session-manager"
target="$HOME/.local/bin/WF"
classic="$HOME/.local/libexec/wf-classic"
expected="$install_root/venv/bin/WF"

if [[ ! -x "$classic" ]]; then
  printf 'Classic executable is unavailable: %s\n' "$classic" >&2
  exit 1
fi

if [[ ! -L "$target" || "$(readlink -f -- "$target")" != "$expected" ]]; then
  printf 'Refusing to replace an installer-unowned target: %s\n' "$target" >&2
  exit 1
fi

ln -sfn -- "$classic" "$target"
printf 'Restored classic WF: %s -> %s\n' "$target" "$classic"
printf '%s\n' 'New metadata and the virtual environment were retained for recovery.'

