#!/usr/bin/env bash
set -euo pipefail

owner_only_regular_file() {
  local path="$1"
  local mode
  [[ -f "$path" && ! -L "$path" && -O "$path" ]] || return 1
  mode="$(stat -c '%a' -- "$path")" || return 1
  (( (8#$mode & 8#077) == 0 ))
}

rollback_migration_on_failure() {
  local status=$?
  local rollback_status
  trap - EXIT
  if (( status != 0 && migration_applied == 1 && cutover_complete == 0 )); then
    set +e
    printf 'Pre-cutover failure; rolling back migration %s.\n' "$migration_id" >&2
    "$venv_dir/bin/wf-dev" migrate rollback "$migration_id" --approve
    rollback_status=$?
    if (( rollback_status == 0 )); then
      printf 'Rolled back migration %s; the WF command was not switched.\n' \
        "$migration_id" >&2
    else
      printf 'Automatic rollback failed for migration %s; inspect it with %s migrate status.\n' \
        "$migration_id" "$venv_dir/bin/wf-dev" >&2
    fi
  fi
  exit "$status"
}

approve=0
migration_plan=''
while (( $# > 0 )); do
  case "$1" in
    --approve-cutover)
      approve=1
      shift
      ;;
    --migration-plan)
      if (( $# < 2 )); then
        printf '%s\n' 'Missing path after --migration-plan.' >&2
        exit 2
      fi
      migration_plan="$2"
      shift 2
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

if (( approve == 0 )); then
  printf '%s\n' 'Refusing cutover without explicit approval.' >&2
  printf '%s\n' \
    'Run: scripts/install.sh --approve-cutover [--migration-plan reviewed-plan.json]' >&2
  exit 2
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
install_root="${XDG_DATA_HOME:-$HOME/.local/share}/wf-session-manager"
venv_dir="$install_root/venv"
bin_dir="$HOME/.local/bin"
libexec_dir="$HOME/.local/libexec"
target="$bin_dir/WF"
classic="$libexec_dir/wf-classic"
owner_marker="$install_root/classic-owner"
cutover_lock="$install_root/cutover.lock"
migration_id=''
migration_applied=0
cutover_complete=0
trap rollback_migration_on_failure EXIT
if [[ -d "$target" && ! -L "$target" ]]; then
  printf 'Refusing directory at command target: %s\n' "$target" >&2
  exit 1
fi
if [[ -e "$target" || -L "$target" ]]; then
  current="$target"
else
  current="$(command -v WF 2>/dev/null || true)"
fi

if [[ -z "$current" || ! -e "$current" ]]; then
  printf '%s\n' 'Cannot preserve classic WF: current command was not found.' >&2
  exit 1
fi

current_resolved="$(readlink -f -- "$current")"
if [[ "$current_resolved" == "$venv_dir/bin/WF" ]]; then
  printf '%s\n' 'WF Session Manager is already installed.'
  exit 0
fi
if [[ ! -f "$current_resolved" || ! -x "$current_resolved" ]]; then
  printf 'Cannot preserve unsafe or non-executable WF command: %s\n' "$current_resolved" >&2
  exit 1
fi

mkdir -p "$install_root" "$bin_dir" "$libexec_dir"
chmod 700 "$install_root" "$libexec_dir"
if ! command -v flock >/dev/null 2>&1; then
  printf '%s\n' 'Cannot serialize cutover: required command flock was not found.' >&2
  exit 1
fi
if [[ ( -e "$cutover_lock" || -L "$cutover_lock" ) ]] \
  && ! owner_only_regular_file "$cutover_lock"; then
  printf 'Refusing unsafe cutover lock: %s\n' "$cutover_lock" >&2
  exit 1
fi
umask 077
exec 9> "$cutover_lock"
chmod 600 "$cutover_lock"
if ! flock -n 9; then
  printf '%s\n' 'Refusing concurrent cutover: another installer holds the cutover lock.' >&2
  exit 1
fi
if [[ ( -e "$owner_marker" || -L "$owner_marker" ) ]] \
  && ! owner_only_regular_file "$owner_marker"; then
  printf 'Refusing unsafe ownership marker: %s\n' "$owner_marker" >&2
  exit 1
fi

current_sha256="$(sha256sum -- "$current_resolved" | awk '{print $1}')"
if [[ ! -e "$classic" && ! -L "$classic" ]]; then
  cp -p -- "$current_resolved" "$classic"
  chmod 700 "$classic"
elif ! owner_only_regular_file "$classic" || [[ ! -x "$classic" ]]; then
  printf 'Refusing unsafe preservation target: %s\n' "$classic" >&2
  exit 1
fi
classic_sha256="$(sha256sum -- "$classic" | awk '{print $1}')"
if [[ "$classic_sha256" != "$current_sha256" ]]; then
  printf '%s\n' 'Refusing cutover because the preserved executable does not match current WF.' >&2
  exit 1
fi

python3 -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install "$project_dir"
"$venv_dir/bin/wf-dev" doctor

if [[ -n "$migration_plan" ]]; then
  validation_json="$("$venv_dir/bin/wf-dev" migrate validate "$migration_plan" --json)"
  migration_id="$(
    printf '%s\n' "$validation_json" \
      | "$venv_dir/bin/python" -c \
        'import json,sys,uuid; print(uuid.UUID(json.load(sys.stdin)["plan_id"]))'
  )"
  printf 'Validated migration plan: %s\n' "$migration_id"
  "$venv_dir/bin/wf-dev" migrate apply "$migration_plan" --approve
  migration_applied=1
fi

legacy_unmanaged="$(
  "$venv_dir/bin/wf-dev" list --all --json \
    | "$venv_dir/bin/python" -c \
      'import json,sys; print(sum(not x["owned"] and x["legacy_metadata"] for x in json.load(sys.stdin)))'
)"
if (( legacy_unmanaged > 0 )); then
  printf 'Refusing cutover: %s legacy-managed tmux session(s) remain unadopted.\n' \
    "$legacy_unmanaged" >&2
  printf '%s\n' 'Generate and review a migration plan with wf-dev migrate preview.' >&2
  exit 1
fi

backup="$install_root/WF.pre-cutover.$(date +%Y%m%d-%H%M%S)"
cp -a -- "$current" "$backup"
marker_temporary="$(mktemp --tmpdir="$install_root" '.classic-owner.XXXXXX')"
umask 077
{
  printf '%s\n' 'schema=1'
  printf 'cutover_epoch=%s\n' "$(date -u +%s)"
  printf 'sha256=%s\n' "$classic_sha256"
} > "$marker_temporary"
chmod 600 "$marker_temporary"
mv -- "$marker_temporary" "$owner_marker"
ln -sfn -- "$venv_dir/bin/WF" "$target"
cutover_complete=1
trap - EXIT

printf 'Installed: %s\n' "$target"
printf 'Preserved pre-cutover executable: %s\n' "$classic"
printf 'Previous command backup: %s\n' "$backup"
printf '%s\n' \
  'Shell profiles were not changed; tmux processes were not restarted, renamed, or terminated.'
