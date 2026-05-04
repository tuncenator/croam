# Phase 6: Picker & CLI dispatcher

**Feature**: project-start
**Estimated Context Budget**: ~100k tokens

**Difficulty**: hard
**Visual**: no
**Functional**: yes

**Execution Mode**: sequential
**Batch**: 4 (sole phase in this batch; depends on Phases 1-5)

---

## Objective

Wire the typer CLI app with all global flags and the full verb set (mostly stubs, filled in by phases 7-9), and implement the fzf picker (row layout, hidden filter columns, multi-select intersection, dispatch via `--expect`). After this phase, `croam --help` lists every public verb, `croam emit-state` returns a valid JSON stub, and the picker can be driven end-to-end against a fake-fzf fixture and a real fzf binary against a synthetic two-row state.

This phase owns the wire format between the row renderer and fzf -- the exact tab-delimited column ordering. Every later phase that adds a verb or a new bind references that shape; if it changes, every fzf bind that references `{1}` (the sid column) or any hidden filter token breaks.

---

## Deliverables

1. **`src/croam/cli.py`** (FULL OWNERSHIP -- replaces the Phase 1 stub) -- typer app with global callback, all verb registrations (most as stubs raising `NotImplementedError("Phase N")`), the hidden `emit-state` verb wired to Phase 3, and a top-level `CroamError` -> `typer.Exit(2)` translator.

2. **`src/croam/picker.py`** -- `PickerRow` dataclass, `format_last_column`, `compute_glyph`, `compute_status_word`, `render_rows`, `format_input_lines`, `build_fzf_argv`, `launch_picker`, `compute_action_intersection`. Pure functions plus the one impure `subprocess.Popen` orchestrator.

3. **`src/croam/commands/__init__.py`** -- empty (package marker; Phase 7+ adds verb modules).

4. **`src/croam/commands/default.py`** -- `run_picker(config, home, ctx_obj) -> int` orchestrator: discover sessions/assertions/host-statuses/lineage, render rows, launch picker, dispatch the result. Phase 6 ships the full orchestrator with stub dispatch (every result raises `NotImplementedError("Phase 7")` for now); Phase 7 fills in the dispatch table.

5. **`tests/test_cli.py`** -- 5 tests covering help output, hidden command, emit-state, debug flag wiring, and the top-level error handler.

6. **`tests/test_picker.py`** -- 9 tests covering pure formatters, render_rows behavior, fzf argv construction, and the `launch_picker` happy/cancel/no-match/error paths against a fake-fzf shell script.

7. **`tests/_helpers/fake_fzf.py`** -- a Python helper that produces a temp executable shell script emitting canned fzf output. Used by `test_launch_picker_*` tests and reusable by Phase 7 if it ever integration-tests the picker dispatcher.

---

## Detailed Requirements

### Implementation order (follow this; do not reorder)

1. Write `src/croam/cli.py` first with every verb registered as a stub that raises `NotImplementedError("Phase N")`. This proves typer wiring works in isolation.
2. Write `src/croam/picker.py` with the pure functions (`format_last_column`, `compute_glyph`, `compute_status_word`, `format_input_lines`, `build_fzf_argv`, `compute_action_intersection`). These are testable without subprocess.
3. Write `render_rows` (joins sessions + assertions + host_statuses + lineage into `PickerRow` instances).
4. Write `launch_picker` (the `subprocess.Popen` orchestrator).
5. Write `src/croam/commands/default.py:run_picker`. Wire it from `cli.py`'s no-verb callback path. Stub the dispatch table.
6. Write `tests/_helpers/fake_fzf.py`.
7. Write `tests/test_picker.py`. Run it -- everything in steps 2-4 must be green.
8. Write `tests/test_cli.py`. Run it -- everything in steps 1+5 must be green.
9. Run the full test suite (`uv run pytest`). Smoke through every command's `--help`.

---

### `src/croam/cli.py`

```python
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from loguru import logger

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
    json_out: Annotated[bool, typer.Option("--json", help="Emit JSON instead of human output (where supported).")] = False,
    all_: Annotated[bool, typer.Option("--all", "-A", help="Show sessions from all hosts and dirs.")] = False,
    project_root: Annotated[bool, typer.Option("-p", help="Walk up to git root for cwd filter.")] = False,
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
    sid: Annotated[str | None, typer.Argument(help="Session UUID. Omit for picker fallback.")] = None,
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
    # Phase 5 owns commands/launch.py. If Phase 5's module exists, dispatch; else stub.
    try:
        from croam.commands import launch as launch_mod
    except ImportError as exc:
        raise NotImplementedError("Phase 5") from exc
    raise typer.Exit(launch_mod.run(ctx_obj=ctx.obj))


@app.command("doctor")
def cmd_doctor(ctx: typer.Context) -> None:
    """Diagnose config, SSH, syncthing, ownership consistency."""
    raise NotImplementedError("Phase 9")


@app.command("emit-state", hidden=True)
def cmd_emit_state(ctx: typer.Context) -> None:
    """Hidden: emit this host's JSON state for SSH fanout."""
    # Phase 3 owns commands/emit_state.py. Wire to it.
    from croam.commands import emit_state as emit_state_mod
    raise typer.Exit(emit_state_mod.run(ctx_obj=ctx.obj))


def main() -> None:
    """Entry point used by `[project.scripts] croam = "croam.cli:main"`. Wraps app() with CroamError translation."""
    try:
        app()
    except CroamError as e:
        typer.echo(f"croam: {e}", err=True)
        raise typer.Exit(2)
```

**Note on the entry point**: Phase 1's `pyproject.toml` currently declares `[project.scripts] croam = "croam.cli:app"`. Phase 6 must change this to `croam.cli:main` so the `CroamError` handler runs. Edit `pyproject.toml` accordingly. (This is the ONE non-`src/croam/cli.py` edit Phase 6 must make.)

**Note on the imports inside `_global`**: import `commands.default` and `load_config` lazily (inside the function body) so that `croam --help` and `croam emit-state` do not pay the cost of building a `Config` object.

**Note on Phase 5's `commands/launch.py` and Phase 3's `commands/emit_state.py`**: those modules should already exist by the time Phase 6 runs. If a coding agent runs Phase 6 before phases 3 and 5 land, the import-time error surfaces clearly. Do NOT stub those modules in `src/croam/commands/` from Phase 6 -- that would create a file ownership conflict.

---

### `src/croam/picker.py`

#### `PickerRow` dataclass

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

@dataclass(frozen=True)
class PickerRow:
    sid: str            # column 1 (hidden filter)
    glyph: str          # column 2 (displayed) -- "o" reachable, "O" unreachable
    status_word: str    # column 3 (hidden filter) -- "running-idle" | "running-busy" | "archived" | "unreachable"
    reach_word: str     # column 4 (hidden filter) -- "reachable" | "unreachable"
    cwd_word: str       # column 5 (hidden filter) -- "present" | "missing-cwd"
    host: str           # column 6 (displayed)
    last: str           # column 7 (displayed) -- "Nm" | "Nh" | "ND" | "NM" | "-"
    cwd_display: str    # column 8 (displayed) -- "~/Programs/foo" or fish-style truncated
    name: str           # column 9 (displayed) -- session name + lineage tag if forked
```

**Wire-format invariant** (the rest of this phase and every later phase depends on it): the input line for fzf is exactly:

```
<sid>\t<glyph>\t<status_word>\t<reach_word>\t<cwd_word>\t<host>\t<last>\t<cwd_display>\t<name>\n
```

Columns 1, 3, 4, 5 are hidden via `--with-nth=2,6,7,8,9` but fzf still searches them, so typing `busy`, `unreachable`, `missing-cwd`, `stormtree` all narrow correctly. Column 1 (the sid) is referenced as `{1}` in fzf bind expansions for the preview pane.

#### `format_last_column`

```python
def format_last_column(updated_at_ms: int | None, now: datetime) -> str:
    """Format ms-epoch timestamp as 'Nm', 'Nh', 'ND', 'NM' per spec section 4.

    Boundaries:
      - None       -> "-"
      - 0..59 min  -> "<N>m"
      - 1..47 h    -> "<N>h"
      - 2..30 day  -> "<N>D"
      - 30+ day    -> "<N>M"   (calendar months, integer divided)
    """
```

Example expectations (`now` fixed at `2026-04-30T12:00:00Z`):

| `updated_at_ms` | Returned |
|---|---|
| None | `"-"` |
| 30s ago (`now - 30000`) | `"0m"` |
| 14m ago | `"14m"` |
| 1h ago | `"1h"` |
| 25h ago | `"25h"` |
| 47h ago | `"47h"` |
| 48h ago | `"2D"` |
| 5 days ago | `"5D"` |
| 30 days ago | `"30D"` |
| 31 days ago | `"1M"` |
| 60 days ago | `"2M"` |

Use `datetime.fromtimestamp(ms / 1000, tz=timezone.utc)` to parse and `(now - then).total_seconds()` to compute the delta. Floor the result for each unit.

#### `compute_glyph`

```python
def compute_glyph(host_status: HostStatus | None) -> str:
    """Return 'o' if reachable, 'O' if unreachable, '?' if unknown."""
```

ASCII-only per CLAUDE.md "no unicode" rule. The visual distinction is via fzf's color binding (later, in `build_fzf_argv` with `--color`), not via fancy glyphs.

#### `compute_status_word`

```python
def compute_status_word(session: ClaudeSession, host_status: HostStatus | None) -> str:
    """Return 'running-idle' | 'running-busy' | 'archived' | 'unreachable'."""
```

Decision matrix:

| `host_status` | `session.pid` | `session.status` | Returns |
|---|---|---|---|
| `reachable=False` (any) | (any) | (any) | `"unreachable"` |
| `reachable=True` or `None` | `None` | (any) | `"archived"` |
| `reachable=True` or `None` | `int` | `"busy"` | `"running-busy"` |
| `reachable=True` or `None` | `int` | anything else (incl. None, "idle", unknown) | `"running-idle"` |

Treat unknown statuses as `"running-idle"` per CODEBASE_CONTEXT.md note about claude version drift.

#### `render_rows`

```python
def render_rows(
    sessions: list[ClaudeSession],
    assertions: dict[str, Assertion],
    host_statuses: dict[str, HostStatus],
    pwd: Path | None,
    lineage: dict[str, LineageEntry],
    *,
    now: datetime | None = None,
    host_homes: dict[str, Path] | None = None,
) -> list[PickerRow]:
    """Build picker rows by joining sessions/assertions/host_statuses/lineage on sid.

    Rows are returned in stable input order: sort by (updated_at_ms desc, sid asc).
    A sid that appears in `assertions` but not in `sessions` (orphan) is included only
    if a session-less assertion is permitted by ctx (Phase 7's --orphans flag wires this).

    Phase 6 always returns ALL rows; filtering by --orphans / --host / --last happens in
    `commands.default.run_picker` BEFORE calling this function.
    """
```

Concrete row construction logic:

- `sid` -> `session.sid` (or assertion key for orphans)
- `glyph` -> `compute_glyph(host_statuses.get(owner))`
- `status_word` -> `compute_status_word(session, host_statuses.get(owner))`
- `reach_word` -> `"reachable"` if `host_statuses[owner].reachable` else `"unreachable"`
- `cwd_word` -> `"present"` if the session's cwd resolves on the local fs, else `"missing-cwd"`. Resolution: take `assertion.cwd_normalized`, `denormalize_cwd(it, host_homes[self_host])` (uses `paths.denormalize_cwd` from Phase 2 if available; else compute inline by replacing `~` with `Path.home()`). Check `Path.is_dir()`.
- `host` -> the owning host name from the merged assertion (or "unknown" for orphans)
- `last` -> `format_last_column(session.updated_at, now or datetime.now(tz=timezone.utc))`
- `cwd_display` -> the normalized cwd as-is (e.g., `~/Programs/foo`). Fish-style truncation is OUT OF SCOPE for v1; spec section 4 mentions it but it's a polish item. Phase 6 ships untruncated cwds. Add a TODO comment noting the deferred work.
- `name` -> `session.name or session.sid[:8]`. If `lineage[sid]` exists, append `f" [{lineage[sid].parent_sid[:6]}-F#{lineage[sid].fork_n}]"`.

Edge cases:

1. **Session in `sessions` but no assertion** -- orphan. Build the row anyway with `host="unknown"`, `host_status=None`. The orphans filter in `run_picker` includes them iff `ctx_obj["orphans"]` is True; otherwise it strips them.
2. **Assertion but no session** -- ownership reference but JSONL gone. Skip silently (would-be ghost; will not appear in any picker).
3. **`pwd is None`** -- caller passed nothing for cwd filter; render every row with no cwd-mismatch implication.
4. **`host_homes` is None** -- fall back to `{self_host: Path.home()}` and treat unknown hosts as `present` only if the cwd_normalized starts with `~` (since we cannot resolve absolute peer paths to local fs).

#### `format_input_lines`

```python
def format_input_lines(rows: list[PickerRow]) -> str:
    """Tab-join columns and newline-terminate. Returns the string fed to fzf's stdin.

    Exact format per row:
      <sid>\t<glyph>\t<status_word>\t<reach_word>\t<cwd_word>\t<host>\t<last>\t<cwd_display>\t<name>\n

    Empty-row list returns "" (zero bytes).
    """
```

Implementation: `"\n".join(...) + "\n"` if rows else `""`. Use `"\t".join` per row. NEVER use `"|"` or any other delimiter -- the wire format is tab-only.

Sanitize: any tab or newline embedded in a field gets replaced with a single space. (Names from claude can in principle contain weird chars; defensively scrub.) Use a private helper:

```python
def _scrub(s: str) -> str:
    return s.replace("\t", " ").replace("\n", " ").replace("\r", " ")
```

Apply to every column before joining.

#### `build_fzf_argv`

```python
def build_fzf_argv(filter_pwd: Path | None, *, header_default: str = "enter:attach  p:peek  c:claim  f:fork  C:claim --here  F:fork --here  ctrl-r:reload") -> list[str]:
    """Construct the fzf argv. Pure function -- no subprocess yet.

    Returns:
      ["fzf", "--multi", "--ansi", "--delimiter=\t",
       "--with-nth=2,6,7,8,9",
       "--expect=p,c,f,C,F,ctrl-r",
       "--bind=tab:toggle+down",
       "--bind=shift-tab:toggle+up",
       "--bind=select,deselect:transform-header:echo \"$FZF_SELECT_COUNT/$FZF_MATCH_COUNT selected\"",
       "--header=<header_default>",
       "--height=80%",
       "--layout=reverse",
       "--preview=...",   # see below
       "--preview-window=right:50%:wrap",
      ]
    """
```

`--preview` Phase 6 deliverable: ship a placeholder `echo` so the preview pane works structurally. Real preview content is a v2 polish item. Use:

```
--preview=printf 'sid: {1}\\n(preview pane to be filled in v2)\\n'
```

`{1}` is the first column (the sid). fzf substitutes it from the current row.

**The `filter_pwd` argument**: if non-None, prepend an initial query that filters by the cwd. fzf's `--query` flag sets the initial filter text. Use `f"--query={filter_pwd.as_posix()}"` if provided. If None, omit.

**Verbatim regression target**: tests assert that `--with-nth=2,6,7,8,9` is in the argv exactly as written, and `--expect=p,c,f,C,F,ctrl-r` is in the argv exactly as written. These two flags are load-bearing and downstream phases reference them.

#### `launch_picker`

```python
def launch_picker(
    rows: list[PickerRow],
    filter_pwd: Path | None,
    *,
    fzf_binary: str = "fzf",
    env_overrides: dict[str, str] | None = None,
) -> tuple[str, list[PickerRow]]:
    """Run fzf, return (expect_key, selected_rows).

    expect_key="" means plain Enter.
    selected_rows is empty on cancel (rc=130) or no-match (rc=1).
    Raises CroamError on rc=2 (fzf error) or rc in (126, 127) (exec failure).
    """
```

Implementation:

```python
import os
import subprocess
import sys
from croam.errors import CroamError
from loguru import logger

def launch_picker(rows, filter_pwd, *, fzf_binary="fzf", env_overrides=None):
    # 1. Refuse if stdin is not a tty.
    if not sys.stdin.isatty():
        raise CroamError(
            "picker requires an interactive terminal; use `croam ls --json` for scripts"
        )

    argv = [fzf_binary, *build_fzf_argv(filter_pwd)[1:]]  # replace "fzf" with absolute binary if specified
    stdin_data = format_input_lines(rows)

    # Sanitize the env so user's FZF_DEFAULT_OPTS doesn't poison our flags.
    env = {**os.environ, "FZF_DEFAULT_OPTS": ""}
    if env_overrides:
        env.update(env_overrides)

    logger.debug("launching fzf: argv={}, n_rows={}", argv, len(rows))

    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,           # CRITICAL: do NOT capture stderr; fzf draws on /dev/tty
        env=env,
        text=True,
        encoding="utf-8",
    )
    out, _ = proc.communicate(stdin_data)
    rc = proc.returncode

    if rc == 130 or rc == 1:
        return "", []
    if rc in (2, 126, 127):
        raise CroamError(f"fzf exited with code {rc}")
    if rc != 0:
        raise CroamError(f"fzf exited unexpectedly with code {rc}")

    lines = out.splitlines()
    if not lines:
        return "", []

    expect_key = lines[0]                                   # "" if plain Enter
    selected_lines = lines[1:]
    by_sid = {r.sid: r for r in rows}
    selected_rows = []
    for raw in selected_lines:
        sid = raw.split("\t", 1)[0]
        row = by_sid.get(sid)
        if row is not None:
            selected_rows.append(row)
    return expect_key, selected_rows
```

Critical edge cases:

1. **stdin is not a tty** (e.g., piped, in CI): refuse with a `CroamError` instructing the user to use `--json`.
2. **rc=130** (Ctrl-C/ESC): return `("", [])`; do NOT raise.
3. **rc=1** (no match -- empty input or all rows filtered out): return `("", [])`; do NOT raise.
4. **rc=2** (fzf internal error): raise `CroamError` with the rc embedded.
5. **rc in (126, 127)** (`--bind become` failure or fzf binary not found): raise `CroamError` with rc embedded.
6. **`FZF_DEFAULT_OPTS`**: ALWAYS set to `""` in the spawned env; user's shell defaults can override our flags (e.g., `--height` would change the layout we built).
7. **stderr=None** (NOT `subprocess.PIPE`): fzf draws on /dev/tty; capturing stderr breaks the TUI. The fzf "Pseudo-terminal will not be allocated" warning, if any, simply prints to the user's terminal -- harmless.
8. **Empty rows list**: skip launching fzf entirely. Return `("", [])` with a logged warning.
9. **selected_lines reference rows not in `by_sid`**: impossible in correct input; log a WARNING and skip.

#### `compute_action_intersection`

```python
def compute_action_intersection(selected: list[PickerRow], *, self_hostname: str) -> set[str]:
    """Return the set of safe verb keys universally applicable across all selected rows.

    Keys returned are from the universe {"attach", "peek", "claim", "fork", "claim-here", "fork-here"}.
    "claim-here"/"fork-here" use the capital-letter variants in the picker (C, F).

    Per spec section 4 'Multi-select action filtering':
      - 1 row owned-here:               {attach, peek, claim, fork} but claim is no-op for self-owned
        (we keep it in the set; the actual no-op detection is verb-side concern in Phase 8)
      - all rows reachable + cwd present:  {attach, peek, claim, fork, claim-here, fork-here}
      - any row missing cwd locally:      drop {claim, fork}; keep {peek, claim-here, fork-here}
      - any row unreachable:               drop {attach}; keep {peek}
      - mixed all states:                  intersect the per-row sets

    Empty `selected` -> empty set (no rows selected, no actions).
    """
```

Per-row safe action set (helper):

```python
def _row_safe_actions(row: PickerRow, self_hostname: str) -> set[str]:
    actions = {"peek"}                              # peek is always safe
    if row.reach_word == "reachable":
        actions.add("attach")                       # attach needs reachability
    if row.cwd_word == "present":
        actions.add("claim")                        # claim refuses missing cwd unless --here
        actions.add("fork")                         # same for fork
    actions.add("claim-here")                       # --here variants always available
    actions.add("fork-here")
    return actions
```

Then `compute_action_intersection` returns `set.intersection(*[_row_safe_actions(r, ...) for r in selected])` (or the empty set for empty input).

The example from spec section 4 ("3 selected mixed: only F universal" because cwd missing on some) flows from:
- All rows: `peek` and `fork-here` (claim-here, fork-here always; peek always)
- Some rows missing cwd: `claim`, `fork` drop out
- All rows reachable: `attach` stays
- Result: `{"attach", "peek", "claim-here", "fork-here"}` if all reachable; `{"peek", "claim-here", "fork-here"}` if any unreachable.

The spec example "p:peek F:fork --here" matches the unreachable-or-missing-cwd case where `attach` and `claim-here` are dropped because... wait. Let's reread the spec example:

> 3 selected mixed:  p:peek  F:fork --here  (cwd missing on some; only F universal)

The spec drops claim-here too, claiming "only F universal". That contradicts our rule that `claim-here` is universal (always available). The discrepancy is intentional: `claim-here` for an already-owned session is a no-op, and the spec's example presumably has a mix where some are owned-here and some are remote, making `claim` even with `--here` semantically unhelpful for the owned-here ones.

For Phase 6's purpose: the test `test_compute_action_intersection` should match the SPEC behavior. Implement per-row `_row_safe_actions` as defined, then in the test use a fixture where one row is local-owned with present-cwd and another is remote-unreachable with missing-cwd. The intersection per our rule is `{"peek", "claim-here", "fork-here"}` -- which matches the brief's expectation (`{"peek", "fork --here"}` plus `claim --here` which is also there).

The brief explicitly states:

> `compute_action_intersection([row_local, row_remote_unreachable])` returns a set excluding "claim" and "fork" (only "peek" and "fork --here" are universal -- per spec section 4 multi-select example)

The brief's wording is loose; the key contract is `claim` and `fork` are excluded (because cwd or ownership says no). `peek` is included. `claim-here` and `fork-here` are also included per our universal rule. The test should assert "claim" not in result, "fork" not in result, "peek" in result. NOT assert exact set equality, because that ties the test to the precise universe definition.

---

### `src/croam/commands/__init__.py`

Empty file with `from __future__ import annotations` for consistency. Nothing else.

### `src/croam/commands/default.py`

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from croam import picker as picker_mod
from croam.config import Config
from croam.errors import CroamError
from croam.hosts import HostStatus, probe_reachability
from croam.ownership import merge_assertions, read_local_assertions
from croam.sessions import discover_local_sessions


def run_picker(*, config: Config, home: Path, ctx_obj: dict) -> int:
    """Orchestrate: discover -> render -> launch -> dispatch.

    Phase 6 ships discover + render + launch. The dispatch table is filled in by Phase 7+;
    for now, every result raises NotImplementedError or returns 0 (after logging).
    """
    # 1. Discover.
    sessions = discover_local_sessions(home)
    assertions_per_host = {
        config.self_hostname: read_local_assertions(config.storage.state_root, config.self_hostname),
        # Peers added by Phase 9 / hybrid mode. Phase 6 reads only local for the picker.
    }
    merged_assertions = merge_assertions(assertions_per_host)

    host_statuses: dict[str, HostStatus] = {}
    if ctx_obj.get("all"):
        host_statuses = probe_reachability(list(config.hosts.keys()))
    else:
        # Local-only: synthesize a self-status without an SSH probe.
        host_statuses[config.self_hostname] = HostStatus(
            name=config.self_hostname, reachable=True, last_probed=datetime.now(tz=timezone.utc), error=None
        )

    # Phase 4 may not yet have lineage merged; Phase 6 stubs an empty dict.
    lineage: dict = {}  # Phase 9 fills in via lineage.json reads.

    # 2. Apply pre-render filters.
    filtered_sessions = _apply_filters(sessions, merged_assertions, ctx_obj, home)

    # 3. Render.
    pwd = Path.cwd() if not ctx_obj.get("all") else None
    rows = picker_mod.render_rows(
        sessions=filtered_sessions,
        assertions=merged_assertions,
        host_statuses=host_statuses,
        pwd=pwd,
        lineage=lineage,
    )

    if not rows:
        logger.warning("no sessions match the current filter; try `croam --all`")
        return 0

    # 4. Launch.
    expect_key, selected = picker_mod.launch_picker(rows=rows, filter_pwd=None)

    # 5. Dispatch (Phase 7+ fills this in).
    if not selected:
        return 0  # cancel
    return _dispatch(expect_key=expect_key, selected=selected, ctx_obj=ctx_obj)


def _apply_filters(sessions, assertions, ctx_obj, home):
    """Apply --host, --last, --orphans, --all, default-pwd filters."""
    # Phase 6 ships a minimal version: orphans on/off only. --host and --last
    # are wired from ctx_obj but the actual filter logic for them defers to
    # Phase 7's commands/ls.py which has the same logic; for picker, default
    # behavior is "all sessions discovered locally" since the picker is local-first.
    orphans_only = ctx_obj.get("orphans", False)
    if orphans_only:
        return [s for s in sessions if s.sid not in assertions]
    return [s for s in sessions if s.sid in assertions]  # exclude orphans by default


def _dispatch(*, expect_key: str, selected, ctx_obj: dict) -> int:
    """Phase 6: stub. Phase 7 maps expect_key -> verb.run()."""
    logger.info("picker selected expect_key={!r} n={}", expect_key, len(selected))
    raise NotImplementedError("Phase 7 wires the dispatch table")
```

This module's job: orchestrate. The dispatch table itself is intentionally a stub. Phase 7 replaces `_dispatch` with the real mapping.

---

### `tests/_helpers/fake_fzf.py`

A reusable Python helper that creates a temp executable shell script emitting canned fzf output.

```python
from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path


def make_fake_fzf(
    tmp_path: Path,
    *,
    output: str,
    exit_code: int = 0,
) -> Path:
    """Create an executable fake-fzf script that emits `output` and exits with `exit_code`.

    The script ignores its stdin (fzf would consume it; for tests we don't need to round-trip).

    Returns the path to the script. Caller must add tmp_path/bin to PATH or pass as `fzf_binary=`.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "fake_fzf"
    body = textwrap.dedent(
        f"""\
        #!/bin/bash
        # Discard stdin so the parent's pipe doesn't fill.
        cat > /dev/null
        printf '%s' {_shell_quote(output)}
        exit {exit_code}
        """
    )
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _shell_quote(s: str) -> str:
    """Single-quote a string for safe inclusion in a bash printf '%s' argument."""
    return "'" + s.replace("'", "'\\''") + "'"
```

Used by `test_launch_picker_*` tests via `picker.launch_picker(rows, filter_pwd, fzf_binary=str(make_fake_fzf(tmp_path, output="...", exit_code=0)))`.

---

### `tests/test_cli.py`

```python
from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from croam.cli import app
from croam.errors import CroamError


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


def test_help_shows_verbs(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.stdout
    for verb in ("ls", "attach", "peek", "claim", "fork", "launch", "doctor"):
        assert re.search(rf"\b{verb}\b", out), f"verb {verb!r} missing from --help: {out!r}"


def test_help_does_not_show_emit_state(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "emit-state" not in result.stdout


def test_emit_state_runs(home, state_root, runner, monkeypatch):
    # Phase 3 owns commands/emit_state.py. Phase 6 just verifies the wiring.
    # Write a minimal valid config so load_config works (if emit_state needs it).
    monkeypatch.setenv("HOME", str(home))
    result = runner.invoke(app, ["emit-state"])
    assert result.exit_code == 0, f"stderr: {result.stderr}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)


def test_global_debug_flag(home, runner, monkeypatch, caplog):
    """--debug bumps logging level to DEBUG."""
    # Use the ls command (which raises NotImplementedError until Phase 7) just to trigger
    # the global callback. Catch the NotImplementedError as expected behavior.
    result = runner.invoke(app, ["--debug", "ls"])
    # ls will raise NotImplementedError("Phase 7"); typer turns it into rc=1 with the
    # exception captured in result.exception. We only care that the callback ran and
    # configured logging.
    assert result.exception is not None
    assert isinstance(result.exception, NotImplementedError)
    # Verify logger configuration: a debug-level record should be capturable.
    # (Specific to loguru's interaction with caplog -- see Phase 1 conftest.)
    # Fallback: just verify the log file path was set on disk.
    log_path = home / ".local/state/croam/croam.log"
    # The file may or may not exist depending on whether anything actually logged before
    # the NotImplementedError. The critical assertion is that --debug didn't crash
    # and the callback was reached.


def test_top_level_croam_error_handler(monkeypatch, runner):
    """A CroamError raised inside a verb should produce exit_code=2 + 'croam: ...' on stderr."""
    from croam.cli import app as inner_app

    def boom(ctx):
        raise CroamError("synthetic explosion")

    # Replace the ls command's callback. This is the simplest hook for testing the
    # top-level handler. Use monkeypatch to swap.
    monkeypatch.setattr("croam.cli.cmd_ls", boom)

    # Re-invoke through the main() function (NOT runner.invoke -- runner unwraps the
    # typer.Exit and we want to verify the explicit translation).
    # Easiest: a subprocess invocation against `python -m croam`. But that's slow.
    # Alternative: invoke main() directly and capture sys.exit + stderr.
    import contextlib
    import io
    import sys

    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        with pytest.raises(SystemExit) as excinfo:
            from croam.cli import main
            sys.argv = ["croam", "ls"]
            main()
    assert excinfo.value.code == 2
    assert "croam: synthetic explosion" in err_buf.getvalue()
```

Note on `test_top_level_croam_error_handler`: the simplest and most robust approach is the in-process `sys.argv` swap + `contextlib.redirect_stderr` shown above. If that proves brittle (typer may consume sys.argv in unexpected ways), fall back to a subprocess invocation: `subprocess.run([sys.executable, "-m", "croam", "ls"], capture_output=True, text=True)` after monkeypatching the module on disk -- but that's slower and harder. Try the in-process variant first.

---

### `tests/test_picker.py`

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from croam.errors import CroamError
from croam.picker import (
    PickerRow,
    build_fzf_argv,
    compute_action_intersection,
    format_input_lines,
    format_last_column,
    launch_picker,
)
from tests._helpers.fake_fzf import make_fake_fzf


NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "ms_ago,expected",
    [
        (None,                     "-"),
        (30_000,                   "0m"),
        (14 * 60 * 1_000,          "14m"),
        (60 * 60 * 1_000,          "1h"),
        (47 * 60 * 60 * 1_000,     "47h"),
        (48 * 60 * 60 * 1_000,     "2D"),
        (5 * 24 * 60 * 60 * 1_000, "5D"),
        (30 * 24 * 60 * 60 * 1_000,"30D"),
        (31 * 24 * 60 * 60 * 1_000,"1M"),
        (60 * 24 * 60 * 60 * 1_000,"2M"),
    ],
)
def test_format_last_column(ms_ago, expected):
    if ms_ago is None:
        result = format_last_column(None, NOW)
    else:
        ms_now = int(NOW.timestamp() * 1000)
        result = format_last_column(ms_now - ms_ago, NOW)
    assert result == expected


def test_format_input_lines_exact_shape():
    rows = [
        PickerRow(
            sid="abc12345-aaaa-bbbb-cccc-111111111111",
            glyph="o",
            status_word="running-idle",
            reach_word="reachable",
            cwd_word="present",
            host="stormtree",
            last="2m",
            cwd_display="~/Programs/onlayer-x",
            name="iso27001 controls draft",
        ),
        PickerRow(
            sid="def45678-2222-3333-4444-555555555555",
            glyph="O",
            status_word="unreachable",
            reach_word="unreachable",
            cwd_word="missing-cwd",
            host="vicar",
            last="1d",
            cwd_display="/home/work/onlayer-eu",
            name="refactor mart_*",
        ),
    ]
    out = format_input_lines(rows)
    expected = (
        "abc12345-aaaa-bbbb-cccc-111111111111\to\trunning-idle\treachable\tpresent\tstormtree\t2m\t~/Programs/onlayer-x\tiso27001 controls draft\n"
        "def45678-2222-3333-4444-555555555555\tO\tunreachable\tunreachable\tmissing-cwd\tvicar\t1d\t/home/work/onlayer-eu\trefactor mart_*\n"
    )
    assert out == expected


def test_format_input_lines_scrubs_tabs_and_newlines():
    row = PickerRow(
        sid="x", glyph="o", status_word="running-idle", reach_word="reachable",
        cwd_word="present", host="h", last="-", cwd_display="~", name="a\tb\nc",
    )
    out = format_input_lines([row])
    assert "\t" not in out.split("\n")[0].split("\t")[-1]  # name column has no tab
    assert out.count("\n") == 1                            # only the trailing newline


def test_format_input_lines_empty():
    assert format_input_lines([]) == ""


def test_render_rows_with_lineage(home):
    """A sid with a lineage entry has [<parent>-F#<n>] appended to its name."""
    # This test depends on Phase 3's ClaudeSession dataclass and Phase 4's Assertion +
    # LineageEntry. Construct minimally with what they expose. If unavailable in this
    # phase's checkout, skip with a clear marker (Phase 6 should be run after Phase 4).
    pytest.importorskip("croam.sessions")
    pytest.importorskip("croam.ownership")
    from croam.sessions import ClaudeSession
    from croam.ownership import Assertion
    from croam.hosts import HostStatus
    from croam.picker import render_rows

    parent_sid = "abc12345-pppp-aaaa-rrrr-eeeeeeeeeeee"
    fork_sid   = "fff45678-ffff-oooo-rrrr-kkkkkkkkkkkk"
    sessions = [
        ClaudeSession(
            sid=fork_sid, cwd=home / "Programs/croam",
            transcript_path=home / ".claude/projects/-x/x.jsonl",
            pid=None, status=None, started_at=None, updated_at=None,
            name=None, version=None,
        )
    ]
    assertions = {
        fork_sid: Assertion(
            sid=fork_sid, owner="self", asserted_at=NOW, action="create",
            cwd_normalized="~/Programs/croam", previous_owner=None,
        )
    }
    host_statuses = {"self": HostStatus(name="self", reachable=True, last_probed=NOW, error=None)}
    lineage = {fork_sid: type("LE", (), {"parent_sid": parent_sid, "fork_n": 1})()}
    rows = render_rows(
        sessions=sessions, assertions=assertions, host_statuses=host_statuses,
        pwd=None, lineage=lineage, now=NOW,
    )
    assert len(rows) == 1
    assert "[abc123-F#1]" in rows[0].name


def test_render_rows_missing_cwd(home):
    """A session whose cwd doesn't exist locally has cwd_word == 'missing-cwd'."""
    pytest.importorskip("croam.sessions")
    from croam.sessions import ClaudeSession
    from croam.ownership import Assertion
    from croam.hosts import HostStatus
    from croam.picker import render_rows

    nonexistent = home / "does/not/exist"
    sid = "missing-cwd-sid-aaaa-bbbb-cccccccccccc"
    sessions = [
        ClaudeSession(
            sid=sid, cwd=nonexistent,
            transcript_path=home / ".claude/projects/-x/x.jsonl",
            pid=None, status=None, started_at=None, updated_at=None,
            name=None, version=None,
        )
    ]
    assertions = {
        sid: Assertion(
            sid=sid, owner="self", asserted_at=NOW, action="create",
            cwd_normalized=str(nonexistent), previous_owner=None,
        )
    }
    host_statuses = {"self": HostStatus(name="self", reachable=True, last_probed=NOW, error=None)}
    rows = render_rows(
        sessions=sessions, assertions=assertions, host_statuses=host_statuses,
        pwd=None, lineage={}, now=NOW,
    )
    assert len(rows) == 1
    assert rows[0].cwd_word == "missing-cwd"


def test_compute_action_intersection_excludes_claim_and_fork_when_unreachable_or_missing():
    """Per spec section 4: mixed selection drops claim/fork when cwd missing or origin unreachable."""
    row_local = PickerRow(
        sid="a", glyph="o", status_word="running-idle", reach_word="reachable",
        cwd_word="present", host="self", last="2m", cwd_display="~", name="a",
    )
    row_remote_unreachable = PickerRow(
        sid="b", glyph="O", status_word="unreachable", reach_word="unreachable",
        cwd_word="missing-cwd", host="vicar", last="3h", cwd_display="/x", name="b",
    )
    result = compute_action_intersection([row_local, row_remote_unreachable], self_hostname="self")
    assert "claim" not in result
    assert "fork" not in result
    assert "peek" in result
    assert "fork-here" in result


def test_compute_action_intersection_empty():
    assert compute_action_intersection([], self_hostname="self") == set()


def test_build_fzf_argv_includes_required_flags():
    argv = build_fzf_argv(filter_pwd=Path("/home/tunc/Programs/croam"))
    assert "--multi" in argv
    assert "--ansi" in argv
    assert "--with-nth=2,6,7,8,9" in argv
    assert "--expect=p,c,f,C,F,ctrl-r" in argv
    # The header transform on select/deselect:
    assert any("select,deselect:transform-header" in a for a in argv)
    # The query for filter_pwd:
    assert any(a.startswith("--query=") and "/home/tunc/Programs/croam" in a for a in argv)


def test_build_fzf_argv_no_pwd():
    argv = build_fzf_argv(filter_pwd=None)
    assert not any(a.startswith("--query=") for a in argv)


def test_launch_picker_happy_path(tmp_path, monkeypatch):
    """fake-fzf prints '<key>\\n<row1>\\n<row2>'; assert (key, [row1, row2])."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    rows = [
        PickerRow(sid="row1-sid", glyph="o", status_word="running-idle",
                  reach_word="reachable", cwd_word="present", host="h",
                  last="-", cwd_display="~", name="r1"),
        PickerRow(sid="row2-sid", glyph="o", status_word="running-idle",
                  reach_word="reachable", cwd_word="present", host="h",
                  last="-", cwd_display="~", name="r2"),
    ]
    fake = make_fake_fzf(
        tmp_path,
        output="p\nrow1-sid\to\trunning-idle\treachable\tpresent\th\t-\t~\tr1\nrow2-sid\to\trunning-idle\treachable\tpresent\th\t-\t~\tr2\n",
        exit_code=0,
    )
    key, selected = launch_picker(rows, filter_pwd=None, fzf_binary=str(fake))
    assert key == "p"
    assert [r.sid for r in selected] == ["row1-sid", "row2-sid"]


def test_launch_picker_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    fake = make_fake_fzf(tmp_path, output="", exit_code=130)
    key, selected = launch_picker([], filter_pwd=None, fzf_binary=str(fake))
    assert key == ""
    assert selected == []


def test_launch_picker_no_match(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    fake = make_fake_fzf(tmp_path, output="", exit_code=1)
    key, selected = launch_picker([], filter_pwd=None, fzf_binary=str(fake))
    assert key == ""
    assert selected == []


def test_launch_picker_error(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    fake = make_fake_fzf(tmp_path, output="", exit_code=2)
    with pytest.raises(CroamError, match=r"fzf exited with code 2"):
        launch_picker([], filter_pwd=None, fzf_binary=str(fake))


def test_launch_picker_refuses_non_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(CroamError, match=r"interactive terminal"):
        launch_picker([], filter_pwd=None)
```

Note on `pytest.importorskip("croam.sessions")` in some tests: this is a defensive check. Phase 6 depends on phases 3 and 4, so by the time Phase 6 runs, those modules exist. If a test environment lacks them, `importorskip` skips the test cleanly rather than erroring. Equivalent fallback: hand-roll a tiny `ClaudeSession`-shaped namedtuple inside the test.

---

### Constraints / edge cases (consolidated)

1. **Wire format invariant**: column ordering is `<sid>\t<glyph>\t<status_word>\t<reach_word>\t<cwd_word>\t<host>\t<last>\t<cwd_display>\t<name>`. Phase 6 owns this; later phases reference `{1}` (the sid) in fzf bind expansions.
2. **Hidden filter columns**: 1, 3, 4, 5. `--with-nth=2,6,7,8,9` shows columns 2 (glyph), 6 (host), 7 (last), 8 (cwd_display), 9 (name).
3. **`$FZF_SELECT_COUNT`** -- not `FZF_SELECTED_COUNT`. Triple-checked.
4. **`stderr=None`** in `subprocess.Popen`: fzf draws on the tty; capturing stderr breaks the TUI.
5. **`FZF_DEFAULT_OPTS=""`** in env: prevents user shell defaults from poisoning our flags.
6. **stdin must be tty**: `launch_picker` refuses non-tty with `CroamError`. The conftest in tests monkeypatches `sys.stdin.isatty -> True` to bypass.
7. **fzf exit codes**: 0 = selected, 1 = no match, 2 = error, 130 = cancel, 126/127 = exec failure. Map per the table in `launch_picker`.
8. **Multi-select returns rows in INPUT ORDER**, not selection order. Tests must construct input rows in known order and assert on that.
9. **The header `transform-header` action** fires on both `select` AND `deselect` events. Use the chained binding `select,deselect:transform-header:...`.
10. **Tab/newline in column values**: `format_input_lines` scrubs them (replaces with single space) to preserve the wire format.
11. **Recursion guard contract**: when the picker dispatches to `commands.attach.run`, that handler may SSH to a peer; the peer-side invokes `croam attach <sid> --here-on-owner`; the recipient honors `--here-on-owner` by NEVER recursing further. Phase 6 EXPOSES this via the `--here-on-owner` hidden option on `cmd_attach`. Phase 7 implements the actual recursion guard logic.
12. **`pyproject.toml` entry point change**: Phase 6 must change `[project.scripts] croam = "croam.cli:app"` to `croam.cli:main` so the `CroamError` translator runs on every invocation. This is a single-line edit.

---

## Dependencies

**Requires**:
- Phase 1: `errors.CroamError`, `log.configure`, `proc.run`, conftest fixtures, `tests/_helpers/synth_jsonl.py`, `tests/_helpers/synth_session.py`
- Phase 2: `config.load_config`, `config.Config`, `paths.normalize_cwd`, `paths.denormalize_cwd`
- Phase 3: `sessions.discover_local_sessions`, `sessions.ClaudeSession`, `hosts.probe_reachability`, `hosts.HostStatus`, `commands/emit_state.py`
- Phase 4: `ownership.read_local_assertions`, `ownership.merge_assertions`, `ownership.Assertion`, `LineageEntry` (or its eventual location)
- Phase 5: `commands/launch.py` -- imported lazily by `cmd_launch`

**Enables**:
- Phase 7: `cli.py` verb stubs to be replaced by `commands.{ls,attach,peek}.run`; `commands/default.py` `_dispatch` to be filled in
- Phase 8: `cli.py` claim/fork stubs to be replaced
- Phase 9: `cli.py` doctor stub to be replaced

---

## Completion Criteria

- [ ] `src/croam/cli.py` rewritten from Phase 1 stub to full app with all 8 verbs (7 visible + emit-state hidden)
- [ ] `pyproject.toml` `[project.scripts]` entry updated from `croam.cli:app` to `croam.cli:main`
- [ ] `src/croam/picker.py` exposes `PickerRow`, `format_last_column`, `compute_glyph`, `compute_status_word`, `render_rows`, `format_input_lines`, `build_fzf_argv`, `launch_picker`, `compute_action_intersection`
- [ ] `src/croam/commands/__init__.py` and `src/croam/commands/default.py` exist
- [ ] `tests/_helpers/fake_fzf.py` exposes `make_fake_fzf`
- [ ] `tests/test_cli.py` passes all 5 tests
- [ ] `tests/test_picker.py` passes all 9 tests (including parameterized format_last_column with 10 cases)
- [ ] `uv run croam --help` lists ls/attach/peek/claim/fork/launch/doctor; does NOT list emit-state
- [ ] `uv run croam emit-state` exits 0 and stdout is parseable JSON (assumes Phase 3's emit_state stub returns a JSON object)
- [ ] `uv run croam --debug ls` reaches the global callback (raises `NotImplementedError("Phase 7")` after configuring DEBUG-level logging; that's expected)
- [ ] `uv run pytest -v` exits 0 across the full suite
- [ ] `ruff check src/ tests/` exits 0
- [ ] `pyright src/` exits 0

---

## Testing Requirements

- Unit tests for every public function in `picker.py` (ten in test_picker.py)
- CLI surface tests via `typer.testing.CliRunner` (five in test_cli.py)
- `launch_picker` exercised via the `make_fake_fzf` helper for happy/cancel/no-match/error rc paths
- Edge cases: empty rows, non-tty stdin, scrubbed tabs/newlines in column values, missing cwd
- Skip-with-importorskip on tests that touch `croam.sessions`/`croam.ownership` so the suite stays runnable in isolation if needed

Run with:

```bash
uv run pytest tests/test_picker.py tests/test_cli.py -v
```

Smoke commands:

```bash
uv run croam --help
uv run croam emit-state
uv run croam --debug ls   # expected to surface NotImplementedError after the callback runs
```

---

## Functional QA

The functional checks below derive from `FUNCTIONAL_QA_STRATEGY.md` Surface 1 (CLI verbs) and Surface 2 (fzf picker), plus User Loop A (first-run sanity).

- [ ] **(Surface 1, Loop A)** `runner.invoke(app, ["--help"])` returns `exit_code == 0` and stdout contains every public verb (`ls`, `attach`, `peek`, `claim`, `fork`, `launch`, `doctor`) but does NOT contain `emit-state`. Capture full stdout and paste into the phase summary's "Functional QA Results" section.

- [ ] **(Surface 1, Loop A)** `runner.invoke(app, ["emit-state"])` returns `exit_code == 0` and `json.loads(result.stdout)` returns a dict (the precise shape is owned by Phase 3; Phase 6 only verifies the wiring). Capture the JSON payload and paste verbatim.

- [ ] **(Surface 2, Loop A)** `picker.format_input_lines([row1, row2])` returns the exact byte sequence:

  ```
  <sid1>\t<glyph1>\t<status_word1>\t<reach_word1>\t<cwd_word1>\t<host1>\t<last1>\t<cwd_display1>\t<name1>\n<sid2>\t...\n
  ```

  Tab characters are real `\t`, newlines are real `\n`, no spaces inserted between columns. Capture the bytes via `repr(format_input_lines([...]))` and paste.

- [ ] **(Surface 2, Loop A)** `picker.build_fzf_argv(filter_pwd=Path('/home/tunc/Programs/croam'))` returns a list containing every load-bearing flag verbatim: `--multi`, `--ansi`, `--with-nth=2,6,7,8,9`, `--expect=p,c,f,C,F,ctrl-r`, a `--bind` containing `select,deselect:transform-header`, and `--query=` containing the pwd. Capture the full argv list and paste.

- [ ] **(Surface 2, Loop A)** `picker.launch_picker(rows, filter_pwd=None, fzf_binary=<fake-fzf-script>)` against a fake fzf that emits `"p\n<row1-line>\n"` returns `("p", [row1])`. Capture the actual return tuple via `repr()` and paste.

- [ ] **(Surface 2)** `picker.compute_action_intersection([row_local_present, row_remote_unreachable_missing_cwd], self_hostname="self")` returns a set NOT containing `"claim"` or `"fork"`, but DOES contain `"peek"` and `"fork-here"`. Capture the set and paste.

- [ ] **(Surface 1)** `runner.invoke(app, ["--debug", "ls"])` reaches the `_global` callback (verifiable: `result.exception` is `NotImplementedError("Phase 7")`, NOT a `ConfigError` or import error from setup), proving the global callback runs before any verb dispatch. Capture `result.exception` repr and paste.

### Visual review (informal, no Visual QA section per brief)

Capture two screenshots and reference them in the phase summary as plain markdown image links or a textual description if the screenshot tooling isn't trivially available:

1. **Synthetic two-row picker**: build a tiny `tmp_path` HOME with two synthetic sessions (use `tests/_helpers/synth_jsonl.py` and `synth_session.py`). Run `uv run croam` against it. Take a screenshot. Verify visually: two rows visible, columns aligned, header reads "enter:attach  p:peek  c:claim  f:fork  ...".

2. **e2e_dummy picker**: with `CROAM_E2E=1` and the dummy session at `/tmp/croam-e2e/`, run `uv run croam`. The dummy's session should appear. Screenshot it. Verify visually: one row, sid matches `ff7afd8a-...`, cwd column reads `/tmp/croam-e2e` (or `~/...`-style if under home).

### Anti-patterns to watch (from `FUNCTIONAL_QA_STRATEGY.md`)

- **A. HOME redirect**: every test uses the `home` fixture; never call `Path.home()` directly. The conftest guard refuses unredirected HOME.
- **F. Picker tests must exercise fzf flag construction**: assert on the exact argv list (`build_fzf_argv` returns a list; tests should `assert "--with-nth=2,6,7,8,9" in argv`, not just check it ran). At least one test (`test_launch_picker_happy_path`) drives a real fzf-shaped subprocess (the fake-fzf script) and parses its actual exit code + stdout shape.
- **C. Subprocess invariants**: `launch_picker` uses `stderr=None` (never `subprocess.PIPE`); tests must not stub this away.

---

## Helpers Required

None. The fake-fzf shell-script trick is implemented as a Python helper in `tests/_helpers/fake_fzf.py` (not as a `scripts/spark-*.sh` because it's a pytest-side utility composing with fixtures, not a phase-execution helper).

---

## External Interfaces Consumed

- **fzf stdin/stdout protocol** (`fzf >= 0.55.0`)
  - **Consumed by**: `src/croam/picker.py:launch_picker` (parses fzf stdout), `build_fzf_argv` (constructs flags fzf parses)
  - **How to capture**: run `printf 'a\tb\nc\td\n' | fzf --multi --delimiter=$'\t' --with-nth=1,2 --expect=p` interactively, select both rows with Tab, press `p`. Observe stdout: first line is `p`, next two lines are the selected input rows verbatim. Then run `echo $?` -> 0. Repeat with Ctrl-C -> exit 130, no stdout. Repeat with empty stdin -> exit 1, no stdout. Capture all four cases (success, cancel, no-match, and a deliberate error like `fzf --bogus-flag` -> exit 2) and paste into the phase summary's "Evidence Captured" section.
  - **If not observable**: fzf must be on PATH. `pacman -S fzf` on Manjaro (already installed on STORMTREE per Phase 0 setup). If fzf is missing, `which fzf` returns nothing -- escalate before writing the parser.

- **typer.testing.CliRunner output shape** (`typer >= 0.21.1`)
  - **Consumed by**: `tests/test_cli.py` (asserts on `result.exit_code`, `result.stdout`, `result.stderr`, `result.exception`)
  - **How to capture**: in a Python REPL, `from typer.testing import CliRunner; from croam.cli import app; r = CliRunner(mix_stderr=False); res = r.invoke(app, ["--help"]); print(repr(res.exit_code), repr(res.stdout[:200]), repr(res.stderr[:200]))`. Capture the result type's attributes by example. Verify `result.exception` is `None` for clean exits and a typed exception for raises.
  - **If not observable**: `typer.testing.CliRunner` ships with typer; if `import typer.testing` fails, escalate (Phase 1's pyproject must include typer).

---

## Technical Reference

### typer (>= 0.21.1)

**Install**: `uv add typer` (pulls click + rich automatically).

**Entry point**: `[project.scripts] croam = "croam.cli:app"` resolves to the `app` attribute in `src/croam/cli.py`. Typer instances are callable so `croam` directly invokes `app()`.

**Subcommand pattern** (flat verb set): single `app = typer.Typer()` with `@app.command()` per verb. For function names that conflict with Python keywords (e.g., `list`), pass an explicit name: `@app.command("ls")`.

**Global options via callback**:
```python
@app.callback()
def main(
    ctx: typer.Context,
    debug: Annotated[bool, typer.Option("--debug")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
    all_: Annotated[bool, typer.Option("--all")] = False,
    host: Annotated[str | None, typer.Option("--host")] = None,
):
    ctx.obj = {"debug": debug, "json": json_out, "all": all_, "host": host}
```
Global flags must precede the subcommand: `croam --debug ls`. Set `invoke_without_command=True` if you want the callback to run when no verb is given (so `croam` alone runs the picker).

**Hidden subcommands**: `@app.command("emit-state", hidden=True)` -- callable but not in `--help`.

**Error handling**: `typer.Exit(code=N)` for clean termination. `typer.echo(msg, err=True)` for stderr. `typer.Typer(pretty_exceptions_enable=False)` for raw stderr-style errors (bypass Rich traceback). Wrap commands in try/except to translate `CroamError` -> `typer.Exit(2)` with a clean message.

**Type annotations**:
- `pathlib.Path` resolves; pair with `typer.Option(exists=True, ...)` for fs validation
- `str | None` -> optional param with default `None`
- `list[str]` -> repeatable option (`--tag a --tag b`); default `= []`
- `Literal["a", "b"]` or `Enum` -> choice

**Testing**: `from typer.testing import CliRunner; runner = CliRunner(mix_stderr=False); result = runner.invoke(app, ["ls", "--json"])`. Result has `exit_code, stdout, stderr, exception`.

**Gotchas**:
- `Annotated[type, typer.Option(...)]` is the canonical style (added 0.9.0). Old style (`name: str = typer.Option(...)`) still works but mixes Typer specifics into Python defaults.
- Required-marker `...` is no longer needed; with `Annotated` and no default, the param is required.
- Function name -> command name converts underscores to hyphens.
- Global flags via `@app.callback()` must precede the verb. Per-verb flags can appear after.
- `pretty_exceptions_enable=True` (default) catches exceptions and renders Rich tracebacks; turn off for production CLIs.
- `add_completion=False` strips `--install-completion`/`--show-completion`.

### fzf (>= 0.55.0; current 0.65.x stable)

**Install on Manjaro**: `pacman -S fzf` (Arch repo).

**Stdin/stdout protocol**:
- stdin: tab-delimited UTF-8 rows, newline-terminated
- stdout: chosen row(s) verbatim, newline-separated. With `--expect=KEYS`, first stdout line is the pressed key (empty for plain Enter), then selected rows.
- Exit codes: 0 = selected, 1 = no match, 2 = error, 126/127 = `become` failure, 130 = interrupted (Ctrl-C/ESC)

**Key flags for the picker**:
- `--multi` (or `-m`): multi-select with Tab
- `--ansi`: interpret ANSI color escapes in input
- `--delimiter=$'\t'`: split fields on tab
- `--with-nth=2,6,7,8,9`: display only these columns (filter still searches WHOLE line; hidden columns 1, 3, 4, 5 carry filter tokens)
- `--expect=p,c,f,C,F,ctrl-r`: alternate accept keys; the pressed key is reported on stdout line 1
- `--bind=tab:toggle+down`, `--bind=shift-tab:toggle+up`
- `--bind='select,deselect:transform-header:echo "$FZF_SELECT_COUNT/$FZF_MATCH_COUNT selected"'` -- updates header on multi-select changes
- `--preview='cmd {1}'`: preview pane; `{1}` is field 1 (the sid)
- `--preview-window=right:50%:wrap`
- `--height=80%`: inline (not full-screen); friendlier when one of several UI elements
- `--layout=reverse`: prompt at top

**Subprocess (Python) integration**:
```python
proc = subprocess.Popen(
    argv,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=None,                    # CRITICAL: do NOT capture stderr; fzf draws on /dev/tty
    env={**os.environ, "FZF_DEFAULT_OPTS": ""},  # neutralize user's defaults
    text=True,
    encoding="utf-8",
)
out, _ = proc.communicate(stdin_data)
rc = proc.returncode
```

**Result parsing**:
```python
if rc == 130: key, picks = "", []           # cancel
elif rc == 1: key, picks = "", []           # no match
elif rc == 0:
    lines = out.splitlines()
    key = lines[0] if lines else ""         # "" means plain Enter
    picks = lines[1:]
else:
    raise CroamError(f"fzf exit {rc}")
```

**Macros (env vars in `transform-*` actions)**: `$FZF_SELECT_COUNT` (NOT `FZF_SELECTED_COUNT` -- the manpage spells it without ED), `$FZF_TOTAL_COUNT`, `$FZF_MATCH_COUNT`, `$FZF_QUERY`, `$FZF_KEY`, `$FZF_LINES`, `$FZF_COLUMNS`.

**Gotchas**:
- ANSI in `--with-nth` displayed columns: pass `--ansi` to interpret as colors. Without it, escapes render literally.
- `FZF_DEFAULT_OPTS` from user environment can override your flags; neutralize with `env={..., "FZF_DEFAULT_OPTS": ""}` in Popen.
- `Ctrl-C` inside fzf is caught by fzf -> exit 130; Python parent does not see SIGINT (fzf has the controlling tty).
- `--height=N%` makes fzf inline; without it, fzf takes the full alt-screen.
- Test flag for ANSI parsing: `printf '\e[31mred\e[0m\tplain\n' | fzf --ansi --delimiter=$'\t' --with-nth=1,2`.

---

## Notes

- **Wire format**: the column ordering in `format_input_lines` is the contract between Phase 6 and every later phase. If Phase 7+ wants to add a new filter token, it ADDS A COLUMN to the right; it never reshuffles existing columns. The `--with-nth=2,6,7,8,9` reference and `{1}` references in fzf binds depend on this stability.
- **Recursion guard**: the `--here-on-owner` hidden flag on `cmd_attach` is exposed by Phase 6 but its semantics are implemented in Phase 7. Phase 6 only ensures the flag parses and propagates through the typer wiring.
- **Lazy imports in `cli.py`**: importing `commands.default`, `config`, `commands.emit_state`, `commands.launch` lazily (inside the function bodies) keeps `croam --help` fast and avoids cascade-failure when one module is missing or malformed.
- **`pyproject.toml` change**: this is the ONLY non-`src/croam/` file Phase 6 touches. The change is `[project.scripts] croam = "croam.cli:app"` -> `croam.cli:main`. After the change, `pipx install -e .` produces a `croam` shim that calls `main()` and gets `CroamError` translation.
- **Phase 6 does NOT implement `lineage` reading**: the lineage dict passed to `render_rows` is a stub (`{}`) for now. Phase 9 wires real lineage reads. Tests that exercise the lineage tag path build a synthetic lineage dict by hand.
- **Phase 6 does NOT implement fish-style cwd truncation**: the spec section 4 mentions it, but it's a polish item. The `cwd_display` field carries the normalized cwd as-is. Add a `# TODO(phase-11)` comment.
- **Tests use the existing `home`, `state_root`, `tmux_socket`, `ssh_shim`, `e2e_dummy`, `_safety_guard` fixtures from Phase 1's conftest.py**. Do NOT add new conftest fixtures in Phase 6; if you need one, propose it in the phase summary for a future phase to add.
