# Compatibility contract

## Preserved immediately

- Existing managed sessions, metadata, notes, tags, project mappings, logging, backups, migration
  journals, and XDG paths.
- Exact tmux session identity and owner-marker checks for every mutation.
- Unmanaged-session hiding and explicit migration-only adoption.
- Existing flat CLI commands and their current JSON output unless a separately versioned envelope is
  introduced.
- Existing config keys and tool profile behavior, including the Codex legacy-alias repair.
- ASCII, `NO_COLOR`, reduced motion, narrow layouts, and current Textual recordings.

## Additive changes

- New grouped CLI commands call the same underlying implementation as old commands.
- `ws theme` is additive; `interface.theme` accepts `auto` and named data-only themes while old
  preference files remain readable.
- New theme files are read-only data under the user config directory and are never executed.

## Migration policy

Schema changes require a version bump, deterministic read migration, rollback implications in docs,
and isolated tests. Theme configuration has no destructive migration: missing/invalid themes fall
back to a built-in palette with an actionable diagnostic.

## Deprecation policy

No existing command is removed in the rebuild branch. When grouped aliases are stable, help text may
mark the flat spelling as compatibility syntax, but it remains functional for at least one release
cycle and is never silently redirected to a different target.
