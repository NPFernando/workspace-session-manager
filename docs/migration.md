# Migration and Cutover

Cutover is intentionally separate from installation and development.

## Current phase

- Use `wf-dev` from the project virtual environment.
- Keep the current `WF`, home-directory launcher, aliases, and SSH hook unchanged.
- Treat classic sessions and metadata as read only.
- Test creation and deletion only with sessions created by `wf-dev`.

## Approval checklist

Before cutover:

- All CI and local quality checks pass.
- The real-tmux integration test passes.
- Manual Textual checks pass in SSH and Termius-sized terminals.
- Secret and privacy scans pass.
- A fresh backup of the classic source, state, logs, and shell profiles exists.
- The preserved classic executable runs independently.
- The owner explicitly approves replacement of the user-local `WF` symlink.
- The owner separately approves any change to the SSH login hook.

## Approved install

The included installer refuses to act without an explicit gate:

```bash
scripts/install.sh --approve-cutover
```

It creates a user-local virtual environment, preserves the resolved current `WF` implementation as
`~/.local/libexec/wf-classic`, and then updates only `~/.local/bin/WF`. It does not edit shell profiles
or kill, rename, import, or alter tmux sessions.

After cutover:

```bash
WF --classic
WF classic doctor
```

The first opens the preserved fzf UI. The second forwards a command to it.

## Rollback

```bash
scripts/uninstall.sh --restore-classic
```

Rollback removes only an installer-owned symlink and restores the preserved classic executable as
the user-local `WF` command. New-format metadata remains intact for diagnosis.

## Metadata migration

Version 0.1.0 does not import or adopt classic sessions. A future importer must be previewable,
per-session, reversible, and explicitly approved. It must record live tmux IDs at import time and
must never infer ownership from names alone.

