"""Typer command line interface and Textual application entry point."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from wf_session_manager import __version__
from wf_session_manager.config import AppConfig, load_config
from wf_session_manager.errors import WFError
from wf_session_manager.legacy import LegacyMetadataReader
from wf_session_manager.migration import MigrationManager, MigrationPlan
from wf_session_manager.models import CreateRequest, SessionState, Tool
from wf_session_manager.paths import AppPaths
from wf_session_manager.service import SessionService
from wf_session_manager.store import MetadataStore
from wf_session_manager.tmux import TmuxBackend
from wf_session_manager.tui import WFApp

app = typer.Typer(
    name="WF",
    help="Manage persistent AI and shell sessions with tmux.",
    no_args_is_help=False,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)
console = Console()
error_console = Console(stderr=True)
migration_app = typer.Typer(help="Preview, apply, inspect, and roll back session adoption.")
app.add_typer(migration_app, name="migrate")


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

    def migration(self) -> MigrationManager:
        return MigrationManager(
            backend=TmuxBackend(),
            store=MetadataStore(self.paths),
            legacy=LegacyMetadataReader(self.config.legacy_state_dirs),
            paths=self.paths,
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
        if result:
            runtime.service().attach(result)
    except WFError as error:
        abort(error)


@app.callback()
def root(
    context: typer.Context,
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
    if context.invoked_subcommand is None:
        run_tui(runtime)


@app.command("list")
def list_command(
    context: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
    include_unmanaged: Annotated[
        bool,
        typer.Option("--all", help="Include unmanaged tmux sessions for diagnostics."),
    ] = False,
) -> None:
    """List managed sessions without changing them."""
    try:
        sessions = (
            runtime_from_context(context)
            .service()
            .list_sessions(include_unmanaged=include_unmanaged)
        )
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
            "managed" if session.owned else "unmanaged",
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
    console.print("Ownership: managed")
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
    """Delete a WF-owned session."""
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
    """Check tmux, agent commands, state, and migration readiness."""
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


def _migration_manager(context: typer.Context) -> MigrationManager:
    return runtime_from_context(context).migration()


def _print_migration_plan(plan: MigrationPlan) -> None:
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("Session")
    table.add_column("Tmux ID")
    table.add_column("Tool")
    table.add_column("Directory")
    table.add_column("Sources")
    table.add_column("Warnings")
    for item in plan.items:
        table.add_row(
            item.name,
            item.tmux_session_id,
            item.tool.value,
            str(item.cwd),
            str(len(item.sources)),
            "; ".join(item.warnings) or "-",
        )
    console.print(table)
    console.print(f"Plan ID: {plan.plan_id}")
    console.print(f"Snapshot: {plan.snapshot_digest}")
    console.print("Notes are included in the private plan file but redacted from this view.")


@migration_app.command("preview")
def migration_preview(
    context: typer.Context,
    sessions: Annotated[
        list[str] | None,
        typer.Option("--session", "-s", help="Exact tmux session name; repeat as needed."),
    ] = None,
    all_sessions: Annotated[
        bool,
        typer.Option("--all", help="Select every eligible unmanaged session."),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write an approval plan with mode 0600."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build a read-only, exact-ID adoption plan."""
    if all_sessions == bool(sessions):
        error_console.print("[red]Error:[/red] choose --all or at least one --session")
        raise typer.Exit(2)
    try:
        manager = _migration_manager(context)
        plan = manager.preview(None if all_sessions else sessions)
        if output is not None:
            manager.write_plan(plan, output.expanduser())
    except WFError as error:
        abort(error)
    if as_json:
        typer.echo(plan.model_dump_json(indent=2))
    else:
        _print_migration_plan(plan)
    if output is not None:
        console.print(f"Plan written: {output.expanduser()}")


@migration_app.command("apply")
def migration_apply(
    context: typer.Context,
    plan_path: Annotated[Path, typer.Argument(help="Reviewed migration plan JSON file.")],
    approve: Annotated[
        bool,
        typer.Option("--approve", help="Approve adoption of every exact session in the plan."),
    ] = False,
) -> None:
    """Adopt sessions only when the reviewed snapshot is unchanged."""
    if not approve:
        error_console.print("[red]Error:[/red] refusing migration without --approve")
        raise typer.Exit(2)
    try:
        journal = _migration_manager(context).apply(plan_path.expanduser())
    except WFError as error:
        abort(error)
    console.print(f"Applied migration {journal.migration_id}: {len(journal.items)} sessions")


@migration_app.command("status")
def migration_status(
    context: typer.Context,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show migration journals without changing sessions."""
    try:
        journals = _migration_manager(context).status()
    except WFError as error:
        abort(error)
    if as_json:
        typer.echo(json.dumps([item.model_dump(mode="json") for item in journals], indent=2))
        return
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("Migration")
    table.add_column("Status")
    table.add_column("Sessions")
    table.add_column("Updated")
    for journal in journals:
        table.add_row(
            str(journal.migration_id),
            journal.status,
            str(len(journal.items)),
            journal.updated_at.isoformat(),
        )
    console.print(table)


@migration_app.command("rollback")
def migration_rollback(
    context: typer.Context,
    migration_id: Annotated[UUID, typer.Argument(help="Applied migration ID.")],
    approve: Annotated[
        bool,
        typer.Option("--approve", help="Approve removal of this migration's ownership records."),
    ] = False,
) -> None:
    """Return an unchanged migration batch to unmanaged status."""
    if not approve:
        error_console.print("[red]Error:[/red] refusing rollback without --approve")
        raise typer.Exit(2)
    try:
        journal = _migration_manager(context).rollback(migration_id)
    except WFError as error:
        abort(error)
    console.print(f"Rolled back migration {journal.migration_id}: {len(journal.items)} sessions")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
