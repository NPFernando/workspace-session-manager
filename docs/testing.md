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
failure, usage-limit, diagnostics, create, create-advanced, validation-error, filter, palette,
responsive Manage, filtered Manage, disabled Manage actions, identity and status forms,
destructive-confirmation, responsive Logs, Live and Saved sources, Logs find/pause/warning/error/empty
states, in-place narrow details at 80 and 99 columns, narrow detail warning/failure/long-content,
dark, light, monochrome, ASCII, reduced-motion, diagnostics-running, long-content, 50-session, and
200-session states.
Reviewed before/after frames at
`160x45`, `120x35`, `100x30`, and `80x24` are stored under `docs/screenshots/`.
Fake-backend terminal recordings and replay instructions are stored under `docs/recordings/`; they
never connect to the live tmux server or production metadata.

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
- latest-value validation after rapid invalid-to-valid name changes
- Search suspension and exact focus/query/scroll restoration around the Create form
- exclusive Search, Filter, Palette, Manage, Form, and Confirmation mode transitions
- shortcut suppression while overlays are active and command dispatch after palette restoration
- identity-bound Manage operations and confirmation cancellation back to the originating action
- Manage local search plus highlighted-action and scroll restoration across nested edit forms
- final session-ID normalization, collision checks, prefix opt-out, and no duplicate tool prefix
- multiline task entry, advanced-option focus restoration, and incremental new-row insertion
- actionable startup failure with rollback verification, retry, details, and metadata cleanup states
- usage-limit propagation across header count, selected row, Activity, agent state, and Summary/Raw
- slow diagnostics progress plus PASS/WARN/FAIL/INFO completion totals
- Cancel-focused confirmation for every protected Manage operation
- dark, light, monochrome, `NO_COLOR`, and `WF_ASCII=1` rendering
- output and session-list scroll position preservation across background refresh
- Live/Saved log switching, source-local selection restoration, follow/pause, manual retry, and find
- log-read failure recovery, stale worker rejection, exact-ID attach blocking, and timer cleanup
- narrow list/detail transitions, inspector scrolling, contextual Help, and stopped-session Manage
- narrow detail viewport restoration across Edit, Task, Logs, Manage, Help, refresh, and reopen
- safe narrow-detail exit after filter exclusion, identity replacement, session loss, or wide resize
- `--no-animation`, `WF_MOTION=off`, reduced motion, and focus restoration after modal cancellation
