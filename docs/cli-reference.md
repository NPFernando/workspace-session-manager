# CLI reference

`ws` keeps the original flat commands for compatibility and adds grouped
commands for new scripts and users. Both forms call the same application
services; the grouped form is the preferred documentation path.

## Common commands

```bash
ws                         # open the Textual application
ws setup                   # create or repair minimal configuration
ws quickstart              # guided first session setup
ws doctor                  # dependency, storage, and theme diagnostics
```

## Sessions

```bash
ws session list
ws session create
ws session inspect NAME
ws session attach NAME
ws session stop NAME
ws session delete NAME
```

Compatibility aliases remain available: `ws list`, `ws create`, `ws inspect`,
`ws attach`, `ws stop`, and `ws delete`.

Existing JSON output is preserved. Commands that support machine-readable
output accept `--json`; new envelopes use `schema_version`, `success`,
`data`, and `error` without changing legacy command output unexpectedly.

## Themes

```bash
ws theme list [--json]
ws theme current [--json]
ws theme set NAME
ws theme preview NAME
ws theme doctor
```

`auto` follows the documented precedence in [Themes](themes.md). Custom
palettes are data-only TOML files under
`~/.config/workspace-session-manager/themes/<name>/colors.toml`.

## Configuration and diagnostics

```bash
ws health
ws doctor
ws setup
ws quickstart
```

Configuration inspection currently remains part of the existing command
surface; use `ws --help` to see the installed configuration commands. The
remaining advanced domains—logs, federation, migration, backup, and
automation—continue to use their existing commands while grouped interfaces
are introduced incrementally. Run `ws --help` or `ws <group> --help` for the
installed command surface.

## Exit status

Existing command-specific exit behavior remains authoritative for compatibility.
New grouped commands are being normalized toward:

```text
0 success
1 operation failed
2 invalid arguments or configuration
3 resource not found
4 ownership or safety rejection
5 dependency unavailable
```

Scripts should use `--json` and inspect `success`/`error` until the remaining
legacy commands are migrated to the common envelope.
