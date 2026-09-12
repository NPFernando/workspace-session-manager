# Architecture v2 direction

This is an incremental target, not a big-bang rewrite.

```text
Textual TUI ─┐
             ├─> Application context / façade ─> domain rules ─> adapters
Typer CLI  ──┘                                      ├─ tmux
                                                     ├─ storage
                                                     ├─ notifier
                                                     └─ external health/federation
```

## Transitional module structure

The first extraction keeps imports compatible and lets the existing façade remain authoritative:

```text
src/workspace_session_manager/
  domain/                 # future state/events/errors; existing models remain source of truth first
  services/               # extracted cohesive services; façade delegates here over time
  adapters/               # future stable adapter import surface
  config/                 # future loader/migrations; current config.py remains compatibility layer
  cli/                    # future grouped commands; current cli.py remains root during transition
  tui/                    # future app/screens/widgets; current tui.py remains bootstrap during transition
  theme/                  # phase 1/2 implementation: data model, providers, manager, Textual bridge
  models.py               # compatibility import surface until domain extraction is complete
  service.py              # compatibility façade and ownership policy during extraction
  tui.py                  # compatibility bootstrap while screens move incrementally
```

## Ownership boundary

There is exactly one policy boundary for mutation. Extracted lifecycle code must call the existing
validated-record/exact-ID path, or a small shared ownership service that wraps it. Screens and CLI
commands may request an operation; they do not inspect a name and then mutate it themselves.

## Application context

The context is intentionally small and explicit:

```python
@dataclass(frozen=True)
class AppContext:
    paths: AppPaths
    config: AppConfig
    sessions: SessionService
    themes: ThemeManager
```

It is a composition object, not a service locator. The current `Runtime` remains compatible while
the context is introduced at feature boundaries.

## Extension points

- `ThemeProvider`: data-only palette sources with source/name discovery.
- `ToolAdapter` (future): availability, launch metadata, and capabilities; lifecycle remains in the
  session service.
- `HealthCheckProvider` (future): bounded check metadata and execution result.
- `Notifier` (existing direction): transport receives already-sanitized content.

Each interface should be introduced only when there are at least two real implementations or a
tested compatibility boundary. No arbitrary executable plugin loading is planned.

## Extraction order

1. Theme package and application context seam.
2. Shared TUI state/actions/help primitives.
3. Session query/lifecycle façade extraction.
4. Grouped CLI commands that call existing functions.
5. Screens/dialogs/widgets moved one cohesive workflow at a time.

The first incremental TUI extraction is `tui_shell.py`. It contains pure
dashboard-shell presentation helpers such as the contextual action rail. It
does not import Textual, services, tmux, or storage; `WsApp` supplies typed
state and remains responsible for orchestration.

Session-specific presentation follows the same boundary in
`tui_session_view.py`: tool/runtime styles, human-readable state labels, task
summaries, and status badges are pure functions. Session selection, refresh,
and mutation remain in `WsApp` and `SessionService`.

The session pane's bounded rendering policy is isolated in
`tui_session_list.py`. It keeps the selected `(name, session_id)` visible when
the SSH-oriented render cap is reached and reports overflow explicitly; it
does not own widget mutation or session operations.

The inspector's overview and status row construction is isolated in
`tui_session_details.py`. It returns immutable row data and applies the
medium-width reduction policy without loading sessions, reading logs, or
performing mutations.

Warning copy and bounded recent-timeline formatting are isolated in
`tui_activity_view.py`. Preview acquisition and sanitization remain owned by
the existing service/worker path; the extracted helper only formats already
safe data for display.

Output summary/raw formatting and preview metadata are isolated in
`tui_output_view.py`. It accepts bounded text and notice data, returning a
renderable value without reading panes, files, or logs.

The selected-session identity/header composition is isolated in
`tui_identity_view.py`. Responsive truncation and semantic status styling are
pure presentation decisions; selection, refresh, and action policy remain in
the application.

Contextual inspector-button state is isolated in `tui_actions.py`. It returns
enabled/disabled flags, pin labels, and actionable disabled explanations; it
does not invoke lifecycle operations or bypass service approval gates.

Dashboard empty and unavailable-state copy is isolated in
`tui_empty_state.py`. It distinguishes first-run, filtered, attention-scan,
and disconnected-runtime states and keeps the primary recovery action visible
without owning widget state or tmux access.

Dashboard count, filter, performance, and connection-status formatting is
isolated in `workspace_header_view.py`. The app supplies measured state and
continues to own responsive layout and semantic theme styling.

The session inventory toolbar and contextual five-item shortcut rail are
isolated in `workspace_toolbar_view.py`. Interaction-mode transitions remain
owned by `WsApp`; the helper only renders discoverability text.

Background-job and critical-health row formatting is isolated in
`tui_status_rows.py`. It formats active work, bounded recent history, and
actionable critical checks; workers, generation guards, and remediation remain
outside the presentation layer.

Refresh failure and stale-selection feedback is isolated in
`tui_refresh_view.py`. It gives retry/return-to-list guidance without deciding
whether a result is current; generation and identity checks remain in
`WsApp`.

Interaction-mode presentation is isolated in `tui_interaction.py`. It derives
semantic CSS state for normal, search, and overlay modes without importing
Textual. Mode transitions, screen-stack operations, focus restoration, and
worker lifecycle remain owned by `WsApp`.

Command-palette query normalization and semantic alias/typo scoring are
isolated in `tui_palette.py`. Textual still owns fuzzy matching, highlighting,
and callback execution; the provider remains the owner of session-aware command
availability and action wiring.
