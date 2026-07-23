# Workspace Session Manager

ws is a terminal application for creating, resuming, inspecting, and managing persistent Claude
Code, Codex CLI, Hermes Agent, and shell sessions on Linux. Textual provides the default interface,
Typer provides automation-friendly commands, and tmux keeps work alive across SSH disconnects.

Repository development does not replace an installed `ws`, change login hooks, or adopt existing
tmux sessions. Release installation and cutover remain separate approval-gated operations.

## Highlights

- Grouped Textual dashboard with exclusive interaction modes, structured filters, configurable grouping
  and density, and responsive layouts
- Distinct Overview, Status, Activity, Recent Output, and protected Manage workflows
- Persistent detached sessions through tmux
- Claude, Codex, Hermes, and shell profiles with strict TOML validation
- Separate runtime, task, agent, input, and alert states with notes, projects, tags, and pinning
- Background Attention checks with bounded exact-ID pane reads and a restorable warning-only view
- ANSI/OSC sanitization, secret redaction, and byte-and-line bounded pane and log views
- Source-aware Logs workspace with Live/Saved switching, follow/pause, find navigation, and copy
- Optional owner-only sanitized logging, usage-limit warnings, diagnostics export, and onboarding
- Session-aware command palette with categorized commands, shortcuts, and availability details
- Eight built-in themes, plus monochrome (`NO_COLOR`) and ASCII-compatible (`WS_ASCII=1`) rendering
- Subtle SSH-friendly motion with config, `--no-animation`, and `WS_MOTION=off` overrides
- Read-only discovery and preview of legacy ws sidecar metadata
- Exact-ID, snapshot-validated, reversible session adoption
- Ownership checks tied to both tmux's unique session ID and a tmux owner marker
- Managed-only default views with `list --all` for diagnostics
- JSON output for session discovery, inspection, and diagnostics
- XDG-compatible, permission-restricted, atomic state storage

## Requirements

- Linux
- Python 3.11 or newer
- tmux
- One or more optional agent commands: `claude`, `codex`, or `hermes`

No command in ws invokes `sudo`.

## Development setup

```bash
git clone https://github.com/NPFernando/workspace-session-manager.git
cd workspace-session-manager
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ws-dev doctor
.venv/bin/ws-dev
```

With `uv`:

```bash
uv sync --extra dev
uv run ws-dev doctor
uv run ws-dev
```

Run the development checks with the locked environment:

```bash
uv sync --locked --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -m "not integration"
```

Development data lives under the `workspace-session-manager` XDG namespace. Operational legacy ws paths are
read only unless a reviewed adoption plan is explicitly applied; adoption does not change those
paths or restart a tmux session.

## CLI

```bash
ws-dev                         # Open the Textual interface
ws-dev --no-animation          # Open with all optional motion disabled
ws-dev list
ws-dev list --all              # Include unmanaged sessions for diagnostics
ws-dev list --json
ws-dev inspect claude-api
ws-dev create --tool claude --name api --cwd ~/projects/api
ws-dev create --tool codex --name review --cwd ~/projects/api --logging
ws-dev create --tool shell --name diagnostics --cwd ~
ws-dev create --from-session claude-api --name api-follow-up
ws-dev preset save backend --tool codex --cwd ~/projects/api --tag backend
ws-dev preset list
ws-dev create --from-preset backend --name api-review
ws-dev edit claude-api --tag backend --state in_progress --input none --pin
ws-dev note claude-api "Refactor authentication flow"
ws-dev rename claude-api api-refactor
ws-dev resume
ws-dev attach claude-api
ws-dev delete claude-api       # Exact-name confirmation required
ws-dev doctor
ws-dev migrate preview --all --output adoption-plan.json
ws-dev migrate validate adoption-plan.json
ws-dev migrate status
```

Normal commands and the Textual dashboard operate only on managed sessions. A session is managed only
when its validated metadata, exact live tmux ID, and tmux owner marker agree. Unmanaged sessions are
hidden unless `list --all` is requested.

## Keyboard controls

| Key | Action |
| --- | --- |
| `Enter` | Attach, or open the in-place inspector at 80-99 columns |
| `Up`/`Down`, `j`/`k` | Navigate sessions; scroll an open narrow inspector |
| `c` | Create a session |
| `e` | Edit identity and organization |
| `n` | Edit the task description |
| `l` | Open the sanitized log view |
| `*` | Toggle pin |
| `d` | Open protected session actions |
| `/` | Enter on-demand search mode |
| `f` | Filter by tool, runtime, task state, warning, or recent activity |
| `g` | Cycle the dashboard grouping |
| `z` | Toggle compact and comfortable row density |
| `h` | Open system health details |
| `s` | Search saved session output |
| `p` | Open the command palette |
| `?` | Open contextual help |
| `r` | Refresh |
| `t` | Cycle dark, light, and monochrome themes |
| `Esc` | Cancel search or return from a narrow detail screen |
| `q` | Quit |

Open **Attention** from Quick Actions or the command palette to temporarily show sessions with known
warnings. `Esc` restores the prior query, filters, selection, focus, and list position. The header
shows scan progress until every eligible agent session has been checked; new warnings discovered
after that initial baseline are reported in one aggregated notification per scan batch.

At 80-99 columns, the first `Enter` opens the selected session's existing inspector at full width;
the next `Enter` attaches. `Esc` returns to the session list. Opening Edit, Task, Logs, Manage, or Help
from that view preserves its inspector position, output position, Summary/Raw mode, selection, and
filters. Starting Search or Filter intentionally returns to the list first.

Inside Logs, `f` pauses or resumes polling, `r` performs a manual read, and `/` opens literal,
case-insensitive find. `Enter` and `Shift+Enter` move between matches, `Ctrl+U` clears the query,
`t` switches between relative and absolute capture times, and `c` copies the selection or the loaded
sanitized output. Active sessions open on the Live pane; stopped sessions open on Saved output when
available. Pausing preserves the current selection and scroll position independently for each source.

The create dialog validates names and directories, detects duplicate sessions and Git projects,
shows the exact command, and keeps Create disabled until required fields are valid. `d` opens a
searchable Manage action browser grouped into General, Runtime, and Danger sections. Identity,
task, and status edits use focused forms; stop, metadata removal, log deletion, and complete deletion
always require a separate confirmation with Cancel focused by default. Canceling a nested form or
confirmation returns to the originating Manage action. Modal workflows suspend Search and restore
its query, selection, focus, and scroll state when they close.

## Configuration

Copy `config.example.toml` to:

```text
${XDG_CONFIG_HOME:-~/.config}/workspace-session-manager/config.toml
```

Configuration is parsed as TOML and validated by Pydantic. It is never evaluated as shell code.
Agent commands are argument arrays, which avoids shell interpolation in configuration parsing.
The `[interface]` table accepts `animations = "off" | "subtle" | "full"` and
`reduce_motion = true | false`. It also supports `environment_display = "hidden" | "label" |
"hostname"` (default: `hidden`), `environment_label` (shown only with `label`),
`default_grouping = "attention" | "runtime" | "agent" | "project" | "warning" | "recent"`
(default: `attention`), and `default_density = "compact" | "comfortable"` (default:
`comfortable`). Configuration is strict: unknown keys and invalid values prevent startup rather than
being silently ignored.

`WS_MOTION=off` takes precedence for an individual launch; `--no-animation`, reduced motion, and
monochrome mode also disable optional motion. `NO_COLOR=1` starts in monochrome. `WS_ASCII=1` avoids
Unicode decorations, which is useful for terminals with incomplete Unicode support.

### Terminal, theme, and accessibility guidance

The dashboard is keyboard-first. Focused dialogs keep their own controls active, `Esc` cancels or
returns to the previous safe context, and destructive confirmations focus Cancel by default. Use
`?` at any time for contextual shortcuts and `p` for the command palette.

Press `t` to cycle the built-in themes: Ithaca, Dark, Light, Monochrome, Midnight, Cyberpunk,
Terminal, and Paper. If your terminal or SSH client has limited colour, set `NO_COLOR=1`; if it has
limited Unicode support, set `WS_ASCII=1`. For slow links, remote terminals, or motion-sensitive
users, prefer `ws-dev --no-animation` or `WS_MOTION=off`.

The layout adapts from wide views down to narrow detail views. At very small dimensions it shows an
instructional fallback instead of exposing clipped controls; the Logs workspace requires at least
40x15. See [terminal compatibility and test status](docs/testing.md#terminal-compatibility-matrix)
before relying on a terminal/client combination in production.

`attention_scan_budget` controls how many eligible agent sessions a refresh may inspect. Its default
is `8`, with a validated range of `1` to `64`. Each background check reads at most 20 sanitized lines
and 8 KiB from the exact tmux session ID. Derived alerts remain in memory and never rewrite session
metadata.

## Data model

New metadata is stored in:

```text
${XDG_STATE_HOME:-~/.local/state}/workspace-session-manager/sessions/
```

Each JSON file is owner-only and written atomically. Schema-v2 records include the exact tmux session
ID plus independent task and input states. Schema-v1 records remain readable and are normalized in
memory; reading alone does not rewrite them. If a session name is later reused, the stale record does
not grant ownership.

See [architecture](docs/architecture.md), [security](docs/security.md), and
[migration](docs/migration.md) for design details.

## Quality checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -m "not integration"
WS_RUN_TMUX_INTEGRATION=1 uv run pytest -m integration -q --no-cov
make secret-scan
```

The real-tmux integration tests use socket paths inside pytest temporary directories. Cleanup removes
only exact test session IDs and temporary sockets. Adoption coverage also verifies that rollback does
not restart, rename, or remove its disposable tmux session.

## Project status

Version `0.2.0` adds the production dashboard hierarchy, protected interactions, responsive modes,
sanitized logging, structured diagnostics, theme support, and deterministic visual regression
coverage. Installing it over an existing release remains an explicit approval-gated step; see
[migration](docs/migration.md).

## License

MIT. See [LICENSE](LICENSE).
