# Migration and Cutover

Cutover is intentionally separate from development. None of these commands should be run against the
operational installation until the owner has reviewed the generated plan and explicitly approved the
relevant step.

## Current phase

- Use `wf-dev` from the project virtual environment.
- Keep the current `WF`, home-directory launcher, alias, SSH hook, and tmux sessions unchanged.
- Use `wf-dev list --all` only for read-only diagnostics before adoption.
- Test creation and deletion only with sessions created by `wf-dev`.

## Approval checklist

Before cutover:

- All CI and local quality checks pass.
- The real-tmux integration tests pass.
- Manual Textual checks pass in SSH and Termius-sized terminals.
- Secret and privacy scans pass.
- A fresh backup of legacy source, state, logs, and shell profiles exists.
- The reviewed plan contains the expected exact tmux IDs and no unexpected sessions.
- Conflicting duplicate sidecars have been handled by configuring only the authoritative read root;
  operational sidecars themselves remain unchanged.
- The owner explicitly approves adoption and replacement of the user-local `WF` symlink.
- The owner separately approves any SSH login-hook change.

## Adoption preview

Preview reads tmux and legacy sidecars but does not write either one:

```bash
wf-dev migrate preview --all --output adoption-plan.json
chmod 600 adoption-plan.json
```

The terminal table redacts notes. The private JSON plan includes imported values, exact tmux IDs,
source locations, and SHA-256 hashes for every sidecar. Review it locally and do not commit it.

Immediately before cutover, validate the reviewed file without changing tmux or WF state:

```bash
wf-dev migrate validate adoption-plan.json
```

Validation rejects non-owner-only permissions, stale tmux IDs or sidecars, unsafe paths, malformed
content, and a plan ID that already has a migration journal. Its JSON mode reports IDs and warnings
but excludes imported notes. Apply repeats these checks under the migration lock.

To select sessions individually, repeat the exact-name option:

```bash
wf-dev migrate preview \
  --session claude-example \
  --session codex-example \
  --output adoption-plan.json
```

Apply rejects the plan if a tmux ID, source value, source hash, pre-existing metadata file, or owner
marker changed after preview.

## Approved install

The installer preserves the resolved pre-cutover command, installs the application in a user-local
virtual environment, validates and applies the reviewed plan, verifies that no legacy-managed
sessions remain unadopted, and then updates only `~/.local/bin/WF`:

```bash
scripts/install.sh \
  --approve-cutover \
  --migration-plan adoption-plan.json
```

An existing preservation copy is reused only when it is a user-owned, owner-only executable whose
SHA-256 matches the current `WF` command. The installer records that checksum in a private ownership
marker before switching the command symlink.

After adoption, any failure before the command symlink switches triggers rollback of that exact
migration. This includes the final check for legacy-managed sessions omitted from the reviewed plan.
If automatic rollback cannot complete because migration state changed concurrently, the installer
retains its failing exit status and prints the migration ID and recovery command path for inspection.
The complete installer transaction is protected by a nonblocking user-owned lock; a concurrent
cutover attempt exits before preserving a command, replacing the environment, or applying a plan.
The final command switch is an atomic rename of a private temporary symlink. Existing timestamped
command backups are never overwritten; a collision aborts cutover and rolls back adoption.

Adoption writes new WF metadata and a tmux user option. It does not attach, rename, restart, kill, or
send input to a session, and it never changes a legacy sidecar. Unrelated unmanaged tmux sessions may
remain; normal WF views hide them.

There is no classic command inside the new application. During the soak period, the installer-created
preservation copy remains at `~/.local/libexec/wf-classic`, and command rollback remains available
through the dedicated uninstall script.

## SSH hook

The SSH startup hook has a separate dry run and approval gate. The script only accepts the exact hook
recorded in the current-system assessment:

```bash
scripts/migrate-ssh-hook.py
scripts/migrate-ssh-hook.py --approve-cutover
```

The replacement respects both new and legacy disable/shown environment variables, invokes `WF` only
for an interactive SSH login outside tmux, and creates a timestamped profile backup. It does not
remove the existing lowercase compatibility alias.

## Rollback

First restore the pre-cutover command:

```bash
scripts/uninstall.sh --restore-classic
```

Command rollback requires the installer ownership marker and refuses a preservation copy whose
ownership, permissions, or checksum changed after cutover.
It atomically replaces the installed command symlink, so `WF` never passes through an intentionally
missing intermediate state.

Then use the retained installed command path to inspect journals and roll back adoption if the adopted
records have not changed:

```bash
~/.local/share/wf-session-manager/venv/bin/wf-dev migrate status
~/.local/share/wf-session-manager/venv/bin/wf-dev \
  migrate rollback MIGRATION_ID --approve
```

Rollback removes only records created by that migration and restores each previous tmux owner option.
It refuses changed records, changed owner markers, or changed tmux IDs. It never kills a session or
deletes legacy metadata.

Restore a migrated SSH profile from the timestamped `.bashrc.wf-pre-cutover.*` backup only with a
separate explicit decision.

## Retirement

After at least seven successful days, preview retirement of the installer-owned preservation copy:

```bash
scripts/retire-classic.sh
scripts/retire-classic.sh --approve-retirement
```

The script requires the new virtual-environment command to still be the active `WF`, requires the
installer's private ownership marker, verifies the original executable checksum, enforces the soak
period, and creates an owner-only compressed archive. Before deletion, it requires the archive to
contain only `wf-classic`, hashes the extracted payload against the installer marker, and self-checks a
basename-only archive checksum that remains valid if the archive directory is moved. A corrupt or
unexpected archive leaves the live preservation copy and marker intact. If rollback has made the
classic command active again, retirement is refused. The script does not remove the original launcher
source, metadata, logs, profiles, aliases, or any tmux session.
