# Workspace Session Manager v2 assessment

Assessment date: 2026-09-05
Branch: `rebuild/user-developer-experience-v2`

This assessment is based on the implementation, tests, Textual recordings, package metadata, and
the current VM checkout. It is not based on filenames alone. The working tree already contained
an approved UI/CI change set before this rebuild branch was created; those changes are preserved.

## Baseline evidence

- Python package: `workspace-session-manager` 0.2.0, Python 3.11+.
- Runtime stack: Textual, Typer, Rich, Pydantic, platformdirs, tmux.
- Main implementation sizes: `tui.py` 10,723 lines, `service.py` 4,137 lines, `cli.py` 3,396 lines.
- Test sizes: `test_tui.py` 4,503 lines, `test_service.py` 2,063 lines, `test_cli.py` 1,669 lines,
  plus model, storage, migration, security-adjacent, integration, and snapshot coverage.
- Collected tests: 578.
- Package wheel and sdist build successfully.
- The package is installed editable in the VM, so new launches resolve this checkout.
- Existing Textual recordings and SVG snapshots cover 80, 100, 120, and 160 column layouts,
  narrow details, Logs, Attention, forms, confirmation, themes, ASCII, monochrome, and reduced motion.

## User flows

`ws` opens the primary Textual dashboard. The dashboard currently combines inventory, grouping,
search, filtering, Attention, a selected-session inspector, Logs, Manage, forms, diagnostics,
health, federation, dependency, project, policy, and interface-control workflows. The CLI also
supports direct lifecycle operations, presets, templates, search, health, federation, backups,
archives, automation, approvals, migration, and operator profiles.

The normal path is sound but dense: a first-time user encounters a large action rail and many
keyboard bindings before learning that the common path is select, Enter, `c`, `/`, `p`, and `?`.
The existing command palette and contextual Manage flow are the right discoverability foundations.

## Safety and persistence contracts

The ownership boundary is in `SessionService` and `TmuxBackend`: mutable operations require a
validated ws metadata record, owner marker, exact live tmux session ID, and expected-ID propagation
to the final adapter call. Name reuse alone never grants ownership. Migration is preview/validate/apply
with stale-plan and journal checks; it never silently adopts or changes arbitrary sessions.

`MetadataStore` and related stores use XDG paths, owner-only permissions, locking, schema validation,
temporary files, fsync, and atomic replacement. Pane/log output is sanitized, redacted, and bounded.
Subprocesses are argument arrays; no lifecycle path relies on `shell=True`.

These contracts are release blockers for refactors. They belong behind application/service APIs but
must remain centralized, not reimplemented in screens, CLI commands, or future adapters.

## Capability map

| Area | Current implementation | Rebuild direction |
| --- | --- | --- |
| Domain | `models.py`, enums, validators | Preserve models; gradually separate state/events/errors |
| Lifecycle | `SessionService` | Extract query/lifecycle/log/search boundaries around one ownership gate |
| tmux | `tmux.py` | Preserve exact-ID adapter and isolated test backend |
| Storage | `store.py`, `paths.py` | Preserve atomic/locked stores; expose typed repositories |
| Health | `health.py` plus service/TUI orchestration | Provider registry with bounded workers and cached results |
| Migration | `migration.py` | Preserve plan/journal/rollback rules; expose application service |
| CLI | `cli.py` root plus Typer sub-apps | Add grouped namespaces as compatibility aliases to existing functions |
| TUI | `tui.py`, `wf.tcss` | Extract shell/state/theme/widgets incrementally |
| Themes | palette definitions in `tui.py` | New data-only `theme` package and providers |
| Tests | broad colocated suite and snapshots | Add focused theme/context/CLI compatibility tests without moving everything at once |

## Findings by category

### UX

- The dashboard is powerful but exposes too much of the feature surface at once.
- Contextual actions already exist, but the default rail and help need stronger progressive disclosure.
- Create is already validated and safer than a simple form, but it should be a short Essentials →
  Task → Review flow with Advanced controls hidden initially.
- Status values are modeled separately, but the presentation needs a consistent human-readable
  Runtime / Task / Agent / Input / Warning grouping.
- Empty states and warnings should consistently include an explanation and next action.

### Architecture and developer experience

- `tui.py` is the primary monolith: screens, widgets, state, theme construction, command routing,
  asynchronous workers, formatters, and presentation helpers are interleaved.
- `service.py` is a second large boundary containing lifecycle, search, logs, federation, archive,
  policy, approval, and automation behavior. It is cohesive enough to preserve as a façade while
  extracting narrow services behind it.
- `cli.py` has existing Typer sub-apps, which makes grouped CLI namespaces feasible without a rewrite.
- Theme definitions are embedded in TUI code and cannot currently be reused by CLI diagnostics or
  custom/Omarchy sources.
- The project lacks `AGENTS.md` and the requested rebuild decision records.

### Testing and release

- Behavior and layout coverage is unusually strong for the current feature set.
- The default pytest coverage gate is 65%; collection-only is not a valid coverage measurement.
- Package build succeeds and includes the TCSS package data; a clean-install smoke test should be
  added before extracting theme resources.
- Snapshot changes are useful evidence but must remain secondary to behavior and safety tests.

### Performance

- TUI inventory, health, Attention, Logs, and federation already use workers/generation checks in
  important paths. Future extraction must retain stale-result rejection and bounded reads.
- The large module size increases review and import coupling more than it currently indicates a
  single event-loop performance defect.

### Security and compatibility

- Existing tmux ownership, output sanitization, storage permissions, and migration rollback are
  strong invariants.
- Custom themes must be parsed as data only. No theme provider may import or execute user files.
- Existing flat CLI commands, JSON output, metadata schema, config defaults, and unmanaged sessions
  must remain compatible during the rebuild.

## Baseline known items

- The current branch includes pre-existing uncommitted UI/CI/release-checklist work; it is not
  reclassified as part of this rebuild.
- The prior VM environment can set `NO_COLOR` and a low-capability `TERM`; tests that assert motion
  must use an explicit color-capable test environment.
- Open PR/issue listing was empty through the available GitHub CLI query at assessment time.
