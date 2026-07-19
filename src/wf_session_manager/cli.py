"""Typer command line interface and Textual application entry point."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from wf_session_manager import __version__
from wf_session_manager.classic import exec_classic
from wf_session_manager.config import AppConfig, load_config
from wf_session_manager.errors import WFError
from wf_session_manager.legacy import LegacyMetadataReader
from wf_session_manager.models import CreateRequest, SessionState, Tool
from wf_session_manager.paths import AppPaths
from wf_session_manager.service import SessionService
from wf_session_manager.store import MetadataStore
from wf_session_manager.tmux import TmuxBackend
from wf_session_manager.tui import CLASSIC_RESULT, WFApp

app = typer.Typer(
    name="WF",
    help="Manage persistent AI and shell sessions with tmux.",
    no_args_is_help=False,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)
console = Console()
error_console = Console(stderr=True)


@dataclass(frozen=True, slots=True)
class Runtime:
    paths: AppPaths
    config: AppConfig

    def service(self) -> SessionService:
        return SessionService(
            backend=TmuxBackend(),
            store=MetadataStore(self.paths),
            config=self.config,
            paths=self.paths,
            legacy=LegacyMetadataReader(self.config.legacy_state_dirs),
        )


def build_runtime(config_path: Path | None = None) -> Runtime:
    paths = AppPaths.discover()
    return Runtime(paths=paths, config=load_config(paths, config_path))


def runtime_from_context(context: typer.Context) -> Runtime:
    runtime = context.obj
    if not isinstance(runtime, Runtime):
        raise RuntimeError("WF runtime was not initialized")
    return runtime


def abort(error: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {error}")
    raise typer.Exit(1)


def run_tui(runtime: Runtime) -> None:
    try:
        result = WFApp(runtime.service()).run()
        if result == CLASSIC_RESULT:
            exec_classic(runtime.config)
        elif result:
            runtime.service().attach(result)
    except WFError as error:
        if runtime.config.fallback_to_classic_on_error:
            exec_classic(runtime.config)
        abort(error)


@app.callback()
def root(
    context: typer.Context,
    classic: Annotated[
        bool,
        typer.Option("--classic", help="Open the preserved fzf implementation."),
    ] = False,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", help="Show the WF version."),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Use a specific TOML configuration file."),
    ] = None,
) -> None:
    """Open the session manager when no subcommand is supplied."""
    try:
        runtime = build_runtime(config)
    except WFError as error:
        abort(error)
    context.obj = runtime
    if version:
        typer.echo(f"WF {__version__}")
        raise typer.Exit()
    if classic:
        try:
            exec_classic(runtime.config)
        except WFError as error:
            abort(error)
    if context.invoked_subcommand is None:
        run_tui(runtime)


@app.command("list")
def list_command(
    context: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """List live tmux sessions without changing them."""
    try:
        sessions = runtime_from_context(context).service().list_sessions()
    except WFError as error:
        abort(error)
    if as_json:
        typer.echo(json.dumps([item.model_dump(mode="json") for item in sessions], indent=2))
        return
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("Status")
    table.add_column("Session")
    table.add_column("Tool")
    table.add_column("State")
    table.add_column("Directory")
    table.add_column("Owner")
    for session in sessions:
        table.add_row(
            "attached" if session.attached else "detached",
            session.name,
            session.tool.value,
            session.state,
            str(session.cwd),
            "WF" if session.owned else "classic/read-only",
        )
    console.print(table)


@app.command()
def inspect(
    context: typer.Context,
    name: Annotated[str, typer.Argument(help="Exact tmux session name.")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show metadata and a sanitized pane preview."""
    try:
        details = runtime_from_context(context).service().inspect(name)
    except WFError as error:
        abort(error)
    if as_json:
        typer.echo(details.model_dump_json(indent=2))
        return
    session = details.session
    console.print(f"[bold cyan]{session.name}[/bold cyan]")
    console.print(f"Tool: {session.tool.value}")
    console.print(f"Status: {'attached' if session.attached else 'detached'}")
    console.print(f"Ownership: {'managed' if session.owned else 'classic / read-only'}")
    console.print(f"Directory: {session.cwd}")
    console.print(f"Note: {session.note or '-'}")
    console.rule("Sanitized preview")
    console.print(details.preview or "No pane output")


@app.command()
def create(
    context: typer.Context,
    tool: Annotated[Tool, typer.Option("--tool", "-t")],
    name: Annotated[str, typer.Option("--name", "-n")],
    cwd: Annotated[Path | None, typer.Option("--cwd", "-C")] = None,
    note: Annotated[str, typer.Option("--note")] = "",
    tag: Annotated[list[str] | None, typer.Option("--tag")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    attach: Annotated[bool, typer.Option("--attach")] = False,
) -> None:
    """Create a detached, persistent WF-owned session."""
    request = CreateRequest(name=name, tool=tool, cwd=cwd or Path.cwd(), note=note, tags=tag or [])
    service = runtime_from_context(context).service()
    try:
        session = service.create(request, dry_run=dry_run)
    except WFError as error:
        abort(error)
    prefix = "Would create" if dry_run else "Created"
    console.print(f"{prefix}: [bold]{session.name}[/bold] in {session.cwd}")
    if attach and not dry_run:
        try:
            service.attach(session.name)
        except WFError as error:
            abort(error)


@app.command()
def attach(context: typer.Context, name: str) -> None:
    """Attach or switch to an existing tmux session."""
    try:
        runtime_from_context(context).service().attach(name)
    except WFError as error:
        abort(error)


@app.command()
def resume(context: typer.Context) -> None:
    """Attach to the most relevant detached session."""
    service = runtime_from_context(context).service()
    try:
        service.attach(service.resume_target().name)
    except WFError as error:
        abort(error)


@app.command()
def note(context: typer.Context, name: str, text: str) -> None:
    """Update the note for a WF-owned session."""
    try:
        runtime_from_context(context).service().update_note(name, text)
    except WFError as error:
        abort(error)
    typer.echo(f"Updated note for {name}")


@app.command()
def organize(
    context: typer.Context,
    name: str,
    tag: Annotated[list[str] | None, typer.Option("--tag")] = None,
    state: Annotated[SessionState | None, typer.Option("--state")] = None,
    pin: Annotated[bool | None, typer.Option("--pin/--unpin")] = None,
) -> None:
    """Set tags, task state, or pin status on a WF-owned session."""
    try:
        runtime_from_context(context).service().organize(name, tags=tag, state=state, pinned=pin)
    except WFError as error:
        abort(error)
    typer.echo(f"Updated {name}")


@app.command()
def rename(context: typer.Context, old_name: str, new_name: str) -> None:
    """Rename a WF-owned session and its metadata atomically."""
    try:
        session = runtime_from_context(context).service().rename(old_name, new_name)
    except WFError as error:
        abort(error)
    typer.echo(f"Renamed {old_name} to {session.name}")


@app.command()
def delete(
    context: typer.Context,
    name: str,
    yes: Annotated[bool, typer.Option("--yes", help="Skip typed confirmation.")] = False,
) -> None:
    """Delete a WF-owned session; classic sessions are always rejected."""
    if not yes:
        confirmation = typer.prompt(f'Type "{name}" to confirm deletion')
        if confirmation != name:
            typer.echo("Cancelled")
            raise typer.Exit(1)
    try:
        runtime_from_context(context).service().delete(name)
    except WFError as error:
        abort(error)
    typer.echo(f"Deleted {name}")


@app.command()
def doctor(
    context: typer.Context,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Check tmux, agent commands, state, and classic fallback availability."""
    report = runtime_from_context(context).service().doctor()
    if as_json:
        typer.echo(report.model_dump_json(indent=2))
    else:
        table = Table(show_header=True, header_style="bold cyan", box=None)
        table.add_column("Check")
        table.add_column("Result")
        table.add_column("Detail")
        for check in report.checks:
            table.add_row(check.name, check.status.value, check.detail)
        console.print(table)
    if not report.healthy:
        raise typer.Exit(1)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def classic(context: typer.Context) -> None:
    """Run the preserved classic implementation with optional arguments."""
    try:
        exec_classic(runtime_from_context(context).config, list(context.args))
    except WFError as error:
        abort(error)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
