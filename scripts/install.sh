#!/usr/bin/env bash
set -euo pipefail

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

mkdir -p "$install_root" "$bin_dir" "$libexec_dir"
chmod 700 "$install_root" "$libexec_dir"

classic_created=0
if [[ ! -e "$classic" ]]; then
  cp -p -- "$current_resolved" "$classic"
  chmod 700 "$classic"
  classic_created=1
elif [[ -L "$classic" || ! -f "$classic" || ! -x "$classic" ]]; then
  printf 'Refusing unsafe preservation target: %s\n' "$classic" >&2
  exit 1
fi

python3 -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install "$project_dir"
"$venv_dir/bin/wf-dev" doctor

if [[ -n "$migration_plan" ]]; then
  "$venv_dir/bin/wf-dev" migrate apply "$migration_plan" --approve
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
ln -sfn -- "$venv_dir/bin/WF" "$target"

if (( classic_created == 1 )); then
  owner_marker="$install_root/classic-owner"
  marker_temporary="$owner_marker.tmp"
  umask 077
  {
    printf '%s\n' 'schema=1'
    printf 'cutover_epoch=%s\n' "$(date -u +%s)"
    printf 'sha256=%s\n' "$(sha256sum -- "$classic" | awk '{print $1}')"
  } > "$marker_temporary"
  mv -- "$marker_temporary" "$owner_marker"
fi

printf 'Installed: %s\n' "$target"
printf 'Preserved pre-cutover executable: %s\n' "$classic"
printf 'Previous command backup: %s\n' "$backup"
printf '%s\n' 'Shell profiles and tmux sessions were not changed.'
