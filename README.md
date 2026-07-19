# WF - Workflow Session Manager

WF is a terminal application for creating, resuming, inspecting, and organizing persistent Claude
Code, Codex CLI, Hermes Agent, and shell sessions on Linux. Textual provides the default interface,
Typer provides automation-friendly commands, and tmux keeps work alive across SSH disconnects.

The project is currently in parallel-development mode. Repository setup does not replace an existing
`WF` installation, change login hooks, or adopt existing tmux sessions. Each cutover action has a
separate approval gate.

## Highlights

- Session-first Textual dashboard with search, details, sanitized pane preview, and responsive layout
- Persistent detached sessions through tmux
- Claude, Codex, Hermes, and shell profiles with strict TOML validation
- Notes, tags, task state, pinning, rename, resume, and guarded deletion
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
wf-dev list
wf-dev list --all              # Include unmanaged sessions for diagnostics
wf-dev list --json
wf-dev inspect claude-api
wf-dev create --tool claude --name api --cwd ~/projects/api
wf-dev create --tool shell --name diagnostics --cwd ~
wf-dev organize claude-api --tag backend --state active --pin
wf-dev note claude-api "Refactor authentication flow"
wf-dev rename claude-api api-refactor
wf-dev resume
wf-dev attach claude-api
wf-dev delete claude-api       # Exact-name confirmation required
wf-dev doctor
wf-dev migrate preview --all --output adoption-plan.json
wf-dev migrate status
```

Normal commands and the Textual dashboard operate only on managed sessions. A session is managed only
when its validated metadata, exact live tmux ID, and tmux owner marker agree. Unmanaged sessions are
hidden unless `list --all` is requested.

## Keyboard controls

| Key | Action |
| --- | --- |
| `Enter` | Attach to the selected session |
| `n` | Create a session |
| `e` | Edit note, tags, task state, and pin |
| `p` | Toggle pin |
| `d` | Delete a managed session with exact-name confirmation |
| `/` | Focus search |
| `r` | Refresh |
| `q` | Quit |

## Configuration

Copy `config.example.toml` to:

```text
${XDG_CONFIG_HOME:-~/.config}/wf-session-manager/config.toml
```

Configuration is parsed as TOML and validated by Pydantic. It is never evaluated as shell code.
Agent commands are argument arrays, which avoids shell interpolation in configuration parsing.

## Data model

New metadata is stored in:

```text
${XDG_STATE_HOME:-~/.local/state}/wf-session-manager/sessions/
```

Each JSON file is owner-only and written atomically. A record includes the tmux session ID that was
assigned at creation or captured during approved adoption. If a session name is later reused, the
stale record does not grant ownership.

See [architecture](docs/architecture.md), [security](docs/security.md), and
[migration](docs/migration.md) for design details.

## Quality checks

```bash
make check
make test-integration
make secret-scan
```

The real-tmux integration tests create random, clearly prefixed sessions. Cleanup removes only those
exact test session IDs. Adoption coverage also verifies that rollback does not restart, rename, or
remove its disposable tmux session.

## Project status

Version `0.1.0` is the first independently testable implementation. Operational cutover remains an
explicit approval-gated step; see [migration](docs/migration.md).

## License

MIT. See [LICENSE](LICENSE).
