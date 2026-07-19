#!/usr/bin/env bash
set -euo pipefail

install_root="${XDG_DATA_HOME:-$HOME/.local/share}/wf-session-manager"
classic="$HOME/.local/libexec/wf-classic"
owner_marker="$install_root/classic-owner"
archive_dir="$install_root/classic-archive"
approve=0

if [[ "${1:-}" == "--approve-retirement" && -z "${2:-}" ]]; then
  approve=1
elif [[ -n "${1:-}" ]]; then
  printf '%s\n' 'Usage: scripts/retire-classic.sh [--approve-retirement]' >&2
  exit 2
fi

if [[ ! -f "$owner_marker" || -L "$owner_marker" ]]; then
  printf 'Refusing retirement without an installer ownership marker: %s\n' "$owner_marker" >&2
  exit 1
fi
if [[ ! -f "$classic" || -L "$classic" ]]; then
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
tar -czf "$temporary" -C "$(dirname -- "$classic")" "$(basename -- "$classic")"
chmod 600 "$temporary"
mv -- "$temporary" "$archive"
sha256sum -- "$archive" > "$archive.sha256"
chmod 600 "$archive.sha256"

rm -- "$classic"
rm -- "$owner_marker"
printf 'Archived installer-owned classic executable: %s\n' "$archive"
printf 'Archive checksum: %s\n' "$archive.sha256"
printf '%s\n' 'No tmux session, legacy metadata, source launcher, or shell profile was removed.'
