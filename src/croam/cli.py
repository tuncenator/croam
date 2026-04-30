from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from croam import log
from croam.errors import CroamError

app = typer.Typer(
    name="croam",
    no_args_is_help=False,
    pretty_exceptions_enable=False,
    add_completion=False,
    invoke_without_command=True,
)


@app.callback()
def _global(
    ctx: typer.Context,
    debug: Annotated[bool, typer.Option("--debug", help="Enable DEBUG-level logging.")] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON instead of human output (where supported).")
    ] = False,
    all_: Annotated[
        bool, typer.Option("--all", "-A", help="Show sessions from all hosts and dirs.")
    ] = False,
    project_root: Annotated[
        bool, typer.Option("-p", help="Walk up to git root for cwd filter.")
    ] = False,
    host: Annotated[str | None, typer.Option("--host", help="Limit to a single host.")] = None,
    last: Annotated[int | None, typer.Option("--last", help="Window in days. Default 30.")] = None,
    orphans: Annotated[bool, typer.Option("--orphans", help="Show only orphan JSONLs.")] = False,
) -> None:
    """croam: cross-host claude-code session manager."""
    # Configure logging eagerly so even no-verb invocations log correctly.
    log_file = Path.home() / ".local/state/croam/croam.log" if debug else None
    log.configure(level="DEBUG" if debug else "WARNING", log_file=log_file, debug=debug)

    ctx.obj = {
        "debug": debug,
        "json": json_out,
        "all": all_,
        "project_root": project_root,
        "host": host,
        "last": last,
        "orphans": orphans,
    }

    # No verb -> picker.
    if ctx.invoked_subcommand is None:
        from croam.commands import default
        from croam.config import load_config

        config = load_config()
        rc = default.run_picker(config=config, home=Path.home(), ctx_obj=ctx.obj)
        raise typer.Exit(rc)


@app.command("ls")
def cmd_ls(ctx: typer.Context) -> None:
    """List sessions (use --json for scriptable output)."""
    raise NotImplementedError("Phase 7")


@app.command("attach")
def cmd_attach(
    ctx: typer.Context,
    sid: Annotated[str | None, typer.Argument(help="Session UUID. Omit for picker fallback.")] = (
        None
    ),
    here_on_owner: Annotated[bool, typer.Option("--here-on-owner", hidden=True)] = False,
) -> None:
    """Attach to a session (recursive over SSH if remotely-owned)."""
    raise NotImplementedError("Phase 7")


@app.command("peek")
def cmd_peek(
    ctx: typer.Context,
    sid: Annotated[str, typer.Argument(help="Session UUID.")],
) -> None:
    """Read-only view of a session."""
    raise NotImplementedError("Phase 7")


@app.command("claim")
def cmd_claim(
    ctx: typer.Context,
    sid: Annotated[str, typer.Argument(help="Session UUID.")],
    here: Annotated[bool, typer.Option("--here")] = False,
) -> None:
    """Transfer ownership to this host."""
    raise NotImplementedError("Phase 8")


@app.command("fork")
def cmd_fork(
    ctx: typer.Context,
    sid: Annotated[str, typer.Argument(help="Session UUID.")],
    here: Annotated[bool, typer.Option("--here")] = False,
) -> None:
    """Branch a new session from an existing JSONL."""
    raise NotImplementedError("Phase 8")


@app.command("launch")
def cmd_launch(ctx: typer.Context) -> None:
    """Wrap a claude invocation inside tmux (the shim entry point)."""
    # Phase 5 owns commands/launch.py. If it exists, dispatch; else stub.
    try:
        from croam.commands import launch as launch_mod
    except ImportError as exc:
        raise NotImplementedError("Phase 5") from exc
    raise typer.Exit(
        launch_mod.launch_cmd(
            argv=["claude"],
            config=ctx.obj.get("_config"),  # type: ignore[arg-type]
            home=Path.home(),
        )
    )


@app.command("doctor")
def cmd_doctor(ctx: typer.Context) -> None:
    """Diagnose config, SSH, syncthing, ownership consistency."""
    raise NotImplementedError("Phase 9")


@app.command("emit-state", hidden=True)
def cmd_emit_state(ctx: typer.Context) -> None:
    """Hidden: emit this host's JSON state for SSH fanout."""
    from croam.commands.emit_state import emit_state_cmd
    from croam.config import load_config

    config = load_config()
    raise typer.Exit(
        emit_state_cmd(
            home=Path.home(),
            state_root=config.storage.state_root,
            hostname=config.self_hostname,
        )
    )


def main() -> None:
    """Entry point for `[project.scripts] croam = "croam.cli:main"`."""
    try:
        app()
    except CroamError as e:
        typer.echo(f"croam: {e}", err=True)
        raise SystemExit(2) from None
