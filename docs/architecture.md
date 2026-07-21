# Architecture

## Boundaries

WF separates five concerns:

1. `TmuxBackend` performs small, exact-target tmux operations using subprocess argument arrays.
2. `MetadataStore` persists validated WF-owned JSON records with locking and atomic replacement.
3. `SessionService` applies ownership and lifecycle policy.
4. `MigrationManager` previews, snapshots, adopts, journals, and rolls back legacy sessions.
5. Typer and Textual are presentation layers over the same service.

The legacy sidecar adapter has no write methods. Unmanaged sessions are hidden from normal views.
`list --all` exposes them for diagnostics, while `migrate preview` can build a private adoption plan.

## Interaction modes

The Textual dashboard allows one active interaction mode: Normal, Search, Filter, Form, Command
Palette, Manage, or Confirmation. Entering an overlay captures the current query, filters, selected
session identity, highlighted option, focus, and scroll position. Cancel restores that context before
another command may run. App-level bindings are unavailable while a modal or full-screen workflow is
active, so keystrokes cannot open conflicting screens or leak into the dashboard.

At 80-99 columns, the session list and inspector are two views of Normal mode rather than separate
screens. The dashboard reuses one inspector tree, records inspector and output scroll positions by
exact session identity, and restores them after modal and Logs workflows. Search and Filter return to
the list before activation. A missing, replaced, or newly filtered session closes the detail view with
an actionable warning instead of retaining a stale target.

Manage is a searchable action browser with separate General, Runtime, and Danger categories.
Identity and organization, task text, and task/input status are edited in separate forms. Manage
callbacks retain the exact name and tmux session ID captured when the workflow opened, so a
background refresh or selection change cannot redirect an operation. Canceling a nested form or
confirmation reopens Manage with its query, scroll position, and originating action restored.

Attention is a temporary filtered dashboard view rather than a separate persistence model. Entering
it captures the same dashboard context as other mode transitions, and `Esc` restores that context.
Its filter contains sessions with known runtime, task, input, or agent alerts; sessions are never
duplicated into a second dashboard group.

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
- an exact match between the record's tmux ID and the live tmux ID; and
- `@wf_owner = "wf-session-manager"` on the live tmux session.

This protects legacy sessions, manually created sessions, stale metadata, and names reused after a
session exits.

After validation, WF carries the expected tmux ID into the backend operation and targets `$session_id`
for attach, pane capture, rename, option changes, logging, restart, stop, and deletion. It does not
validate an ID and then return to the reusable name for the final command.

## Adoption

Preview records exact tmux IDs, normalized legacy values, every source path, and SHA-256 hashes for
the source sidecars. Apply rereads the live inventory and sidecars and rejects a stale snapshot. It
then adds ownership metadata and the tmux marker without attaching, renaming, restarting, or killing
the session. A private journal supports batch rollback while records remain unchanged.

`migrate validate` exposes the same snapshot and prior-journal checks without writing state. Apply
repeats validation while holding the migration lock, so a successful preflight is informative rather
than an authority that can become stale.

The cutover installer records the validated plan ID before apply. An EXIT handler rolls back that
exact migration if any later pre-cutover gate fails; the handler is disabled only after the command
symlink switches successfully. A failed automatic rollback is reported for manual recovery and never
hidden by the original installer error. A separate owner-only, nonblocking `flock` covers the complete
installer transaction so preservation, environment installation, adoption, and command switching
cannot race another cutover invocation.

Install and command rollback create a private temporary symlink beside `~/.local/bin/WF` and use a
same-filesystem rename for the final replacement. The old command therefore remains available until
the new link is complete. Timestamped pre-cutover backups use no-replace semantics; a collision aborts
and enters the same adoption-recovery path.

## Persistence

State directories use mode `0700`; files and locks use `0600`. Writes occur through a temporary file
in the destination directory, followed by `fsync` and atomic `os.replace`. Linux `flock` serializes
writers.

Schema-v2 metadata separates user-assigned task and input states. Schema-v1 `active`, `done`, and
`paused` values are normalized to `in_progress`, `completed`, and `waiting` when read. A record is
written as schema v2 only when it is created or explicitly edited.

Runtime state is read from tmux. Attached-client count distinguishes attached and detached sessions;
dead-pane status distinguishes stopped and failed sessions. Session activity timestamps come from
tmux and are combined conservatively with WF's last-attach timestamp.

## Attach behavior

Outside tmux, WF runs `tmux attach-session`. Inside tmux, it runs `tmux switch-client`. tmux owns the
long-running process, so closing SSH does not terminate the session.

## Output and logging

Pane previews are captured on demand. ANSI, OSC, DCS, clipboard, title, and control sequences are
stripped; common token/password forms are redacted; local home paths are shortened; and output is
bounded by both lines and UTF-8 bytes after sanitization. Optional persistent logging uses tmux
`pipe-pane` with an argument-array command that invokes WF's sanitizer and writes owner-only rotating
files. Logging state is a tmux option and is never enabled for an unmanaged session.

The Logs workspace makes its source explicit. Live reads capture the exact verified tmux session ID;
Saved reads accept only the expected owner-only regular log file. Active sessions default to Live,
while stopped sessions default to Saved. The service keeps its original automatic saved-first policy
when no source is requested, preserving compatibility for CLI callers. TUI polling runs in one
exclusive worker, rejects stale generations and changed session identities, and pauses the dashboard
timer while Logs is open. Paused and find modes stop automatic reads and preserve a separate viewport
for each source.

Input-required status remains explicit metadata and is never inferred from arbitrary pane output.
Conservative activity detectors may surface recognized usage-limit text in the inspector without
changing runtime, task, or input state.

## Attention scanning

The dashboard checks eligible non-shell sessions in a single exclusive background worker. Every pane
read is bounded to 20 sanitized lines and 8 KiB and carries the inventory snapshot's exact tmux ID;
a reused name cannot redirect a capture. Results are accepted only when the worker generation,
session identity, and notice revision still match the current dashboard state.

Each refresh inspects at most `attention_scan_budget` sessions. Half of a multi-session batch is
reserved for attached sessions and sessions with known warnings, while the remaining capacity uses
least-recently-scanned order across the full eligible inventory. This provides prompt rechecks
without starving detached sessions. A failed read retains the prior known alert, reports the scan as
delayed, and remains eligible for retry.

Startup establishes a complete alert baseline without notifications. Later scans aggregate newly
discovered warnings into one notification per batch. Pane-derived alerts and scan timestamps remain
process-local; WF does not infer or persist task/input metadata from output.
