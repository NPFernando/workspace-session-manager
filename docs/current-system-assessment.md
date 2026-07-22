# Current System Assessment

Assessment date: 2026-07-19

This document records the pre-development inspection of the operational ws launcher. It is
deliberately privacy-safe: session task text, project names, pane output, credentials, and log
contents are excluded.

## Command and source layout

- The active `ws` command is a user-local symbolic link to a Bash script in the home directory.
- A separate release-style directory contains a byte-identical copy of that script.
- The implementation reports version `0.1.0-dev` and uses tmux as its persistence backend.
- The SSH login hook invokes the home-directory script directly, not the `ws` symlink.
- The shell also defines a lowercase compatibility alias for the same script.
- No `ws-dev` command existed before this repository was created.

The source path and symlink are intentionally not changed by this project.

## Runtime state

- Seven live tmux sessions were present during inspection.
- At least one session was attached and the others were detached.
- Observed naming follows `<tool>-<purpose>` for Claude and Codex sessions.
- The implementation also supports the `hermes-` prefix and unprefixed shell session names.
- Exact tmux targets are used by the classic launcher for most lifecycle operations.

No session was attached, renamed, imported, restarted, killed, or otherwise changed during the
assessment.

## Metadata and logs

The classic system uses both legacy home-directory storage and XDG-compatible storage:

- Config: `~/.config/wf/`
- Cache: `~/.cache/wf/`
- State: `~/.local/state/wf/`
- Current session sidecars: `~/.local/state/wf/sessions/`
- Legacy session sidecars: `~/.ws-session-notes/`
- Current logs: `~/.local/state/wf/logs/`
- Legacy logs: `~/.ws-session-logs/`

Per-session sidecars use these suffixes where applicable:

- `.tool`
- `.cwd`
- `.project`
- `.note`
- `.state`
- `.last`
- `.tags`
- `.pinned`

Shared files include action history, project cache, favorites, search data, templates, macros, and
cached health information. Existing metadata has already been copied once from the legacy directory
to XDG state by the classic launcher. The new application treats all of these paths as read-only
until an explicit migration is approved.

## Tool conventions

- Claude launches as `claude`.
- Codex launches as `codex`.
- Hermes launches as `hermes chat`.
- Agent sessions begin in an interactive shell so the tmux session remains available if the agent
  process exits.

## Shell integration

Interactive SSH logins currently auto-open the classic workspace menu when tmux is available and
the terminal meets guard conditions. The hook avoids opening inside tmux and honors environment
variables that disable the menu or choose its initial action.

This repository does not modify that hook, shell aliases, `PATH`, systemd, or global binaries.

## Backup

A non-destructive archive was created before project implementation:

- Location: `~/backups/wf-session-manager/pre-migration-20260719-123344/legacy-wf.tar.gz`
- Mode: owner-readable and owner-writable only
- SHA-256: `4493ab0f20b9cb5ebc351028eced5b7d5e8840e1143a3f8e640674fd2bb8a6d5`

The archive includes the launcher source, release tree, command symlink, ws configuration/cache/state,
legacy sidecars/logs, and copies of the relevant user shell profiles. It must not be committed or
published.

## Migration constraints

Development uses the `workspace-session-manager` XDG namespace and the `ws-dev` command. Existing unmanaged
sessions are hidden by default and available through `ws-dev list --all` for diagnostics. A tmux
session is mutable only when a new ws metadata record, the original tmux session ID, and the tmux
owner marker prove ownership. Name matching alone never grants ownership.

Cutover requires explicit approval, a fresh backup, a preserved classic executable, and a manual
change to the SSH login hook. Until then, the operational launcher remains authoritative.
