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
    from croam.commands import ls as ls_mod
    from croam.config import load_config

    config = load_config()
    raise typer.Exit(ls_mod.run(ctx.obj, config, Path.home()))


@app.command("attach")
def cmd_attach(
    ctx: typer.Context,
    sid: Annotated[str | None, typer.Argument(help="Session UUID. Omit for picker fallback.")] = (
        None
    ),
    here_on_owner: Annotated[bool, typer.Option("--here-on-owner", hidden=True)] = False,
    no_exec: Annotated[bool, typer.Option("--no-exec", hidden=True)] = False,
) -> None:
    """Attach to a session (recursive over SSH if remotely-owned)."""
    from croam.commands import attach as attach_mod
    from croam.config import load_config

    config = load_config()
    raise typer.Exit(
        attach_mod.run(
            sid, ctx.obj, config, Path.home(), here_on_owner=here_on_owner, no_exec=no_exec
        )
    )


@app.command("peek")
def cmd_peek(
    ctx: typer.Context,
    sid: Annotated[str, typer.Argument(help="Session UUID.")],
    here_on_owner: Annotated[bool, typer.Option("--here-on-owner", hidden=True)] = False,
    no_exec: Annotated[bool, typer.Option("--no-exec", hidden=True)] = False,
) -> None:
    """Read-only view of a session."""
    from croam.commands import peek as peek_mod
    from croam.config import load_config

    config = load_config()
    raise typer.Exit(
        peek_mod.run(
            sid, ctx.obj, config, Path.home(), here_on_owner=here_on_owner, no_exec=no_exec
        )
    )


@app.command("claim")
def cmd_claim(
    ctx: typer.Context,
    sid: Annotated[str, typer.Argument(help="Session UUID.")],
    here: Annotated[bool, typer.Option("--here")] = False,
) -> None:
    """Transfer ownership to this host."""
    from croam.commands import claim as claim_mod
    from croam.config import load_config

    config = load_config()
    raise typer.Exit(
        claim_mod.run(
            sid,
            state_root=config.storage.state_root,
            hostname=config.self_hostname,
            home=Path.home(),
            config_path=Path.home() / ".config" / "croam" / "config.toml",
            here=here,
        )
    )


@app.command("fork")
def cmd_fork(
    ctx: typer.Context,
    sid: Annotated[str, typer.Argument(help="Session UUID.")],
    here: Annotated[bool, typer.Option("--here")] = False,
) -> None:
    """Branch a new session from an existing JSONL."""
    from croam.commands import fork as fork_mod
    from croam.config import load_config

    config = load_config()
    _fork_sid, rc = fork_mod.run(
        sid,
        state_root=config.storage.state_root,
        hostname=config.self_hostname,
        home=Path.home(),
        here=here,
    )
    raise typer.Exit(rc)


@app.command("release", hidden=True)
def cmd_release(
    ctx: typer.Context,
    sid: Annotated[str, typer.Argument(help="Session UUID.")],
    emit_jsonl: Annotated[bool, typer.Option("--emit-jsonl", hidden=True)] = False,
) -> None:
    """Hidden: release ownership (called by remote claim)."""
    from croam.commands import release as release_mod
    from croam.config import load_config

    config = load_config()
    raise typer.Exit(
        release_mod.run(
            sid,
            state_root=config.storage.state_root,
            hostname=config.self_hostname,
            home=Path.home(),
            emit_jsonl=emit_jsonl,
        )
    )


@app.command("launch")
def cmd_launch(ctx: typer.Context) -> None:
    """Wrap a claude invocation inside tmux (the shim entry point)."""
    from croam.commands import launch as launch_mod
    from croam.config import load_config

    config = load_config()
    raise typer.Exit(
        launch_mod.launch_cmd(
            argv=["claude"],
            config=config,
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
