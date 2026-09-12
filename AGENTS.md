# Agent guidance

## Architecture

`SessionService` is the current lifecycle façade. `TmuxBackend` is the exact-target adapter and
`MetadataStore` is the locked/atomic persistence boundary. `tui.py` and `cli.py` are currently large
compatibility modules; extract cohesive workflows incrementally rather than duplicating behavior.

## Safety invariants

- Never mutate a tmux session by name alone.
- Require ws metadata, owner marker, and exact tmux ID for mutations.
- Never adopt, rename, kill, attach to, or write legacy sessions during tests unless an isolated
  migration/integration fixture explicitly owns them.
- Preserve argument-array subprocess calls; do not use `shell=True`.
- Preserve ANSI/OSC/control sanitization, redaction, output bounds, atomic writes, locks, and owner-only
  permissions.
- Theme/config files are data. Never import or execute them.

## Development

```bash
uv sync --locked --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy
env -u NO_COLOR TERM=xterm-256color uv run pytest -m 'not integration'
WS_RUN_TMUX_INTEGRATION=1 uv run pytest -m integration -q --no-cov
uv build
```

Use fake backends for TUI tests and isolated tmux sockets for integration. Run `git diff --check`
before handoff. Snapshot changes must be intentional and reviewed.

## Where changes belong

- New theme parsing/providers: `src/workspace_session_manager/theme/`.
- New lifecycle policy: service/domain layer, not a widget event handler.
- New tmux operations: `tmux.py`, with expected-ID support and tests.
- New health checks: health provider boundary and bounded worker tests.
- New grouped CLI commands: compatibility command modules that call existing service APIs.
- New TUI presentation: extracted `tui/` modules once the relevant workflow seam exists.
