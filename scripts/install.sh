#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--approve-cutover" ]]; then
  printf '%s\n' 'Refusing cutover without explicit approval.' >&2
  printf '%s\n' 'Run: scripts/install.sh --approve-cutover' >&2
  exit 2
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
install_root="${XDG_DATA_HOME:-$HOME/.local/share}/wf-session-manager"
venv_dir="$install_root/venv"
bin_dir="$HOME/.local/bin"
libexec_dir="$HOME/.local/libexec"
target="$bin_dir/WF"
classic="$libexec_dir/wf-classic"
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

if [[ ! -e "$classic" ]]; then
  cp -p -- "$current_resolved" "$classic"
  chmod 700 "$classic"
fi

python3 -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install "$project_dir"
"$venv_dir/bin/wf-dev" doctor

backup="$install_root/WF.pre-cutover.$(date +%Y%m%d-%H%M%S)"
cp -a -- "$current" "$backup"
ln -sfn -- "$venv_dir/bin/WF" "$target"

printf 'Installed: %s\n' "$target"
printf 'Classic fallback: %s\n' "$classic"
printf 'Previous command backup: %s\n' "$backup"
printf '%s\n' 'Shell profiles and tmux sessions were not changed.'
