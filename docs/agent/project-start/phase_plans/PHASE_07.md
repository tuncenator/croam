# Phase 7: Verbs: attach, peek, ls

**Feature**: project-start
**Estimated Context Budget**: ~80k tokens

**Difficulty**: medium
**Visual**: no
**Functional**: yes

**Execution Mode**: sequential
**Batch**: 5 (sole phase in this batch; depends on Phases 3, 4, 5, 6)

---

## Objective

Implement the three read-mostly verbs that make up croam's primary CLI surface:

- `croam attach <sid>` -- adopt the live session via tmux. Works locally; SSHes to the owner with a recursion guard if owner is remote and reachable.
- `croam peek <sid>` -- read-only access. Live tmux read-only when origin is reachable; static JSONL render otherwise.
- `croam ls` -- non-interactive scriptable list with `--json` mode and filter flags (`--all`, `--host`, `--last`, `--orphans`).

Phase 6 wired the typer commands as stubs; Phase 7 replaces those stubs with full implementations. Phase 7 also fills in `commands/default.run_picker` to dispatch the picker's `(expect_key, selected_rows)` to the correct verb.

The single trickiest mechanic in this phase is the **recursion guard**: when host A's `croam attach <sid>` SSHes to host B (the owner), the SSH'd-to side must NOT recurse further. The guard is the `--here-on-owner` flag: when set, the recipient treats the session as locally-owned regardless of what its `ownership.json` claims.

This phase also introduces **`--no-exec` mode**: every verb's `run()` accepts an opt-in flag (also honored as `CROAM_NO_EXEC=1` env var) that, instead of `os.execvp` / `tmux attach` / `ssh ...`, emits a JSON document with the planned argv to stdout and exits 0. This is the test harness's only window into argv-construction correctness, since `runner.invoke` cannot drive an interactive `exec()`.

---

## Deliverables

1. `src/croam/commands/attach.py` -- `run(...)` with local + remote dispatch, recursion guard, `--no-exec` plan emission.
2. `src/croam/commands/peek.py` -- `run(...)` with live read-only attach OR static transcript render fallback.
3. `src/croam/commands/ls.py` -- `run(...)` with JSON / text output, filter handling.
4. `src/croam/commands/default.py` (Phase 6 created the file with `run_picker` orchestration; Phase 7 fills in the dispatcher branch that maps `(expect_key, selected_rows)` to the right verb).
5. `src/croam/transcript.py` (NEW small module) -- `render_static_transcript(jsonl_path, *, fp=sys.stdout) -> int`: minimal `[user]` / `[assistant]` line emitter.
6. Wire all three verbs in `src/croam/cli.py` -- replace the Phase 6 stubs with `runs` from `attach`/`peek`/`ls`. **Note: Phase 6 owns `cli.py`. Phase 7 only edits the four lines per verb that wire `commands.<verb>.run` in place of `NotImplementedError`. Do not touch any other part of `cli.py`.**
7. `tests/test_attach.py`, `tests/test_peek.py`, `tests/test_ls.py`, `tests/test_transcript.py` -- full coverage per the test list below.

---

## Detailed Requirements

### 1. `src/croam/transcript.py` (NEW)

Reads the JSONL line by line, prints user prompts and assistant responses, skips everything else (attachment, file-history-snapshot, last-prompt, permission-mode, tool_use, tool_result, system).

Public API (exact signature, no deviation):

```python
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

from loguru import logger

def render_static_transcript(jsonl_path: Path, *, fp: TextIO = sys.stdout) -> int:
    """Render a claude JSONL transcript as plain `[user]` / `[assistant]` lines.

    Skips metadata records (last-prompt, permission-mode, attachment,
    file-history-snapshot, tool_use, tool_result, system, anything else).
    Returns 0 on success, 1 if the file does not exist or is unreadable.
    Phase 11 may polish (paginate, syntax-highlight, etc.). Phase 7 just makes it
    functional.
    """
```

Behavior:

- If the file does not exist: log a WARNING via `loguru.logger`, write a one-line message to `fp` (`"croam: transcript not found: <path>"`), return `1`.
- If the file is not valid UTF-8 or has lines that do not parse as JSON: skip the broken line (log it at DEBUG), continue reading.
- For each line that parses as a JSON object:
  - `type == "user"`: extract message body. The body is in `obj["message"]` which can be either a string OR a dict like `{"role": "user", "content": "..."}` OR a dict with `content` being a list of content-block objects (per Anthropic API). Implement a small extractor `_extract_text(message_field) -> str` that handles all three shapes; falls back to `json.dumps(message_field)` if the shape is unknown.
  - `type == "assistant"`: same extraction.
  - All other types: skip silently.
- Output format: exactly `f"[{role}] {text}\n"` per record. No timestamps, no metadata, no separators in v1.
- Return `0` on success.

Edge cases to test:
- Empty file -> return 0, no output
- File with only metadata records (no user/assistant) -> return 0, no output
- Unicode characters in messages -> emitted verbatim
- A `user` record whose `message` is a dict with `content` being a list with a text block: extract the text
- Non-existent file -> return 1 with one stderr line
- A line with malformed JSON sandwiched between valid lines -> skip the broken line, render the others

### 2. `src/croam/commands/attach.py`

Full module (function signature and behavior):

```python
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from croam.config import Config
from croam.errors import CroamError, SessionNotFound, SshError
from croam.hosts import probe_reachability
from croam.ownership import merge_assertions, read_local_assertions
from croam import sessions, tmux
from croam.proc import run as proc_run

def run(
    sid: str | None,
    ctx_obj: dict[str, Any],
    config: Config,
    home: Path,
    *,
    here_on_owner: bool = False,
    no_exec: bool | None = None,
) -> int:
    """Attach to a claude session by sid.

    - sid=None: fall back to picker (call `commands.default.run_picker`).
    - here_on_owner=True: the recursion guard. SSHing party set this to tell us
      to treat the session as locally-owned no matter what ownership.json says.
    - no_exec: when True (or CROAM_NO_EXEC=1 in env), emit planned argv as JSON
      to stdout instead of exec-ing. Used by tests.
    """
```

Implementation steps in order:

1. Resolve `no_exec` precedence: explicit kwarg wins; else `os.environ.get("CROAM_NO_EXEC") == "1"`; else `False`.
2. If `sid is None`: import lazily and call `commands.default.run_picker(config, home, ctx_obj)`. Return its return code. (Avoid top-level circular import: `from croam.commands import default` inside the function.)
3. Resolve owner:
   - If `here_on_owner=True`: owner is `config.self_hostname`. **Skip the ownership read entirely.** This is the recursion guard's whole job.
   - Else: read all hosts' assertions (local mirror via `read_local_assertions` for each `<state_root>/<HOSTNAME>/`), call `merge_assertions(...)`, look up `merged[sid]`. If absent -> raise `SessionNotFound(f"sid {sid} not found in any host's ownership.json")`.
4. Compute the local socket path. The tests set `CROAM_TMUX_SOCK` env var; production reads `<state_root>/tmux.sock` (per phase 5's `tmux.default_socket(config)` if it exists; else None for default). Pass `Path(os.environ["CROAM_TMUX_SOCK"])` if set, else None.
5. Branch on owner:
   - **Owner is local** (owner == config.self_hostname OR here_on_owner): build local plan.
     - Read sessions via `sessions.discover_local_sessions(home)`. Find the one with matching `sid`. If not found, treat it as archived: tmux session does NOT exist; we will need to relaunch.
     - Call `tmux.has_session(sock, f"claude-{sid}")`.
     - If `has_session` is True: plan is "tmux-attach" with argv `["tmux", *(["-S", str(sock)] if sock else []), "attach", "-t", f"claude-{sid}"]`.
     - If `has_session` is False: plan is "tmux-new-and-attach" with argv `["tmux", *(["-S", str(sock)] if sock else []), "new-session", "-A", "-s", f"claude-{sid}", "claude-real", "--resume", sid]`. (`-A` makes new-session attach if it already exists, race-safe.)
   - **Owner is remote**: probe reachability.
     - `statuses = probe_reachability([owner], timeout_s=2.0)` (single-host probe; reuses existing helper).
     - If `statuses[owner].reachable is False`: raise `SshError(f"origin {owner} unreachable; try 'croam peek {sid}' for read-only static transcript")`.
     - Else build SSH plan: `["ssh", peer_alias_for(owner, config), "croam", "attach", sid, "--here-on-owner"]`. `peer_alias_for` reads `config.hosts[owner].ssh`.
6. Execute the plan:
   - If `no_exec`: `print(json.dumps({"action": <plan_kind>, "argv": <argv>}))` to stdout and `return 0`.
   - Else: `os.execvp(argv[0], argv)`. (For ssh and tmux-attach, this replaces the current process and the user's terminal becomes the remote tmux. For tmux-new-and-attach, same.) Log the planned argv at INFO before exec.

Plan-kind strings (for the `--no-exec` JSON):
- `"tmux-attach"` -- existing local tmux session.
- `"tmux-new-and-attach"` -- launch new local tmux + attach.
- `"ssh-recurse"` -- SSH to remote owner.

### 3. `src/croam/commands/peek.py`

```python
def run(
    sid: str,
    ctx_obj: dict[str, Any],
    config: Config,
    home: Path,
    *,
    no_exec: bool | None = None,
) -> int:
```

Implementation steps:

1. Resolve `no_exec` precedence (same as attach).
2. Resolve owner via `merge_assertions`. If absent -> `SessionNotFound`.
3. Branch on (owner_locality, reachability, has_live_tmux):
   - **Owner is local AND tmux session exists** (`tmux.has_session(sock, f"claude-{sid}")` is True):
     - Plan: `"tmux-peek"` with argv `["tmux", *(["-S", str(sock)] if sock else []), "attach", "-r", "-t", f"claude-{sid}"]` (the `-r` makes it read-only).
     - Execute via `os.execvp` or emit JSON in `--no-exec`.
   - **Owner is local AND no tmux session**:
     - Plan: `"static-transcript"`. The transcript path is `home / ".claude" / "projects" / encode_cwd(<assertion.cwd_normalized resolved against host_home>) / f"{sid}.jsonl"`. Use `paths.encode_cwd` and `paths.decode_cwd` helpers from Phase 2.
     - In `--no-exec` mode: emit `{"action": "static-transcript", "argv": ["render_static_transcript", str(transcript_path)]}` and return 0. (No real argv for static render -- we use a string-array marker so tests can match.)
     - Else call `render_static_transcript(transcript_path)` and return its return code.
   - **Owner is remote AND reachable**:
     - SSH to owner with `["ssh", peer_alias_for(owner, config), "croam", "peek", sid, "--here-on-owner"]`. The remote side honors the same recursion guard as attach (peek must accept and pass through `--here-on-owner` too).
     - Plan kind: `"ssh-recurse"`.
     - Execute via `os.execvp` or emit JSON.
   - **Owner is remote AND unreachable**:
     - Read JSONL from local syncthing mirror at `<state_root>/<owner>/projects/<encoded>/<sid>.jsonl`. Use `config.state_root / owner / "projects" / encoded_cwd / f"{sid}.jsonl"`.
     - If the mirror file does not exist, raise `SshError(f"origin {owner} unreachable and no mirror at <state_root>/{owner}/projects/...")`.
     - In `--no-exec` mode: emit `{"action": "static-transcript-mirror", "argv": ["render_static_transcript", str(mirror_path)]}` and return 0.
     - Else call `render_static_transcript(mirror_path)`.

`peek` accepts `--here-on-owner` for symmetry with attach (so a remote peek doesn't recurse). When set, force the "owner is local" branch.

### 4. `src/croam/commands/ls.py`

```python
def run(
    ctx_obj: dict[str, Any],
    config: Config,
    home: Path,
) -> int:
```

This is read-only and never execs anything, so it has no `no_exec` flag.

Implementation steps:

1. Read filters from `ctx_obj`:
   - `all_hosts: bool = ctx_obj.get("all", False)`
   - `host_filter: str | None = ctx_obj.get("host")`
   - `last_window_days: int = ctx_obj.get("last", config.picker_last_window_days)`
   - `orphans: bool = ctx_obj.get("orphans", False)`
   - `json_output: bool = ctx_obj.get("json", False)`
2. Discover local sessions via `sessions.discover_local_sessions(home)`.
3. Read all hosts' assertions:
   - Always read this host's own (`config.self_hostname`).
   - If `all_hosts` is True: also read every peer subdir under `config.state_root` whose hostname is in `config.hosts`. (Use the syncthing mirror; SSH fanout in this phase is out of scope -- `--all` reads the local mirror only.)
   - Else: just this host's assertions.
4. `merged = merge_assertions(per_host)`.
5. Join sessions with merged assertions by sid:
   - For each sid in `merged`: build a row. The row's `cwd` comes from `assertion.cwd_normalized`. The row's `last_activity_iso` comes from joining with the local `sessions` list if the sid is local; else from the syncthing mirror's session JSON if available; else None.
   - For each local session NOT in `merged`: that's an orphan (transcript without backing assertion).
6. Apply filters:
   - `host_filter`: keep only rows where `assertion.owner == host_filter`.
   - `all_hosts is False AND host_filter is None`: keep only `assertion.owner == config.self_hostname`.
   - `orphans is True`: keep ONLY orphan rows. Default (`orphans=False`): hide orphans.
   - `last_window_days`: drop rows whose `last_activity_iso` is older than `now - last_window_days` (rows with `None` last_activity are kept regardless -- they're new or unknown).
   - PWD filter (only if neither `--all` nor `--host` is set, and `config.picker_default_filter == "exact-pwd"`): keep only rows whose `cwd_normalized` (resolved against `home`) equals `Path.cwd()`. Match comparison normalizes both sides (`paths.normalize_cwd` from Phase 2).
7. Emit output:
   - If `json_output`: `print(json.dumps(rows_as_dicts, indent=2, default=str))`. Schema:
     ```json
     [
       {
         "sid": "abc12345-...",
         "owner": "stormtree",
         "host_reachable": null,
         "status": "running-idle",
         "cwd": "~/Programs/croam",
         "last_activity": "2026-04-30T10:00:00Z",
         "is_orphan": false,
         "name": "iso27001 controls draft"
       }
     ]
     ```
     - `last_activity`: ISO8601 UTC string OR `null`. NEVER ms-epoch.
     - `host_reachable`: `null` for ls (no SSH probe in v1 ls; that's `croam doctor`). Reserved for future.
     - `status`: one of `"running-idle"`, `"running-busy"`, `"archived"`, `"unknown"` (when remote and we have no live signal).
   - Else (text mode): print one line per row in a deterministic format. Phase 11 may polish; Phase 7 outputs:
     ```
     <sid_short>  <owner>  <last>  <cwd>  <name>
     ```
     where `sid_short` is the first 8 chars of the sid.
8. Return 0 always (empty output is fine; absence of sessions is not an error).

### 5. `src/croam/commands/default.py` -- complete the dispatcher

Phase 6 created `run_picker` with the picker-launch orchestration but left the dispatch branch as a stub (or partially filled). Phase 7 wires the dispatch:

```python
def run_picker(config: Config, home: Path, ctx_obj: dict) -> int:
    rows = ...  # phase 6's render
    expect_key, selected_rows = launch_picker(rows, filter_pwd=...)
    if not selected_rows:
        return 0  # cancel or no-match
    return _dispatch(expect_key, selected_rows, ctx_obj, config, home)

def _dispatch(expect_key: str, selected: list[PickerRow], ctx_obj, config, home) -> int:
    from croam.commands import attach, peek
    # Phase 8 imports for claim, fork

    # Single-row dispatch
    if len(selected) == 1:
        sid = selected[0].sid
        if expect_key == "":
            return attach.run(sid, ctx_obj, config, home)
        if expect_key == "p":
            return peek.run(sid, ctx_obj, config, home)
        if expect_key == "c":
            raise NotImplementedError("Phase 8: claim")
        if expect_key == "f":
            raise NotImplementedError("Phase 8: fork")
        if expect_key == "C":
            raise NotImplementedError("Phase 8: claim --here")
        if expect_key == "F":
            raise NotImplementedError("Phase 8: fork --here")
        if expect_key == "ctrl-r":
            return run_picker(config, home, ctx_obj)  # reload by re-running

    # Multi-row dispatch
    intersection = compute_action_intersection(selected)
    requested = expect_key or "attach"
    if requested not in intersection:
        # phase 6 owns the inline refusal; phase 7 just exits non-zero with stderr
        typer.echo(f"croam: action '{requested}' not safe for all selected rows", err=True)
        return 3
    # iterate over selected rows, dispatching the same verb to each
    for row in selected:
        rc = ...  # call attach/peek per requested
        if rc != 0:
            return rc
    return 0
```

Phase 7 implements the attach/peek branches and the multi-row iteration. The claim/fork branches stay as `raise NotImplementedError("Phase 8: ...")` -- Phase 8 fills them.

Phase 7 does NOT need to implement keyboard refusal in the picker UI itself (Phase 6 owns that via fzf header). Phase 7 only handles the case where we somehow get an out-of-intersection key -- defensive.

### 6. CLI wiring (`src/croam/cli.py`)

Phase 6 created `cli.py` with:

```python
@app.command("attach")
def cmd_attach(...):
    raise NotImplementedError("Phase 7")

@app.command("peek")
def cmd_peek(...):
    raise NotImplementedError("Phase 7")

@app.command("ls")
def cmd_ls(...):
    raise NotImplementedError("Phase 7")
```

Phase 7 replaces those bodies with calls into the new modules. The signature of each typer command must be:

```python
@app.command("attach")
def cmd_attach(
    ctx: typer.Context,
    sid: str | None = typer.Argument(None, help="session UUID; omit to open the picker"),
    here_on_owner: bool = typer.Option(False, "--here-on-owner", hidden=True, help="recursion guard"),
    no_exec: bool = typer.Option(False, "--no-exec", hidden=True, help="emit planned argv as JSON instead of executing"),
) -> None:
    from croam.commands import attach
    config = ctx.obj["config"]
    home = ctx.obj["home"]
    rc = attach.run(sid, ctx.obj, config, home, here_on_owner=here_on_owner, no_exec=no_exec)
    raise typer.Exit(rc)
```

Same shape for peek (with `sid: str` required, plus `--here-on-owner` and `--no-exec`) and ls (no sid, no `--no-exec`, no `--here-on-owner`).

**Important: do not modify any other part of `cli.py`.** Phase 6 owns the file. Phase 7 only fills these three command body blocks.

### 7. Implementation order

Implement in this order, committing between each:

1. `src/croam/transcript.py` + `tests/test_transcript.py`. Self-contained, no dependencies. Easiest to get green first.
2. `src/croam/commands/ls.py` + `tests/test_ls.py`. Simplest verb (no exec, no SSH, just JSON).
3. `src/croam/commands/peek.py` + `tests/test_peek.py`. Medium complexity (read-only attach OR static render OR mirror read).
4. `src/croam/commands/attach.py` + `tests/test_attach.py`. Most complex (recursion guard + remote SSH + tmux dispatch).
5. Wire all three into `cli.py` (replace stubs) and verify `runner.invoke(app, [...])` round-trips.
6. Fill in `commands/default.py:_dispatch` for attach/peek branches; multi-row iteration.

---

## Edge cases (explicit, must each have a test)

- **`attach <sid>` with sid not present in any ownership.json**: raise `SessionNotFound`. CLI exits 2.
- **`attach <sid>` with `--here-on-owner` set but local session JSONL absent**: still treat as local; tmux dispatch will simply create a new tmux session via `--resume <sid>`. Claude itself decides whether to find an existing transcript.
- **`attach <sid>` recursion guard inversion**: `--here-on-owner` set AND ownership.json says owner is some OTHER host. Behavior: still treat as local. Do NOT recurse via SSH. (This is the whole point of the guard. If the data is inconsistent, treating-as-local at least produces a deterministic outcome.)
- **`attach` on a local session that's already tmux-attached**: tmux supports multiple attaches. The plan doesn't change. Test with `tmux.has_session=True` and assert the same argv.
- **`attach` remote, peer reachable, but SSH command itself has a typo in alias**: out of scope; the user's `~/.ssh/config` is responsible. Test only the in-process argv assembly.
- **`peek` of a sid not in ownership.json**: raise `SessionNotFound`.
- **`peek` of a remote unreachable session whose mirror also doesn't exist**: raise `SshError` with helpful message.
- **`peek` of a local archived session**: `tmux.has_session=False` -> static transcript path. Verify path encoding via `paths.encode_cwd`.
- **`ls --json` with no sessions at all**: returns `[]`. Test exact stdout: `runner.invoke(app, ["ls", "--json"]).stdout.strip() == "[]"`.
- **`ls` text mode, no sessions**: empty stdout, exit 0.
- **`ls --orphans` with no orphans**: returns `[]`.
- **`ls --orphans` AND a non-orphan also matches the cwd filter**: only the orphan is shown.
- **`ls` with both `--all` and `--host vicar`**: returns only vicar's sessions across the local mirror (host filter wins inside the all-hosts merge).
- **`ls --last 0`**: drops every row with `last_activity` older than now (i.e., everything with non-null timestamp). Rows with `last_activity=null` still appear.
- **Picker dispatch with multi-row selection, all rows local-owned, expect key empty (Enter)**: iterate over rows, attach each one in sequence. (Realistically attach-multiple is weird; we exit on first non-zero rc. Document this as v1 behavior.)
- **Picker dispatch with `expect_key=ctrl-r`**: re-run `run_picker` recursively. Bound recursion depth in tests is fine; production users press it deliberately.
- **Static transcript with a non-utf8 byte in the JSONL**: log at DEBUG, skip the line, continue.

---

## Dependencies

**Requires**:
- Phase 1: `src/croam/errors.py` (CroamError, SshError, SessionNotFound, OrphanRefused), `src/croam/log.py` (configure), `src/croam/proc.py` (proc.run), conftest fixtures (home, tmux_socket, ssh_shim, state_root, synthetic builders).
- Phase 2: `src/croam/paths.py` (encode_cwd, decode_cwd, normalize_cwd), `src/croam/config.py` (Config dataclass).
- Phase 3: `src/croam/sessions.py` (discover_local_sessions, ClaudeSession), `src/croam/hosts.py` (probe_reachability).
- Phase 4: `src/croam/ownership.py` (read_local_assertions, merge_assertions, Assertion).
- Phase 5: `src/croam/tmux.py` (has_session, the socket-passing convention).
- Phase 6: `src/croam/cli.py` (the typer app and existing stubs), `src/croam/picker.py` (PickerRow, launch_picker, compute_action_intersection), `src/croam/commands/default.py` (run_picker with the launch logic in place).

**Enables**:
- Phase 8: claim/fork can replace the `NotImplementedError` branches in `commands/default.py:_dispatch` and reuse the same `--no-exec` testing pattern.
- Phase 10: integration tests can drive `attach`/`peek`/`ls` end-to-end against the synthetic two-host fixture.

---

## Completion Criteria

- [ ] `src/croam/transcript.py` exists with `render_static_transcript(jsonl_path, *, fp=sys.stdout) -> int`.
- [ ] `src/croam/commands/{attach,peek,ls}.py` exist with the public `run(...)` entry points described above.
- [ ] `src/croam/commands/default.py:_dispatch` handles attach + peek + ctrl-r single-row, attach + peek multi-row, and raises `NotImplementedError` for claim/fork (Phase 8).
- [ ] `src/croam/cli.py:cmd_attach`, `cmd_peek`, `cmd_ls` call into the new modules instead of raising `NotImplementedError`. No other lines in `cli.py` are touched.
- [ ] All tests in `tests/test_attach.py`, `tests/test_peek.py`, `tests/test_ls.py`, `tests/test_transcript.py` pass.
- [ ] `uv run pytest tests/test_attach.py tests/test_peek.py tests/test_ls.py tests/test_transcript.py -q` reports 0 failures.
- [ ] `uv run pytest --cov=src/croam/commands/attach --cov=src/croam/commands/peek --cov=src/croam/commands/ls --cov=src/croam/transcript --cov-report=term-missing` reports >= 90% line coverage on each of the four modules.
- [ ] `uv run croam ls --json` against the conftest synthetic fixture returns parseable JSON (manually verified in summary).
- [ ] `uv run croam attach <sid> --no-exec` against a synthetic local session returns the planned tmux argv (manually verified in summary).
- [ ] No use of `print()` inside `src/croam/` except where stdout IS the protocol (the `--no-exec` JSON emission, the `ls` JSON/text output, the static transcript rendering). Everywhere else uses `loguru.logger`.
- [ ] No `Path.home()` or `os.path.expanduser("~")` in production code. Only `home: Path` parameters.
- [ ] All paths normalized via `paths.encode_cwd` / `paths.normalize_cwd`. No ad-hoc string replacement.

---

## Testing Requirements

### `tests/test_transcript.py`

- `test_render_empty_file(tmp_path)`: empty file -> return 0, no output.
- `test_render_metadata_only(tmp_path)`: file with only `last-prompt` and `permission-mode` records -> return 0, no output.
- `test_render_user_string_message(tmp_path)`: a user record with `message="hello"` -> stdout is `"[user] hello\n"`.
- `test_render_user_dict_content_string(tmp_path)`: a user record with `message={"role": "user", "content": "hi"}` -> stdout is `"[user] hi\n"`.
- `test_render_user_dict_content_blocks(tmp_path)`: a user record with `message={"role": "user", "content": [{"type": "text", "text": "block"}]}` -> stdout is `"[user] block\n"`.
- `test_render_assistant_message(tmp_path)`: assistant record -> stdout starts with `"[assistant] "`.
- `test_render_skips_other_types(tmp_path)`: file with attachment, file-history-snapshot, tool_use -> only user/assistant lines emitted.
- `test_render_unicode(tmp_path)`: a user message with `"こんにちは"` -> emitted verbatim.
- `test_render_malformed_line_skipped(tmp_path)`: file with `{not json}` between two valid records -> the two valid records render, the bad one is skipped.
- `test_render_missing_file(tmp_path, capsys)`: returns 1, stderr/stdout has a one-line message containing `"transcript not found"`.

### `tests/test_attach.py`

All tests use `runner = typer.testing.CliRunner(mix_stderr=False)` and `runner.invoke(app, [...])`.

- `test_attach_local_session_running(home, tmux_socket, monkeypatch)`:
  - Set `monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))`.
  - Build synthetic local session sid + ownership.json with `owner=self`.
  - Pre-create the tmux session: `subprocess.run(["tmux", "-S", str(tmux_socket), "new-session", "-d", "-s", f"claude-{sid}", "/bin/sleep", "60"])`. Tear down with `tmux kill-session` in a finally / fixture cleanup.
  - Invoke: `runner.invoke(app, ["attach", sid, "--no-exec"])`.
  - Assert `result.exit_code == 0`, `json.loads(result.stdout) == {"action": "tmux-attach", "argv": ["tmux", "-S", str(tmux_socket), "attach", "-t", f"claude-{sid}"]}`.
- `test_attach_local_session_archived(home, tmux_socket, monkeypatch)`:
  - Synthetic session; no pre-existing tmux.
  - `runner.invoke(app, ["attach", sid, "--no-exec"])`.
  - Assert `plan["action"] == "tmux-new-and-attach"` and `plan["argv"][0:5] == ["tmux", "-S", str(tmux_socket), "new-session", "-A"]`. Verify `["claude-real", "--resume", sid]` is at the tail.
- `test_attach_remote_reachable(home, state_root, ssh_shim)`:
  - Synthetic ownership where `owner="vicar"`. Configure `ssh_shim` so `ssh vicar true` exits 0 (reachable).
  - Configure config.toml with `hosts.vicar.ssh = "vicar"`.
  - `runner.invoke(app, ["attach", sid, "--no-exec"])`.
  - Assert `plan == {"action": "ssh-recurse", "argv": ["ssh", "vicar", "croam", "attach", sid, "--here-on-owner"]}`.
- `test_attach_remote_unreachable(home, state_root, ssh_shim)`:
  - Same as above but `ssh_shim` is configured so `ssh vicar true` exits 255.
  - `runner.invoke(app, ["attach", sid])` (no `--no-exec` -- we want the error path).
  - Assert `result.exit_code == 2`, `result.stderr` contains `"origin vicar unreachable"` and `"croam peek"`.
- `test_attach_picker_fallback(home, monkeypatch)`:
  - `runner.invoke(app, ["attach"])` (no sid).
  - Monkeypatch `commands.default.run_picker` to return `42`.
  - Assert `result.exit_code == 42`.
- `test_attach_recursion_guard(home, tmux_socket, state_root, monkeypatch)`:
  - **The critical test.** Synthetic ownership.json says `owner="vicar"` (REMOTE). Set `monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))`.
  - `runner.invoke(app, ["attach", sid, "--here-on-owner", "--no-exec"])`.
  - Assert `plan["action"]` is `"tmux-attach"` or `"tmux-new-and-attach"` -- NOT `"ssh-recurse"`. The `--here-on-owner` flag forced a local treatment despite ownership saying remote.
  - This is the property test that proves no infinite SSH ping-pong can happen.
- `test_attach_sid_not_found(home, state_root)`:
  - No assertion exists for the sid.
  - `runner.invoke(app, ["attach", "ffffffff-ffff-ffff-ffff-ffffffffffff"])`.
  - Assert `result.exit_code == 2`, `result.stderr` contains `"not found"`.

### `tests/test_peek.py`

- `test_peek_local_live(home, tmux_socket, monkeypatch)`:
  - Synthetic local session; pre-create tmux session.
  - `runner.invoke(app, ["peek", sid, "--no-exec"])`.
  - Assert `plan == {"action": "tmux-peek", "argv": ["tmux", "-S", str(tmux_socket), "attach", "-r", "-t", f"claude-{sid}"]}`.
- `test_peek_local_archived(home, monkeypatch)`:
  - Synthetic local session; tmux has no matching session.
  - `runner.invoke(app, ["peek", sid, "--no-exec"])`.
  - Assert `plan["action"] == "static-transcript"` and `plan["argv"][1]` ends with `f"{sid}.jsonl"` and the path is under `home / ".claude" / "projects"`.
- `test_peek_local_archived_renders(home, monkeypatch)`:
  - Same setup as above. Build a synthetic JSONL with two user records.
  - `runner.invoke(app, ["peek", sid])` (no `--no-exec` -- actually render).
  - Assert `result.exit_code == 0`, `result.stdout` contains `"[user] "` twice.
- `test_peek_remote_unreachable_via_mirror(home, state_root, ssh_shim)`:
  - Synthetic ownership: `owner="vicar"`. Build the mirror JSONL at `state_root/vicar/projects/<encoded>/<sid>.jsonl` with one user record. Configure `ssh_shim` to fail `ssh vicar true`.
  - `runner.invoke(app, ["peek", sid])`.
  - Assert `result.exit_code == 0`, stdout contains `"[user] "` from the mirror.
- `test_peek_remote_reachable_recurses(home, state_root, ssh_shim)`:
  - Synthetic ownership: `owner="vicar"`. Configure `ssh_shim` so `ssh vicar true` exits 0.
  - `runner.invoke(app, ["peek", sid, "--no-exec"])`.
  - Assert `plan == {"action": "ssh-recurse", "argv": ["ssh", "vicar", "croam", "peek", sid, "--here-on-owner"]}`.
- `test_peek_remote_unreachable_no_mirror(home, state_root, ssh_shim)`:
  - Synthetic ownership: `owner="vicar"`. NO mirror file. `ssh_shim` configured to fail.
  - `runner.invoke(app, ["peek", sid])`.
  - Assert `result.exit_code == 2`, stderr contains `"unreachable"` and `"no mirror"`.
- `test_peek_sid_not_found(home, state_root)`:
  - `runner.invoke(app, ["peek", "deadbeef-..."])`.
  - Assert exit 2, stderr has `"not found"`.

### `tests/test_ls.py`

- `test_ls_json_empty(home, state_root)`:
  - No sessions, no assertions.
  - `runner.invoke(app, ["ls", "--json"])`.
  - Assert `result.exit_code == 0`, `result.stdout.strip() == "[]"`.
- `test_ls_json_one_local(home, state_root)`:
  - Synthetic session + assertion (owner=self) under `home`.
  - `runner.invoke(app, ["ls", "--json"])`.
  - Parse `result.stdout` as JSON; assert it's a list of length 1; assert keys: `{"sid", "owner", "host_reachable", "status", "cwd", "last_activity", "is_orphan", "name"}`.
  - Assert `data[0]["owner"] == "stormtree"` (or whatever self_hostname is in the synthetic config).
  - Assert `data[0]["last_activity"]` is either None or matches ISO8601 (`re.match(r"\d{4}-\d{2}-\d{2}T...Z", ...)` -- not ms-epoch).
- `test_ls_text_mode(home, state_root)`:
  - One synthetic session.
  - `runner.invoke(app, ["ls"])`.
  - Assert `result.exit_code == 0`, stdout has at least one non-empty line that contains the first 8 chars of the sid.
- `test_ls_filter_pwd(home, state_root, monkeypatch, tmp_path)`:
  - Two synthetic sessions: one with `cwd_normalized=~/Programs/A`, one with `~/Programs/B`.
  - `monkeypatch.chdir(tmp_path / "home" / "Programs" / "A")` (or wherever the `home` fixture rooted Programs/A).
  - `runner.invoke(app, ["ls", "--json"])`.
  - Assert exactly one entry returned, the one with cwd_normalized matching A.
- `test_ls_all_flag(home, state_root)`:
  - Two host subdirs under state_root: `stormtree/ownership.json` with sid_a, `vicar/ownership.json` with sid_b.
  - `runner.invoke(app, ["--all", "ls", "--json"])` (note `--all` is global; check Phase 6's actual flag location).
  - Assert two entries, one per host.
- `test_ls_host_filter(home, state_root)`:
  - Same two-host setup.
  - `runner.invoke(app, ["--host", "vicar", "ls", "--json"])`.
  - Assert exactly one entry, owner=vicar.
- `test_ls_orphans_hidden_by_default(home, state_root)`:
  - Synthetic JSONL on disk (`home/.claude/projects/.../<sid>.jsonl`) but NO assertion for it.
  - `runner.invoke(app, ["ls", "--json"])`.
  - Assert returned list is empty (or does not contain the orphan).
- `test_ls_orphans_with_flag(home, state_root)`:
  - Same setup.
  - `runner.invoke(app, ["--orphans", "ls", "--json"])`.
  - Assert returned list contains the orphan; `entry["is_orphan"] is True`; `entry["owner"] is None`.
- `test_ls_last_window(home, state_root, monkeypatch)`:
  - Two synthetic sessions: one with `last_activity = now - 10 days`, one with `last_activity = now - 100 days`.
  - `runner.invoke(app, ["--last", "30", "ls", "--json"])`.
  - Assert only the 10-day-old one is in the result.
- `test_ls_returns_zero_with_empty_state(home, state_root)`:
  - Nothing populated.
  - `runner.invoke(app, ["ls"])`.
  - Assert exit 0, empty stdout.

### Test helpers to use (already provided by Phase 1 conftest)

- `home` fixture
- `tmux_socket` fixture
- `ssh_shim` fixture (write canned argv->output mappings)
- `state_root` fixture
- `tests/_helpers/synth_jsonl.py:build_jsonl(...)` -- write a synthetic JSONL with a controllable list of records
- `tests/_helpers/synth_assertions.py:write_assertion(...)` -- create an `ownership.json` entry for a given sid

If a helper does not yet exist for what you need, add it under `tests/_helpers/` rather than inlining the logic in test files.

---

## Functional QA

> Surfaces exercised: **Surface 1 (CLI verbs)**. References user loops: A (first-run sanity), B (cross-host attach), F (peek), and the implicit "ls outputs JSON for scripts" loop.

For each check, the coding agent runs the listed command, captures stdout/stderr/exit_code, and pastes the verbatim output into the phase summary's "Functional QA Results" section with a pass/fail verdict.

- [ ] (CLI surface, Loop A) Synthetic single-host scenario: build one synthetic session via the conftest fixtures, then run in-process `runner.invoke(app, ["ls", "--json"])`. Assert exit 0, `json.loads(result.stdout)` has length 1, schema matches `{"sid", "owner", "host_reachable", "status", "cwd", "last_activity", "is_orphan", "name"}`. Paste the captured JSON.
- [ ] (CLI surface, Loop A) Empty state: `runner.invoke(app, ["ls", "--json"])` against a fresh state_root with zero sessions returns exit 0, stdout `"[]\n"` (or `"[]"` after `.strip()`). Paste the literal stdout.
- [ ] (CLI surface, Loop A) Local-running attach plan: pre-create a tmux session at `claude-<sid>` via the `tmux_socket` fixture, run `runner.invoke(app, ["attach", sid, "--no-exec"])`. Assert `json.loads(stdout) == {"action": "tmux-attach", "argv": ["tmux", "-S", "<tmux_socket>", "attach", "-t", "claude-<sid>"]}`. Paste the JSON. Tear down the tmux session afterward (`tmux -S <socket> kill-session -t claude-<sid>`).
- [ ] (CLI surface, Loop A) Local-archived attach plan: NO pre-existing tmux session. Run the same invoke. Assert `plan["action"] == "tmux-new-and-attach"`, argv includes `["new-session", "-A", "-s", "claude-<sid>", "claude-real", "--resume", sid]` (in that order at the tail). Paste the JSON.
- [ ] (CLI surface, Loop B) Remote-reachable attach plan: configure `ssh_shim` so `ssh vicar true` exits 0; synthetic ownership says vicar owns the sid. Run `runner.invoke(app, ["attach", sid, "--no-exec"])`. Assert `plan == {"action": "ssh-recurse", "argv": ["ssh", "vicar", "croam", "attach", sid, "--here-on-owner"]}`. Paste the JSON.
- [ ] (CLI surface, Loop B) Recursion guard property: same setup as above (ownership says vicar) BUT call `runner.invoke(app, ["attach", sid, "--here-on-owner", "--no-exec"])`. Assert `plan["action"]` starts with `"tmux-"` (NOT `"ssh-recurse"`). This is the critical guarantee that two-host SSH ping-pong cannot happen.
- [ ] (CLI surface, Loop F) Peek local-archived dispatch: synthetic local session whose tmux is not running. Run `runner.invoke(app, ["peek", sid, "--no-exec"])`. Assert `plan["action"] == "static-transcript"` and the path argv ends with `f"{sid}.jsonl"`. Paste the JSON.
- [ ] (CLI surface, Loop F) Peek remote-unreachable mirror read: build a synthetic mirror JSONL at `<state_root>/vicar/projects/<encoded>/<sid>.jsonl` with two user records. Configure `ssh_shim` to fail `ssh vicar true`. Run `runner.invoke(app, ["peek", sid])` (full render, NOT `--no-exec`). Assert exit 0, stdout contains `[user]` twice.
- [ ] (CLI surface, scripting) `ls --orphans` schema: synthesize a JSONL with no backing assertion; run `runner.invoke(app, ["--orphans", "ls", "--json"])`. Assert the returned list contains the orphan, `entry["is_orphan"] is True`, `entry["owner"] is None`. Then run `runner.invoke(app, ["ls", "--json"])` (no `--orphans`); assert the orphan is absent. Paste both JSON outputs.

### Cross-cutting anti-patterns to watch

From `FUNCTIONAL_QA_STRATEGY.md`:

- **Anti-pattern A (HOME redirect)**: every test must use the `home` fixture. NEVER call `Path.home()` or `os.path.expanduser("~")` inside test code or production code. The conftest guard catches accidents but do not rely on it.
- **Anti-pattern B (mocking SSH)**: do NOT `monkeypatch.setattr(croam.hosts, "subprocess.run", fake)`. Use the `ssh_shim` fixture so real argv assembly is exercised.
- **Anti-pattern C (mocking tmux)**: do NOT mock `tmux.has_session`. Use the real tmux binary against `tmux_socket`. Pre-create / kill sessions via the fixture.
- **Anti-pattern E (timezones)**: every datetime in the JSON output goes through `.astimezone(timezone.utc).isoformat()` and ends with `Z` or `+00:00`. Test that it does. Mixed-offset bugs surface only when peers report from different timezones.

---

## Helpers Required

None. Phase 7 reuses existing helpers (`tests/_helpers/synth_jsonl.py`, `synth_assertions.py`, `ssh_shim`, `home`, `tmux_socket`, `state_root` fixtures) all from Phase 1 / Phase 4. No new spark-* shell scripts needed.

---

## External Interfaces Consumed

- **`croam emit-state --json` JSON shape (Phase 3's hidden command)**
  - **Consumed by**: `src/croam/commands/ls.py` (when `--all` is set with a remote-reachable peer; ls in v1 reads only the local mirror, but the JSON shape from `emit-state` is the same shape the local mirror produces, so reading the mirror requires the same parser). `src/croam/commands/peek.py` (mirror read also follows the same shape).
  - **How to capture**: with the project virtualenv active, `uv run python -c "from pathlib import Path; from croam.hosts import emit_state; import json; print(json.dumps(emit_state(Path.home(), Path.home() / '.local/share/croam'), indent=2, default=str))"` against the conftest-prepared synthetic home (or use `runner.invoke(app, ['emit-state'])` after setting `HOME` to the test home -- safer, never touches the user's real claude data). Capture the JSON to `/tmp/phase07-emit-state-sample.json` and paste it into the phase summary's "Evidence Captured" section.
  - **If not observable**: emit-state should be functional after Phase 3. If for some reason it raises, note that in the phase summary, defer the consumer test to a Phase 7 -> Phase 3 follow-up, and use a hand-written fixture matching what Phase 3 documented in its summary. Do not invent the schema from the spec without observing the real output.

- **tmux command output shapes (`tmux has-session`, `tmux new-session`, `tmux attach`)**
  - **Consumed by**: `src/croam/commands/attach.py` and `peek.py` via Phase 5's `tmux.has_session(...)` wrapper.
  - **How to capture**: `tmux -S /tmp/croam-phase07-probe.sock new-session -d -s probe-test sleep 60 && tmux -S /tmp/croam-phase07-probe.sock has-session -t probe-test ; echo $? && tmux -S /tmp/croam-phase07-probe.sock kill-session -t probe-test`. Capture stdout and exit codes for each command.
  - **If not observable**: tmux must be on PATH; this is a project prerequisite. If missing, escalate -- the phase cannot proceed without tmux.

- **claude JSONL transcript records (user / assistant message shapes)**
  - **Consumed by**: `src/croam/transcript.py:render_static_transcript` (specifically the `_extract_text` helper that handles three message-shape variants).
  - **How to capture**: with `CROAM_E2E=1` set (NOT in interactive use of the user's real ~/.claude -- the dummy at `/tmp/croam-e2e/` only), run `head -n 50 /tmp/croam-e2e/.claude/projects/-tmp-croam-e2e/[DUMMY_SID].jsonl | python3 -c "import sys, json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin if l.strip()]"`. Capture three sample records: at minimum one `user` and one `assistant`. Paste into the phase summary's "Evidence Captured" section.
  - **If not observable**: the e2e dummy should exist per Phase 0 setup. If it does not, fall back to building a synthetic JSONL via `tests/_helpers/synth_jsonl.py` matching the documented shapes in `CODEBASE_CONTEXT.md` "Data Models" section, and note in the phase summary that real-shape verification is deferred to Phase 10.

---

## Notes

- **Use `os.execvp`, not `subprocess.run`, for the actual exec path.** `subprocess.run` waits and returns; we want the user's terminal to fully replace into tmux/ssh. `os.execvp` does that. Do log the planned argv at INFO before exec'ing -- the log line is the last thing that runs before the process is replaced.
- **`--no-exec` is the test seam.** Without it, attach and peek's exec path is invisible to typer.testing.CliRunner. Treat the JSON shape (`{"action": "...", "argv": [...]}`) as a public contract within the project (Phase 8 follows the same pattern; Phase 10 reads these JSONs in integration tests).
- **`-A` flag on `tmux new-session`**: `tmux new-session -A -s name cmd` is "attach if exists, else create + attach." Race-safe -- two croam invocations on the same sid will not collide. We still call `has_session` first so the `--no-exec` plan can distinguish the two cases (tests need to see whether the session existed). Production code could skip the `has_session` and rely on `-A`, but keeping the explicit branch makes the test plan deterministic.
- **`commands.default._dispatch` recursion on ctrl-r**: bound by user attention, not a real loop. If you want to be defensive, add a `_recursion_depth` parameter capped at 100. Not required for v1.
- **Multi-row dispatch**: realistic for `peek` (open each in turn? -- unclear UX). For `attach`, only the first row makes sense (you can't attach to two sessions at once). Phase 7 implements "iterate, return on first non-zero rc," which is conservative. Phase 11 may revisit.
- **JSON output must NOT use `dataclasses.asdict()` directly on dataclass-y rows** -- `Path` and `datetime` won't serialize. Either convert to a plain dict before dump, or pass `default=str` to `json.dumps`. The test `test_ls_json_one_local` asserts the timestamp matches an ISO8601 regex, so plain `default=str` is fine for `datetime` (Python's default is ISO8601). For `Path`, convert to `str` explicitly.
- **`probe_reachability` is on `hosts.py`** (Phase 3). It's a list-input function; for a single-owner check, pass a one-element list and look up `result[owner]`.
- **Owner equality check**: `merged[sid].owner == config.self_hostname`. The config's `self_hostname` is autodetected from `os.uname().nodename` lowercase but may be overridden in `[self] hostname = "..."`. Trust `config.self_hostname` always.
- **Logging discipline**: every entry into `attach.run` / `peek.run` / `ls.run` logs at INFO with the verb name and inputs; the dispatch decision (local vs remote, has-session vs not) logs at DEBUG; the planned argv logs at INFO right before execvp; errors raise CroamError subclasses (no print-and-return).
- **The `OrphanRefused` error** (from Phase 1) is for Phase 8 `claim`/`attach`-on-orphan refusal. Phase 7 does not raise it; orphans in `ls` are filtered, not refused.
- **`--here-on-owner` is hidden** on the typer command. Users never type it. Tests can pass it explicitly; production reaches it only via SSH from another croam.
- **State persistence across tests**: every test must use isolated `home` and `state_root` fixtures. Tmux sessions created in one test must be killed before the test exits. The `tmux_socket` fixture should auto-cleanup the socket and any sessions on it at teardown -- verify this with the existing fixture before relying on it; if it doesn't, add the cleanup.
- **Encoding paths**: when computing the static transcript path, the order is: take `assertion.cwd_normalized` (e.g., `~/Programs/croam`), expand `~` against the local `home`, get the absolute path, then `paths.encode_cwd(absolute_path)`. The result is a directory name like `-home-tunc-Programs-croam`. Then append `f"{sid}.jsonl"`. Build it as `home / ".claude" / "projects" / encoded / f"{sid}.jsonl"`. Use the Phase 2 `paths.encode_cwd` directly -- do not re-implement the slash/dot replacement.
