# Testing

## Fast suite

```bash
pytest -m "not integration"
```

Unit and Textual pilot tests use temporary state and fake tmux backends. They do not access the live
tmux server or classic metadata.

## Real tmux

```bash
WF_RUN_TMUX_INTEGRATION=1 pytest -m integration -q --no-cov
```

The integration test creates a random `wf-it-...` session. Cleanup checks both the generated tmux ID
and the `@wf_owner` option before deleting it. A pre-existing name collision causes the test to abort,
not to reuse or delete that session.

## Manual TUI matrix

Run `uv run textual run --dev wf_session_manager.tui:WFApp` only with a suitable service fixture, or
run `uv run wf-dev` against the live read-only session inventory.

Check at least:

- `80x24`, `100x28`, and `120x36`
- SSH disconnect and reconnect after creating a disposable `wf-dev` session
- inside-tmux switching and outside-tmux attachment
- missing Claude, Codex, and Hermes commands
- exact-name delete mismatch and cancellation
- classic-session mutation rejection
- sanitized pane output containing ANSI, IP, home path, and test token patterns
