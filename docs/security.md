# Security Model

## Threats addressed

- Shell injection through names, paths, or tmux targets
- Accidental modification of pre-existing tmux sessions
- Name reuse granting authority through stale metadata
- Symlink attacks against metadata and classic sidecars
- Partial creation leaving unmanaged sessions behind
- Credentials or terminal control sequences appearing in previews
- Accidental publication of local paths, logs, or secrets

tmux commands are constructed as argument arrays. Managed names use a strict lowercase allowlist, and
tmux targets use exact-name syntax. TOML configuration is parsed, not sourced.

## Trust boundaries

The user's configuration and installed agent commands are trusted local inputs. Agent processes and
their pane output may be untrusted. Pane output is sanitized before Textual or Rich renders it.

Classic metadata is read only, limited to small regular non-symlink files, and is never copied into
the new state namespace automatically.

## Destructive operations

Rename, metadata edits, pinning, and deletion require ownership proof. CLI deletion requires typing
the exact session name unless `--yes` is supplied. The TUI always requires exact-name confirmation.
WF never sends `sudo`, never changes shell profiles, and has no system-wide install path.

## Reporting

Do not open a public issue for a vulnerability. Follow [SECURITY.md](../SECURITY.md) to report it
privately.

