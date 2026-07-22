# TUI Interaction Recordings

These recordings were captured from the in-memory fake backend. They do not connect to a tmux
server, read ws metadata, or contain real session names, paths, output, hostnames, or credentials.

Each scenario has a `typescript` stream and a timing file produced by util-linux `script`. Replay a
recording from the repository root with:

```bash
scriptreplay --log-timing docs/recordings/dashboard.timing \
  --log-out docs/recordings/dashboard.typescript
```

Available scenarios:

- `dashboard`: normal dashboard and structured output summary
- `usage-limit`: alert propagation and paused agent state
- `create-validation`: invalid then valid session-name feedback
- `diagnostics`: running and completed diagnostic states
- `reduced-motion`: dashboard with optional motion disabled

The recordings are review artifacts, not automated tests. Textual pilot and SVG snapshot tests are
the deterministic behavioral and visual gates.
