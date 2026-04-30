"""Typer CLI stub for croam. Phase 6 replaces this with the full dispatcher."""
from __future__ import annotations

import typer

app = typer.Typer(
    name="croam",
    pretty_exceptions_enable=False,
    add_completion=False,
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def _main(ctx: typer.Context) -> None:
    """croam: cross-host claude-code session manager."""
    if ctx.invoked_subcommand is None:
        # Phase 6 replaces this with the picker dispatch.
        pass
