# WF - Workflow Session Manager

WF is a terminal application for creating, resuming, inspecting, and managing persistent Claude
Code, Codex CLI, Hermes Agent, and shell sessions on Linux. Textual provides the default interface,
Typer provides automation-friendly commands, and tmux keeps work alive across SSH disconnects.

Repository development does not replace an installed `WF`, change login hooks, or adopt existing
tmux sessions. Release installation and cutover remain separate approval-gated operations.

## Highlights

- Grouped Textual dashboard with exclusive interaction modes, structured filters, and responsive layouts
- Distinct Overview, Status, Activity, Recent Output, and protected Manage workflows
- Persistent detached sessions through tmux
- Claude, Codex, Hermes, and shell profiles with strict TOML validation
- Separate runtime, task, agent, input, and alert states with notes, projects, tags, and pinning
- ANSI/OSC sanitization, secret redaction, and byte-and-line bounded pane and log views
- Source-aware Logs workspace with Live/Saved switching, follow/pause, find navigation, and copy
- Optional owner-only sanitized logging, usage-limit warnings, diagnostics export, and onboarding
- Session-aware command palette with categorized commands, shortcuts, and availability details
- Dark, light, monochrome, `NO_COLOR`, and ASCII-compatible presentation modes
- Subtle SSH-friendly motion with config, `--no-animation`, and `WF_MOTION=off` overrides
- Read-only discovery and preview of legacy WF sidecar metadata
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

No command in WF invokes `sudo`.

## Development setup

```bash
git clone https://github.com/NPFernando/wf-session-manager.git
cd wf-session-manager
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/wf-dev doctor
.venv/bin/wf-dev
```

With `uv`:

```bash
uv sync --extra dev
uv run wf-dev doctor
uv run wf-dev
```

Development data lives under the `wf-session-manager` XDG namespace. Operational legacy WF paths are
read only unless a reviewed adoption plan is explicitly applied; adoption does not change those
paths or restart a tmux session.

## CLI

```bash
wf-dev                         # Open the Textual interface
wf-dev --no-animation          # Open with all optional motion disabled
wf-dev list
wf-dev list --all              # Include unmanaged sessions for diagnostics
wf-dev list --json
wf-dev inspect claude-api
wf-dev create --tool claude --name api --cwd ~/projects/api
wf-dev create --tool codex --name review --cwd ~/projects/api --logging
wf-dev create --tool shell --name diagnostics --cwd ~
wf-dev edit claude-api --tag backend --state in_progress --input none --pin
wf-dev note claude-api "Refactor authentication flow"
wf-dev rename claude-api api-refactor
wf-dev resume
wf-dev attach claude-api
wf-dev delete claude-api       # Exact-name confirmation required
wf-dev doctor
wf-dev migrate preview --all --output adoption-plan.json
wf-dev migrate validate adoption-plan.json
wf-dev migrate status
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
| `p` | Open the command palette |
| `?` | Open contextual help |
| `r` | Refresh |
| `t` | Cycle dark, light, and monochrome themes |
| `Esc` | Cancel search or return from a narrow detail screen |
| `q` | Quit |

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
${XDG_CONFIG_HOME:-~/.config}/wf-session-manager/config.toml
```

Configuration is parsed as TOML and validated by Pydantic. It is never evaluated as shell code.
Agent commands are argument arrays, which avoids shell interpolation in configuration parsing.
The `[interface]` table accepts `animations = "off" | "subtle" | "full"` and
`reduce_motion = true | false`. `WF_MOTION=off` takes precedence for an individual launch;
monochrome mode also disables optional motion.

## Data model

New metadata is stored in:

```text
${XDG_STATE_HOME:-~/.local/state}/wf-session-manager/sessions/
```

Each JSON file is owner-only and written atomically. Schema-v2 records include the exact tmux session
ID plus independent task and input states. Schema-v1 records remain readable and are normalized in
memory; reading alone does not rewrite them. If a session name is later reused, the stale record does
not grant ownership.

See [architecture](docs/architecture.md), [security](docs/security.md), and
[migration](docs/migration.md) for design details.

## Quality checks

```bash
make check
make test-integration
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
