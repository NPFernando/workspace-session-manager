# Testing

## Fast suite

```bash
pytest -m "not integration"
```

Unit and Textual pilot tests use temporary state, temporary legacy sidecars, and fake tmux backends.
They do not access the live tmux server or operational metadata.

## Real tmux

```bash
WF_RUN_TMUX_INTEGRATION=1 pytest -m integration -q --no-cov
```

The integration tests use `tmux -S` with a socket inside pytest's temporary directory. Cleanup
requires the generated socket path, session name, and exact tmux ID. One test covers managed
creation; the other removes its test owner marker, adopts the same exact ID, rolls adoption back, and
verifies that the tmux session remained alive throughout.

## Visual regression

`pytest-textual-snapshot` records deterministic SVG frames for wide, medium, narrow, empty, warning,
failure, usage-limit, diagnostics, create, validation-error, destructive-confirmation, dark, light,
monochrome, long-content, 50-session, and 200-session states. Reviewed before/after frames at
`160x45`, `120x35`, `100x30`, and `80x24` are stored under `docs/screenshots/`.

## Manual TUI matrix

Run `uv run textual run --dev wf_session_manager.tui:WFApp` only with a suitable service fixture, or
run `uv run wf-dev` against the managed inventory. Use `wf-dev list --all` for read-only diagnostics.

Check at least:

- `80x24`, `100x30`, `120x35`, and `160x45`
- SSH disconnect and reconnect after creating a disposable `wf-dev` session
- inside-tmux switching and outside-tmux attachment
- missing Claude, Codex, and Hermes commands
- exact-name delete mismatch and cancellation
- unmanaged-session hiding and mutation rejection
- private-file and stale adoption-plan rejection, read-only validation, and exact-batch rollback
- preservation checksum enforcement and refusal to retire an active classic command
- simulated installer success, pre-cutover adoption rollback, and rollback-failure reporting
- real advisory-lock contention between isolated installer processes
- atomic command-switch failure recovery and command-backup collision refusal
- retirement archive payload corruption and relocatable checksum verification
- sanitized pane output containing ANSI, IP, home path, and test token patterns
- zero-result searches and empty inventories with no hidden actionable selection
- create validation failure with values preserved and Create disabled
- Cancel-focused confirmation for every protected Manage operation
- dark, light, monochrome, `NO_COLOR`, and `WF_ASCII=1` rendering
- output and session-list scroll position preservation across background refresh
