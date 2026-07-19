#!/usr/bin/env bash
set -euo pipefail

owner_only_regular_file() {
  local path="$1"
  local mode
  [[ -f "$path" && ! -L "$path" && -O "$path" ]] || return 1
  mode="$(stat -c '%a' -- "$path")" || return 1
  (( (8#$mode & 8#077) == 0 ))
}

install_root="${XDG_DATA_HOME:-$HOME/.local/share}/wf-session-manager"
classic="$HOME/.local/libexec/wf-classic"
owner_marker="$install_root/classic-owner"
archive_dir="$install_root/classic-archive"
target="$HOME/.local/bin/WF"
expected="$install_root/venv/bin/WF"
approve=0

if [[ "${1:-}" == "--approve-retirement" && -z "${2:-}" ]]; then
  approve=1
elif [[ -n "${1:-}" ]]; then
  printf '%s\n' 'Usage: scripts/retire-classic.sh [--approve-retirement]' >&2
  exit 2
fi

if [[ ! -L "$target" || "$(readlink -f -- "$target")" != "$expected" \
  || ! -f "$expected" || -L "$expected" || ! -x "$expected" || ! -O "$expected" ]]; then
  printf '%s\n' 'Refusing retirement because the new WF installation is not active.' >&2
  exit 1
fi
if ! owner_only_regular_file "$owner_marker"; then
  printf 'Refusing retirement without an installer ownership marker: %s\n' "$owner_marker" >&2
  exit 1
fi
if ! owner_only_regular_file "$classic" || [[ ! -x "$classic" ]]; then
  printf 'Refusing retirement of an unsafe or missing file: %s\n' "$classic" >&2
  exit 1
fi

schema=''
cutover_epoch=''
expected_sha256=''
while IFS='=' read -r key value; do
  case "$key" in
    schema) schema="$value" ;;
    cutover_epoch) cutover_epoch="$value" ;;
    sha256) expected_sha256="$value" ;;
  esac
done < "$owner_marker"

if [[ "$schema" != '1' || ! "$cutover_epoch" =~ ^[0-9]+$ \
  || ! "$expected_sha256" =~ ^[0-9a-f]{64}$ ]]; then
  printf 'Invalid ownership marker: %s\n' "$owner_marker" >&2
  exit 1
fi

actual_sha256="$(sha256sum -- "$classic" | awk '{print $1}')"
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
  printf '%s\n' 'Refusing retirement because the preserved executable changed.' >&2
  exit 1
fi

now_epoch="$(date -u +%s)"
minimum_epoch=$((cutover_epoch + 7 * 24 * 60 * 60))
if (( now_epoch < minimum_epoch )); then
  printf 'Refusing retirement before the seven-day soak completes at epoch %s.\n' \
    "$minimum_epoch" >&2
  exit 1
fi

if (( approve == 0 )); then
  printf 'Dry run; eligible installer-owned file: %s\n' "$classic"
  printf '%s\n' 'No files changed. Re-run with --approve-retirement.'
  exit 0
fi

mkdir -p "$archive_dir"
chmod 700 "$archive_dir"
timestamp="$(date -u +%Y%m%d-%H%M%S)"
archive="$archive_dir/wf-classic.$timestamp.tar.gz"
temporary="$archive.tmp"
classic_name="$(basename -- "$classic")"
if [[ -e "$archive" || -L "$archive" || -e "$archive.sha256" || -L "$archive.sha256" ]]; then
  printf 'Refusing to overwrite an existing retirement archive: %s\n' "$archive" >&2
  exit 1
fi
tar -czf "$temporary" -C "$(dirname -- "$classic")" "$classic_name"
chmod 600 "$temporary"
mv -- "$temporary" "$archive"
if [[ "$(tar -tzf "$archive")" != "$classic_name" ]]; then
  printf '%s\n' 'Refusing retirement because the archive has unexpected contents.' >&2
  exit 1
fi
if ! archived_sha256="$(tar -xOzf "$archive" -- "$classic_name" | sha256sum | awk '{print $1}')"; then
  printf '%s\n' 'Refusing retirement because the archived executable cannot be verified.' >&2
  exit 1
fi
if [[ "$archived_sha256" != "$expected_sha256" ]]; then
  printf '%s\n' 'Refusing retirement because the archived executable does not match.' >&2
  exit 1
fi
archive_name="$(basename -- "$archive")"
checksum_name="$archive_name.sha256"
(
  cd -- "$archive_dir"
  sha256sum -- "$archive_name" > "$checksum_name"
  sha256sum -c -- "$checksum_name" >/dev/null
)
chmod 600 "$archive.sha256"

if [[ ! -L "$target" || "$(readlink -f -- "$target")" != "$expected" ]] \
  || ! owner_only_regular_file "$classic" \
  || [[ "$(sha256sum -- "$classic" | awk '{print $1}')" != "$expected_sha256" ]]; then
  printf '%s\n' 'Refusing retirement because cutover state changed during archival.' >&2
  exit 1
fi
rm -- "$classic"
rm -- "$owner_marker"
printf 'Archived installer-owned classic executable: %s\n' "$archive"
printf 'Archive checksum: %s\n' "$archive.sha256"
printf '%s\n' 'No tmux session, legacy metadata, source launcher, or shell profile was removed.'
