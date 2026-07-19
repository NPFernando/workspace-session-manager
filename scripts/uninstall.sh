#!/usr/bin/env bash
set -euo pipefail

owner_only_regular_file() {
  local path="$1"
  local mode
  [[ -f "$path" && ! -L "$path" && -O "$path" ]] || return 1
  mode="$(stat -c '%a' -- "$path")" || return 1
  (( (8#$mode & 8#077) == 0 ))
}

replace_with_symlink() {
  local destination="$1"
  local target_path="$2"
  local target_dir
  local temporary_dir
  local temporary_link
  target_dir="$(dirname -- "$target_path")"
  temporary_dir="$(mktemp -d --tmpdir="$target_dir" ".${target_path##*/}.switch.XXXXXX")"
  temporary_link="$temporary_dir/${target_path##*/}"
  if ! ln -s -- "$destination" "$temporary_link"; then
    rmdir -- "$temporary_dir" || true
    return 1
  fi
  if ! mv -Tf -- "$temporary_link" "$target_path"; then
    rm -f -- "$temporary_link"
    rmdir -- "$temporary_dir" || true
    return 1
  fi
  if ! rmdir -- "$temporary_dir"; then
    printf 'Warning: unable to remove temporary link directory: %s\n' "$temporary_dir" >&2
  fi
}

if [[ "${1:-}" != "--restore-classic" ]]; then
  printf '%s\n' 'Refusing rollback without explicit approval.' >&2
  printf '%s\n' 'Run: scripts/uninstall.sh --restore-classic' >&2
  exit 2
fi

install_root="${XDG_DATA_HOME:-$HOME/.local/share}/wf-session-manager"
target="$HOME/.local/bin/WF"
classic="$HOME/.local/libexec/wf-classic"
expected="$install_root/venv/bin/WF"
owner_marker="$install_root/classic-owner"

if ! owner_only_regular_file "$classic" || [[ ! -x "$classic" ]]; then
  printf 'Classic executable is unavailable: %s\n' "$classic" >&2
  exit 1
fi
if ! owner_only_regular_file "$owner_marker"; then
  printf 'Classic ownership marker is unavailable or unsafe: %s\n' "$owner_marker" >&2
  exit 1
fi

schema=''
expected_sha256=''
while IFS='=' read -r key value; do
  case "$key" in
    schema) schema="$value" ;;
    sha256) expected_sha256="$value" ;;
  esac
done < "$owner_marker"
if [[ "$schema" != '1' || ! "$expected_sha256" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'Invalid ownership marker: %s\n' "$owner_marker" >&2
  exit 1
fi
actual_sha256="$(sha256sum -- "$classic" | awk '{print $1}')"
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
  printf '%s\n' 'Refusing rollback because the preserved executable changed.' >&2
  exit 1
fi

if [[ ! -L "$target" || "$(readlink -f -- "$target")" != "$expected" ]]; then
  printf 'Refusing to replace an installer-unowned target: %s\n' "$target" >&2
  exit 1
fi

replace_with_symlink "$classic" "$target"
printf 'Restored classic WF: %s -> %s\n' "$target" "$classic"
printf '%s\n' 'New metadata and the virtual environment were retained for recovery.'
