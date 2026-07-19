# Architecture

## Boundaries

WF separates four concerns:

1. `TmuxBackend` performs small, exact-target tmux operations using subprocess argument arrays.
2. `MetadataStore` persists validated WF-owned JSON records with locking and atomic replacement.
3. `SessionService` applies ownership, rollback, lifecycle, and legacy-read policies.
4. Typer and Textual are presentation layers over the same service.

The classic sidecar adapter has no write methods. A session discovered from classic metadata is a
read-only `SessionView` unless a future, explicit import operation creates a new ownership record.
No import command exists in version 0.1.0.

## Session creation

WF validates the name, directory, tool profile, and executable before calling tmux. tmux starts an
interactive login shell in detached mode. For agent sessions, WF sends a shell-quoted command to that
new shell. The shell remains after the agent exits, preserving diagnostics and a useful workspace.

After creation, WF writes a tmux user option and an owner-only metadata record. If tmux setup or the
metadata write fails, WF removes only the session it just created, after checking its tmux ID.

## Ownership

A session mutation requires all of the following:

- a live tmux session with the exact requested name;
- a valid JSON record in the new XDG namespace;
- `owner = "wf-session-manager"` in that validated record; and
- an exact match between the record's tmux ID and the live tmux ID.

This protects classic sessions, manually created sessions, stale metadata, and names reused after a
session exits.

## Persistence

State directories use mode `0700`; files and locks use `0600`. Writes occur through a temporary file
in the destination directory, followed by `fsync` and atomic `os.replace`. Linux `flock` serializes
writers.

## Attach behavior

Outside tmux, WF runs `tmux attach-session`. Inside tmux, it runs `tmux switch-client`. tmux owns the
long-running process, so closing SSH does not terminate the session.

## Preview privacy

Pane previews are captured on demand and never persisted by the new application. ANSI and control
sequences are stripped, common token/password forms are redacted, local home paths are shortened,
and output is line-bounded before rendering.

