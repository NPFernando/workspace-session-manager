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
for attach, pane capture, rename, option changes, and deletion. It does not validate an ID and then
return to the reusable name for the final command.

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
