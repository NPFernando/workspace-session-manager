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
tmux targets use exact-name syntax. TOML configuration is parsed, not sourced.

## Trust boundaries

The user's configuration and installed agent commands are trusted local inputs. Agent processes and
their pane output may be untrusted. Pane output is sanitized before Textual or Rich renders it.

Legacy metadata is read only and limited to small regular non-symlink files. Adoption is never
automatic: preview snapshots source hashes and exact tmux IDs, while apply requires an unchanged plan
and explicit approval.

## Destructive operations

Rename, metadata edits, pinning, and deletion require ownership proof. CLI deletion requires typing
the exact session name unless `--yes` is supplied. The TUI always requires exact-name confirmation.
WF never sends `sudo` and has no system-wide install path. The standalone SSH-hook migration script
defaults to a dry run, requires a literal match with the assessed hook, creates a backup, and changes
the profile only with its separate approval flag.

## Reporting

Do not open a public issue for a vulnerability. Follow [SECURITY.md](../SECURITY.md) to report it
privately.
