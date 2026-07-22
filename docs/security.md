# Security Model

## Threats addressed

- Shell injection through names, paths, or tmux targets
- Accidental modification of pre-existing tmux sessions
- Name reuse granting authority through stale metadata
- Symlink attacks against metadata, migration plans, journals, and legacy sidecars
- Partial creation leaving unmanaged sessions behind
- Credentials or terminal control sequences appearing in previews
- Accidental publication of local paths, logs, or secrets

tmux commands are constructed as argument arrays. Managed names use a strict lowercase allowlist, and
discovery uses exact-name syntax. Once ownership is validated, sensitive operations target the
verified tmux session ID. TOML configuration is parsed, not sourced.

## Trust boundaries

The user's configuration and installed agent commands are trusted local inputs. Agent processes and
their pane output may be untrusted. Pane output is sanitized before Textual or Rich renders it.

Legacy metadata is read only and limited to small regular non-symlink files. Adoption is never
automatic: preview snapshots source hashes and exact tmux IDs, while apply requires an unchanged plan
and explicit approval. Plans and journals may contain imported notes and are accepted only from
owner-only files with no symlink path component.

## Destructive operations

Rename, metadata edits, pinning, logging, restart, stop, and deletion require ownership proof. CLI
deletion requires typing the exact session name unless `--yes` is supplied. The TUI exposes stop,
metadata removal, log deletion, and complete deletion only through Manage, then requires a separate
confirmation whose default focus is Cancel. Complete deletion also requires the exact session name.
ws never sends `sudo` and has no system-wide install path. The standalone SSH-hook migration script
defaults to a dry run, requires a literal match with the assessed hook, creates a backup, and changes
the profile only with its separate approval flag.

The classic preservation copy and its ownership marker are user-owned and owner-only. Restore and
retirement verify the recorded SHA-256 before acting, and retirement also proves that the new ws
command remains active so it cannot remove a classic executable currently serving as the rollback.
Before that command switch, installer failures roll back only the exact migration applied by the same
installer invocation. A private process lock prevents concurrent installer invocations from racing
over the preserved command, virtual environment, ownership marker, or command symlink.
Command switches use same-directory temporary symlinks and atomic rename, while pre-cutover backups
refuse existing destinations instead of replacing them.

## Pane output

Preview and log captures use exact tmux IDs. Sanitization removes CSI, OSC, DCS, clipboard, title,
and control sequences before Rich or Textual sees the content, then redacts common credentials, IP
addresses, and the local home path. Rendered results are bounded by configured line and UTF-8 byte
limits. Optional persistent logging is disabled or enabled explicitly per managed session and writes
only through ws's owner-only, size-limited sanitizer process. ws does not infer input-required state
from arbitrary captured output; narrowly recognized operational warnings such as usage limits are
shown as possible activity notices without changing task metadata.

The compatibility `--classic` bridge executes only a regular, owner-owned executable under the
owner-only `~/.local/libexec` directory. It is not exposed as a dashboard action.

Classic retirement verifies both the archive topology and the extracted executable hash before
deleting the preservation copy. The archive checksum references only its basename and is verified at
creation time; archive corruption never authorizes deletion.

## Reporting

Do not open a public issue for a vulnerability. Follow [SECURITY.md](../SECURITY.md) to report it
privately.
