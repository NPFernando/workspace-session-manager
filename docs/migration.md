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
virtual environment, applies the reviewed plan, verifies that no legacy-managed sessions remain
unadopted, and then updates only `~/.local/bin/WF`:

```bash
scripts/install.sh \
  --approve-cutover \
  --migration-plan adoption-plan.json
```

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

The script requires the installer's ownership marker, verifies the original executable checksum,
enforces the soak period, creates an owner-only compressed archive and checksum, and then removes only
that preservation copy and marker. It does not remove the original launcher source, metadata, logs,
profiles, aliases, or any tmux session.
