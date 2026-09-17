#!/usr/bin/env bash
set -euo pipefail

# Retires the middle-generation "WF" install (the second-generation tool
# this project itself replaced — not the original bash ~/ws "classic"
# script, which retire-classic.sh already handles separately). Unlike that
# script, there's no single small checksummed executable to preserve here:
# WF is a full Python venv, entirely reproducible from its own git history
# if ever needed again, so this doesn't archive it before removal — it
# just refuses unless every live safety check passes.

owner_only_regular_file() {
  local path="$1"
  local mode
  [[ -f "$path" && ! -L "$path" && -O "$path" ]] || return 1
  mode="$(stat -c '%a' -- "$path")" || return 1
  (( (8#$mode & 8#077) == 0 ))
}

# Ordinary venv-installed executables (unlike the hand-placed
# classic-owner marker) are commonly group/other readable depending on
# umask — that's expected, not a tamper signal. This only checks type
# and ownership, not the private-mode-bits requirement.
owned_regular_file() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" && -O "$path" ]]
}

wf_data_root="${XDG_DATA_HOME:-$HOME/.local/share}/wf-session-manager"
wf_target="$HOME/.local/bin/WF"
wf_expected="$wf_data_root/venv/bin/WF"
ws_target="$HOME/.local/bin/ws"
install_root="${XDG_DATA_HOME:-$HOME/.local/share}/workspace-session-manager"
ws_expected="$install_root/venv/bin/ws"
approve=0

if [[ "${1:-}" == "--approve-retirement" && -z "${2:-}" ]]; then
  approve=1
elif [[ -n "${1:-}" ]]; then
  printf '%s\n' 'Usage: scripts/retire-wf.sh [--approve-retirement]' >&2
  exit 2
fi

# 1. ws must be the active, installer-owned command — otherwise nothing has
#    actually taken over from WF yet and removing it would strand sessions.
if [[ ! -L "$ws_target" || "$(readlink -f -- "$ws_target")" != "$ws_expected" ]] \
  || ! owned_regular_file "$ws_expected" || [[ ! -x "$ws_expected" ]]; then
  printf '%s\n' 'Refusing retirement because ws is not the active installation.' >&2
  exit 1
fi

# 2. WF must actually be present as expected — nothing to retire otherwise,
#    and a missing/unexpected symlink target could mean something else now
#    occupies that path.
if [[ ! -L "$wf_target" ]]; then
  printf '%s\n' "WF is not installed at $wf_target — nothing to retire." >&2
  exit 0
fi
if [[ "$(readlink -f -- "$wf_target")" != "$wf_expected" ]] \
  || ! owned_regular_file "$wf_expected" || [[ ! -x "$wf_expected" ]]; then
  printf 'Refusing retirement of an unexpected WF installation: %s\n' "$wf_target" >&2
  exit 1
fi
if [[ -e "$wf_data_root" && ! -O "$wf_data_root" ]]; then
  printf 'Refusing retirement of an unowned directory: %s\n' "$wf_data_root" >&2
  exit 1
fi

# 3. No live tmux session may still be owned by anything other than this
#    project — a session tagged for the old tool would be stranded by
#    removing its binary. @wf_owner is intentionally still named that (see
#    tmux.py) even after the WF -> ws rename; its VALUE is what matters.
if command -v tmux >/dev/null 2>&1 && tmux list-sessions >/dev/null 2>&1; then
  stray=0
  while IFS= read -r owner; do
    if [[ -n "$owner" && "$owner" != "workspace-session-manager" ]]; then
      stray=$((stray + 1))
    fi
  done < <(tmux list-sessions -F '#{@wf_owner}' 2>/dev/null || true)
  if (( stray > 0 )); then
    printf 'Refusing retirement: %d live tmux session(s) are not owned by workspace-session-manager.\n' "$stray" >&2
    exit 1
  fi
fi

if (( approve == 0 )); then
  printf 'Dry run; eligible for retirement:\n'
  printf '  %s (symlink)\n' "$wf_target"
  printf '  %s (install directory, not archived — a reproducible venv, not preserved source)\n' "$wf_data_root"
  printf '%s\n' 'No files changed. Re-run with --approve-retirement.'
  exit 0
fi

rm -- "$wf_target"
rm -rf -- "$wf_data_root"
printf 'Removed: %s\n' "$wf_target"
printf 'Removed: %s\n' "$wf_data_root"
printf '%s\n' 'No tmux session, ws installation, or classic-retirement archive was touched.'
