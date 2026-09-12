# Development guide

The project uses Python, Textual, Typer, Rich, Pydantic, platformdirs, and tmux. Keep the runtime
small and avoid adding a framework for dependency injection or plugins.

## Fast checks

```bash
uv sync --locked --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy
env -u NO_COLOR TERM=xterm-256color uv run pytest -m 'not integration'
uv build
```

Run integration tests only with the isolated tmux fixture:

```bash
WS_RUN_TMUX_INTEGRATION=1 uv run pytest -m integration -q --no-cov
```

## Safe changes

Lifecycle operations must flow through `SessionService` and expected-ID tmux adapter methods. TUI
and CLI layers orchestrate; they do not implement ownership checks. Use fake backends for TUI tests,
temporary XDG roots for storage tests, and private tmux sockets for integration tests.

New theme providers belong under `src/workspace_session_manager/theme/providers/`. They may read
bounded data files but must not execute user content. New grouped CLI commands should call existing
service functions so flat command compatibility remains intact.
