# Phase 3: Sessions & host probes

**Feature**: project-start
**Estimated Context Budget**: ~70k tokens

**Difficulty**: medium
**Visual**: no
**Functional**: yes

**Execution Mode**: parallel
**Batch**: 3 (parallel with Phase 4 and Phase 5; all three depend only on Phases 1-2)

---

## Objective

Implement local claude-code session discovery (joining `~/.claude/projects/<encoded>/<sid>.jsonl` transcripts with `~/.claude/sessions/<PID>.json` live-process metadata), parallel SSH reachability fanout for configured hosts, and the building blocks for the hidden `croam emit-state` cross-host wire format. This phase produces the read-side of the discovery layer (Surface 4) and the data shape the hidden CLI verb (Surface 1) will return once Phase 6 wires it into typer.

---

## Deliverables

1. `src/croam/sessions.py` -- new module:
   - `@dataclass(frozen=True) class ClaudeSession` with fields documented in "Detailed Requirements" below.
   - `discover_local_sessions(home: Path) -> list[ClaudeSession]`
   - `tmux_attached(sid: str, sock: Path | None = None) -> tuple[bool, bool]` (returns `(has_session, attached)`; full implementation in Phase 3, Phase 5's `tmux.py` is the canonical wrapper but this function does its own subprocess call via `proc.run` and is independent of `tmux.py`).

2. `src/croam/hosts.py` -- new module:
   - `@dataclass(frozen=True) class HostStatus`
   - `probe_reachability(hosts: list[str], timeout_s: float = 2.0) -> dict[str, HostStatus]`
   - `emit_state(home: Path, state_root: Path, hostname: str) -> dict`
   - `fetch_remote_state(host: str, ssh_alias: str, timeout_s: float = 5.0) -> dict | None`

3. `src/croam/commands/__init__.py` -- new package marker (empty file with docstring `"""croam command modules. Each verb maps to one module here."""`).

4. `src/croam/commands/emit_state.py` -- new module:
   - `def emit_state_cmd(home: Path, state_root: Path, hostname: str) -> int` returning exit code 0 on success and printing the JSON payload to stdout. Phase 6 wires this into typer; Phase 3 must NOT touch `cli.py`.

5. `tests/test_sessions.py` -- unit tests for `discover_local_sessions` and `tmux_attached`.

6. `tests/test_hosts.py` -- unit tests for `probe_reachability`, `emit_state`, `fetch_remote_state`.

7. `tests/_helpers/synth_jsonl.py` (CREATE if Phase 1 didn't already; CONTRIBUTE additions if it did) -- Phase 1 owns this file. Phase 3 only USES the helpers it exposes (`build_jsonl`, `build_session_metadata`). If a needed helper is missing, raise this in the phase summary's "Helper Issues" rather than editing `_helpers/`.

---

## Detailed Requirements

### File-contention rules (READ FIRST)

- **DO NOT modify `src/croam/cli.py`.** Phase 6 owns the typer entry point. Phase 3 contributes the emit-state command via `src/croam/commands/emit_state.py`, which Phase 6 will register.
- **DO NOT modify `src/croam/proc.py`, `src/croam/log.py`, `src/croam/errors.py`, or `tests/conftest.py`.** Phase 1 owns these. Use them as-is.
- **DO NOT modify `src/croam/paths.py` or `src/croam/config.py`.** Phase 2 owns these. Use them as-is.
- **DO NOT modify `tests/_helpers/synth_jsonl.py`.** Phase 1 owns the test helpers. If something is missing, raise it in the phase summary; the checkpoint agent handles helper edits.

### `src/croam/sessions.py`

Module header (every module starts with this):
```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

from croam import proc
from croam.paths import decode_cwd
```

#### `ClaudeSession` dataclass

```python
@dataclass(frozen=True)
class ClaudeSession:
    sid: str                          # uuid string from filename stem
    cwd: Path                         # decoded from <encoded-cwd> dir name; absolute
    transcript_path: Path             # absolute path to <sid>.jsonl
    pid: int | None                   # None when no live ~/.claude/sessions/*.json found
    status: Literal["idle", "busy"] | None  # None when archived; coerce unknown -> "idle"
    started_at_ms: int | None         # epoch ms, from sessions/<PID>.json startedAt
    updated_at_ms: int | None         # epoch ms, from sessions/<PID>.json updatedAt
    name: str | None                  # autoname or /rename; absent in many sessions
    version: str | None               # claude version, e.g. "2.1.123"
```

The brief specifies `started_at_ms` and `updated_at_ms` (ms-epoch ints). The PROJECT_PLAN's earlier sketch used `started_at`/`updated_at` -- the brief overrides. Use the `_ms` suffixes.

#### `discover_local_sessions(home: Path) -> list[ClaudeSession]`

Implementation order:

1. `projects_dir = home / ".claude" / "projects"`. If `not projects_dir.exists()`, return `[]`.
2. `sessions_dir = home / ".claude" / "sessions"`. May or may not exist.
3. Build `sid_to_meta: dict[str, dict]` by scanning `sessions_dir`:
   - For each `*.json` file, `json.load` it; on `JSONDecodeError` log `logger.warning(...)` and skip.
   - Read `sessionId` field. Skip if missing or not a string.
   - If `sid_to_meta` already has this sid, keep the entry whose `updatedAt` is greater. Treat missing `updatedAt` as `0`.
4. Walk `projects_dir.iterdir()` for each `<encoded>` subdir; then `subdir.glob("*.jsonl")` for each transcript.
   - `sid = jsonl_path.stem` (filename without `.jsonl`).
   - `cwd = decode_cwd(subdir.name, host_home=home)` -- the Phase 2 helper handles lossy decoding.
   - Look up `meta = sid_to_meta.get(sid)`; may be `None` for archived sessions.
   - Build the `ClaudeSession`:
     - If `meta is not None`: pull `pid`, `status` (coerce values not in `{"idle","busy"}` to `"idle"`; if `status` field missing, default `"idle"`), `startedAt` -> `started_at_ms`, `updatedAt` -> `updated_at_ms`, `name`, `version`.
     - If `meta is None`: all of those are `None`.
5. Return the list (order: by `updated_at_ms desc nulls last`, then `sid asc`; deterministic for tests).

Edge cases (each must be exercised by a test):
- `~/.claude/projects` does not exist -> `[]`.
- `~/.claude/projects` exists but has no subdirs -> `[]`.
- Subdir exists but contains no `.jsonl` -> skipped (no entries from that dir).
- Empty `<sid>.jsonl` (zero bytes) -> still emit a `ClaudeSession` (the file exists; content irrelevant for Phase 3 -- Phase 7's peek parses content).
- Malformed `~/.claude/sessions/<PID>.json` (bad JSON) -> logged WARNING, skipped, transcript still emitted as archived if no other session metadata file resolves the sid.
- Multiple `sessions/<PID>.json` files share the same `sessionId` -> highest `updatedAt` wins. If two share the same `updatedAt`, deterministically pick by lower PID.
- `sessions/<PID>.json` references a `sessionId` for which no transcript exists -> NOT emitted (we only emit one ClaudeSession per transcript file; orphan sessions metadata is silently ignored at this layer).
- `decode_cwd` may probe the filesystem. If it raises (Phase 2 documents what), catch `OSError`/`ValueError` and skip the directory with `logger.warning(...)`. Do NOT propagate.

Return shape example (one running, one archived):
```python
[
    ClaudeSession(
        sid="ff7afd8a-ea17-4183-a131-566e7bcb0758",
        cwd=Path("/tmp/croam-e2e"),
        transcript_path=Path("/home/tunc/.claude/projects/-tmp-croam-e2e/ff7afd8a-...jsonl"),
        pid=161066,
        status="idle",
        started_at_ms=1777504235790,
        updated_at_ms=1777532759343,
        name="2026-04-30_1745_ai-agent-setup",
        version="2.1.123",
    ),
    ClaudeSession(
        sid="abc12345-...",
        cwd=Path("/home/tunc/Programs/old-project"),
        transcript_path=Path("/home/tunc/.claude/projects/-home-tunc-Programs-old-project/abc12345-...jsonl"),
        pid=None, status=None, started_at_ms=None, updated_at_ms=None, name=None, version=None,
    ),
]
```

#### `tmux_attached(sid: str, sock: Path | None = None) -> tuple[bool, bool]`

Phase 3 implements this fully. Phase 5's `tmux.py` will be the canonical wrapper for tmux operations, but `tmux_attached` is conceptually a session-state query and lives in `sessions.py` (it's used at picker render time alongside `discover_local_sessions`). Phase 5 may later refactor it to delegate to `tmux.py`.

1. Build the argv prefix: `["tmux"]` plus `["-S", str(sock)]` if `sock is not None`.
2. Call `proc.run(prefix + ["has-session", "-t", f"claude-{sid}"], timeout=2.0)`.
3. If returncode != 0: return `(False, False)` -- tmux server not running, or session does not exist. Both are normal for archived sessions.
4. Otherwise: call `proc.run(prefix + ["list-sessions", "-F", "#{session_name}:#{session_attached}"], timeout=2.0)`.
5. On returncode != 0: return `(True, False)` (we know the session exists from step 2, but list failed -- log WARNING).
6. Parse stdout. For each line: split on `:`, strip; if `name == f"claude-{sid}"`, return `(True, attached_flag != "0")`.
7. Loop fell through: return `(True, False)`.

Edge cases:
- Tmux server not running: step 2 returns nonzero with stderr "no server running on /tmp/tmux-1000/default" or similar. Treated as `(False, False)`. Test this.
- `proc.run` raises `proc.ProcTimeoutError` (Phase 1's typed timeout): catch, log WARNING, return `(False, False)`.
- Session name with special characters: sids are uuid4 strings (only `[0-9a-f-]`), no shell injection risk; use as-is.

### `src/croam/hosts.py`

Module header:
```python
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from croam import proc
from croam.sessions import ClaudeSession, discover_local_sessions
```

#### `HostStatus` dataclass

```python
@dataclass(frozen=True)
class HostStatus:
    name: str
    reachable: bool
    last_probed: datetime  # tz-aware UTC
    error: str | None      # None when reachable; populated otherwise
```

#### `probe_reachability(hosts: list[str], timeout_s: float = 2.0) -> dict[str, HostStatus]`

1. If `not hosts`, return `{}`.
2. `now = datetime.now(timezone.utc)` -- captured once outside the executor for deterministic `last_probed`.
3. `executor = ThreadPoolExecutor(max_workers=min(8, len(hosts)))` (use as a context manager).
4. For each host, submit `_probe_one(host, timeout_s, now)` -- a private helper.
5. Collect results into `{host: HostStatus}`.
6. Return.

`_probe_one(host: str, timeout_s: float, now: datetime) -> HostStatus`:
```python
argv = [
    "ssh",
    "-o", f"ConnectTimeout={int(timeout_s)}",
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    host,
    "true",
]
try:
    result = proc.run(argv, timeout=timeout_s + 1.0)
except proc.ProcTimeoutError:
    return HostStatus(name=host, reachable=False, last_probed=now, error="timeout")
if result.returncode == 0:
    return HostStatus(name=host, reachable=True, last_probed=now, error=None)
err = (result.stderr or "").strip() or f"ssh exited {result.returncode}"
return HostStatus(name=host, reachable=False, last_probed=now, error=err)
```

Edge cases:
- `timeout_s = 0.0` -> the OS may reject `ConnectTimeout=0`; treat sub-1 timeouts as `int(timeout_s)` = 0 and rely on `proc.run`'s timeout. Tests use 0.5; that becomes `ConnectTimeout=0`. The `timeout=timeout_s + 1.0` on the `proc.run` call dominates.
- Empty host list -> `{}` returned; no executor spun up.
- Duplicate hosts in list -> still de-dupe at the dict-build stage (later submission overwrites). Document but do NOT explicitly de-dupe (caller's responsibility; tests pass unique).
- Stderr from `ssh`: real OpenSSH writes "Could not resolve hostname X" or "ssh: connect to host X port 22: No route to host". The shim must mirror this.

#### `emit_state(home: Path, state_root: Path, hostname: str) -> dict`

Builds the JSON wire format for `croam emit-state`:

```python
def emit_state(home: Path, state_root: Path, hostname: str) -> dict:
    host_dir = state_root / hostname
    payload = {
        "hostname": hostname,
        "ownership": _read_json_or_none(host_dir / "ownership.json"),
        "lineage": _read_json_or_none(host_dir / "lineage.json"),
        "host_cache": _read_json_or_none(host_dir / "host-cache.json"),
        "sessions": [_session_to_wire(s) for s in discover_local_sessions(home)],
    }
    return payload
```

`_read_json_or_none(path: Path) -> dict | None`: returns `None` if file does not exist; otherwise `json.loads(path.read_text())`. On `JSONDecodeError`, log WARNING, return `None`.

`_session_to_wire(s: ClaudeSession) -> dict`: returns
```python
{
    "sid": s.sid,
    "cwd": str(s.cwd),
    "transcript_path": str(s.transcript_path),
    "pid": s.pid,
    "status": s.status,
    "started_at_ms": s.started_at_ms,
    "updated_at_ms": s.updated_at_ms,
    "name": s.name,
    "version": s.version,
}
```

The wire format is deliberately a serializable dict (no datetimes, no Paths). Phase 4's ownership module returns `Assertion` dataclasses, but `emit_state` consumes ownership.json's RAW JSON (not the Phase 4 dataclasses), because Phase 4 may not be running yet when this function gets called and we don't want a runtime dependency on `ownership.py`. The receiver of `emit_state`'s output (Phase 4's `read_all_assertions(peer_states=...)`) is responsible for parsing.

Edge cases:
- `state_root / hostname` does not exist -> all three state files missing -> all three keys = None; sessions still populated. Test this.
- `home / .claude / projects` does not exist -> sessions = [].
- Both missing -> `{"hostname": ..., "ownership": None, "lineage": None, "host_cache": None, "sessions": []}` returned without error. Test this.

#### `fetch_remote_state(host: str, ssh_alias: str, timeout_s: float = 5.0) -> dict | None`

```python
def fetch_remote_state(host: str, ssh_alias: str, timeout_s: float = 5.0) -> dict | None:
    argv = [
        "ssh",
        "-o", "ConnectTimeout=2",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        ssh_alias,
        "croam", "emit-state", "--json",
    ]
    try:
        result = proc.run(argv, timeout=timeout_s)
    except proc.ProcTimeoutError:
        logger.warning("fetch_remote_state {} timeout", host)
        return None
    if result.returncode != 0:
        logger.warning("fetch_remote_state {} rc={} stderr={!r}", host, result.returncode, result.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.warning("fetch_remote_state {} bad JSON: {}", host, e)
        return None
```

Edge cases:
- Mixed stdout (banner + JSON): we trust `croam emit-state --json` to write only JSON to stdout and route logs to stderr. If the JSON parse fails, we log + return None.
- `host` and `ssh_alias` may differ (config maps hostname to a custom ssh alias). Pass `ssh_alias` to ssh; use `host` only for log messages.

### `src/croam/commands/__init__.py`

```python
"""croam command modules. Each verb maps to one module here."""
```

That is the entire contents. The `__init__.py` makes `commands` a Python package; Phase 6 imports submodules.

### `src/croam/commands/emit_state.py`

```python
"""Hidden `croam emit-state` verb implementation. Wired by Phase 6's cli.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from croam.hosts import emit_state


def emit_state_cmd(home: Path, state_root: Path, hostname: str) -> int:
    """Print the per-host state JSON to stdout. Returns 0 on success."""
    payload = emit_state(home, state_root, hostname)
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    return 0
```

The function is signature-stable so Phase 6's typer handler can call it after resolving `home`, `state_root`, and `hostname` from config + environment. Tests in this phase invoke `emit_state_cmd` directly, NOT via typer's `CliRunner` (Phase 6 covers that).

---

## Implementation Order

Recommended sequence (each step's tests pass before moving on):

1. Create `src/croam/sessions.py` with the dataclass and `discover_local_sessions`. Cover steps 1-5 of its algorithm. Ship `tests/test_sessions.py` cases for: empty home, archived only, running + archived mix, multi-PID-same-sid, malformed JSON.
2. Add `tmux_attached` to `sessions.py`. Add tests. (Tests must use the `tmux_socket` fixture from Phase 1's conftest -- a private socket -- and either spin up a real `sleep`-backed session or rely on `proc.run` returning nonzero for the no-session case.)
3. Create `src/croam/hosts.py`. Implement `HostStatus`, `probe_reachability`. Tests use the `ssh_shim` fixture.
4. Implement `emit_state` and `fetch_remote_state` in the same module. Tests for each.
5. Create `src/croam/commands/__init__.py` and `src/croam/commands/emit_state.py`. One unit test in `tests/test_hosts.py` (or a new `tests/test_emit_state_cmd.py`) calls `emit_state_cmd` directly and parses its stdout.

---

## Dependencies

**Requires**:
- Phase 1: `src/croam/proc.py` (the `run` wrapper and the `ProcTimeoutError` typed exception); `src/croam/log.py` (loguru configured); `src/croam/errors.py` (CroamError base, though Phase 3 does not raise these directly); `tests/conftest.py` (the `home`, `tmux_socket`, `ssh_shim`, `state_root`, `e2e_dummy` fixtures + the autouse HOME-redirect guard); `tests/_helpers/synth_jsonl.py` with `build_jsonl(home, sid, cwd, ...)` and `build_session_metadata(home, pid, sid, ...)`.
- Phase 2: `src/croam/paths.py:decode_cwd(encoded: str, host_home: Path | None = None) -> Path`. Phase 3 calls this once per project subdir.

**Enables**:
- Phase 4 (ownership): can keep developing in parallel; only needs Phase 3's `emit_state` shape at integration time, and that shape is fully specified above. No code-level dependency.
- Phase 6 (picker & cli): consumes `discover_local_sessions`, `probe_reachability`, `tmux_attached`, and registers `emit_state_cmd` into typer.
- Phase 7 (attach/peek/ls): uses `discover_local_sessions` and `fetch_remote_state` for the `--all` SSH fanout.
- Phase 9 (sync/doctor): uses `probe_reachability` for diagnostics.

---

## Completion Criteria

- [ ] `src/croam/sessions.py` exists with `ClaudeSession`, `discover_local_sessions`, `tmux_attached`.
- [ ] `src/croam/hosts.py` exists with `HostStatus`, `probe_reachability`, `emit_state`, `fetch_remote_state`.
- [ ] `src/croam/commands/__init__.py` exists.
- [ ] `src/croam/commands/emit_state.py` exists with `emit_state_cmd(home, state_root, hostname) -> int`.
- [ ] `tests/test_sessions.py` and `tests/test_hosts.py` exist with the test cases enumerated below.
- [ ] `uv run pytest tests/test_sessions.py tests/test_hosts.py -v` passes locally.
- [ ] `uv run pytest --cov=src/croam/sessions --cov=src/croam/hosts --cov-report=term-missing` reports >= 90% on both modules.
- [ ] `uv run pyright src/croam/sessions.py src/croam/hosts.py src/croam/commands/` reports zero errors.
- [ ] `uv run ruff check src/croam/sessions.py src/croam/hosts.py src/croam/commands/` reports zero violations.
- [ ] No imports from Phase 4 (`ownership`) or Phase 5 (`tmux.py`, `shim.py`) in this phase's code. Phase 3 is upstream of both.
- [ ] `cli.py` is NOT modified; `proc.py`, `log.py`, `errors.py`, `conftest.py`, `paths.py`, `config.py`, `_helpers/synth_jsonl.py` are NOT modified.

---

## Testing Requirements

### Test commands

Primary: `uv run pytest tests/test_sessions.py tests/test_hosts.py -v`
With coverage: `uv run pytest tests/test_sessions.py tests/test_hosts.py -v --cov=src/croam/sessions --cov=src/croam/hosts --cov-report=term-missing`
With Tier 2 (real dummy): `CROAM_E2E=1 uv run pytest tests/test_sessions.py::test_e2e_dummy_discovery -v`

### `tests/test_sessions.py` cases (all Tier 1 unless noted)

1. **`test_discover_empty_home(home)`**: no `~/.claude/projects` -> `discover_local_sessions(home)` returns `[]`.
2. **`test_discover_with_running_session(home)`**: build_jsonl + build_session_metadata for one sid; assert exactly one ClaudeSession returned, `pid != None`, `status in {"idle","busy"}`, `started_at_ms` and `updated_at_ms` are positive ints, `transcript_path` matches the synthesized path.
3. **`test_discover_archived_session(home)`**: build_jsonl ONLY (no session metadata file); assert `pid is None, status is None, started_at_ms is None, updated_at_ms is None`.
4. **`test_discover_multiple_pids_same_sid(home)`**: write two `~/.claude/sessions/*.json` with same `sessionId`, different PIDs, different `updatedAt` (one older, one newer); assert the discovered ClaudeSession's `pid` matches the one with HIGHER `updatedAt`.
5. **`test_discover_skips_malformed_jsonl(home, caplog)`**: write a corrupt `~/.claude/sessions/161066.json` (truncated/invalid); assert `discover_local_sessions(home)` returns the transcript as archived AND `caplog.records` contains a WARNING with the path.
6. **`test_discover_unknown_status_coerced_to_idle(home)`**: session metadata has `status="weird"`; assert ClaudeSession.status == "idle".
7. **`test_discover_no_status_field_defaults_idle(home)`**: session metadata has no `status` key; assert "idle".
8. **`test_discover_no_projects_dir_returns_empty(home)`**: only `~/.claude/sessions` exists (no projects); assert `[]`.
9. **`test_discover_orphan_session_meta_ignored(home)`**: write `sessions/<PID>.json` with a sessionId for which no transcript exists; assert NOT included in the result list (we only emit one entry per transcript file).
10. **`test_discover_orders_deterministic(home)`**: build 3 transcripts with varied updated_at; assert returned list is sorted updated_at_ms desc, sid asc tiebreak.
11. **`test_tmux_attached_no_server(tmux_socket)`**: socket points at a non-existent path; assert `tmux_attached("any-sid", sock=tmux_socket)` returns `(False, False)` without raising.
12. **`test_tmux_attached_session_present(tmux_socket)`**: `proc.run(["tmux", "-S", str(tmux_socket), "new-session", "-d", "-s", "claude-test-sid", "--", "sleep", "10"])` to spin up a real session; assert `tmux_attached("test-sid", sock=tmux_socket) == (True, False)`. Teardown: `tmux -S <sock> kill-server` (or just rely on tmp_path cleanup).
13. **`test_e2e_dummy_discovery(e2e_dummy)`** (Tier 2 only): `home = Path.home()` (the real one; the `e2e_dummy` fixture's existence implies `CROAM_E2E=1`); call `discover_local_sessions(home)`; assert at least one returned ClaudeSession has `sid == e2e_dummy.sid` AND `cwd == Path("/tmp/croam-e2e")`. **Read-only**: no writes to `~/.claude/...`.

### `tests/test_hosts.py` cases

1. **`test_probe_empty_list`**: `probe_reachability([])` returns `{}`.
2. **`test_probe_reachable(ssh_shim)`**: register the shim to make `ssh ok-host true` exit 0 with empty stdout/stderr; assert `result["ok-host"].reachable is True` and `error is None`.
3. **`test_probe_unreachable_timeout(ssh_shim)`**: register the shim to `sleep 5` for `bad-host`; call `probe_reachability(["bad-host"], timeout_s=0.5)`; assert `reachable is False, error == "timeout"`.
4. **`test_probe_unreachable_resolution(ssh_shim)`**: register the shim to exit 255 with stderr `"ssh: Could not resolve hostname bogus-host"`; assert `reachable is False, "Could not resolve" in error`.
5. **`test_probe_parallel(ssh_shim)`**: register 8 hosts each delayed 0.2s; measure `time.monotonic()` before/after `probe_reachability(...)`; assert wall time < 1.0s. (Sequential would be 1.6s.)
6. **`test_probe_last_probed_utc`**: assert `result[host].last_probed.tzinfo is not None and last_probed.utcoffset() == timedelta(0)`.
7. **`test_emit_state_full(home, state_root)`**: pre-populate `state_root/<hostname>/ownership.json`, `lineage.json`, `host-cache.json` with synthetic JSON; build_jsonl + build_session_metadata for one sid in `home`; call `emit_state(home, state_root, "stormtree")`; assert returned dict has keys `{"hostname", "ownership", "lineage", "host_cache", "sessions"}`, `hostname == "stormtree"`, `ownership` equals the dict we wrote, `len(sessions) == 1`, `sessions[0]["sid"]` equals the synthesized sid.
8. **`test_emit_state_empty(home, state_root)`**: nothing exists for the hostname; assert `{"hostname": "stormtree", "ownership": None, "lineage": None, "host_cache": None, "sessions": []}`.
9. **`test_emit_state_corrupt_ownership(home, state_root, caplog)`**: write malformed `ownership.json`; assert `ownership` key is `None` AND a WARNING is logged.
10. **`test_emit_state_session_wire_shape(home, state_root)`**: build a synthetic running session; assert each `sessions[i]` has exactly the keys `{"sid","cwd","transcript_path","pid","status","started_at_ms","updated_at_ms","name","version"}` and that values are JSON-serializable (no Path, no datetime).
11. **`test_fetch_remote_state_ok(ssh_shim)`**: register the shim so `ssh some-host croam emit-state --json` prints `{"hostname":"some-host","ownership":null,"lineage":null,"host_cache":null,"sessions":[]}` and exits 0; assert `fetch_remote_state("some-host", "some-host")` returns the parsed dict.
12. **`test_fetch_remote_state_timeout(ssh_shim, caplog)`**: shim sleeps 5s; `fetch_remote_state(..., timeout_s=0.5)` returns `None` with a WARNING.
13. **`test_fetch_remote_state_bad_json(ssh_shim, caplog)`**: shim prints `not json`; returns `None` with a WARNING.
14. **`test_fetch_remote_state_nonzero_rc(ssh_shim, caplog)`**: shim exits 255 with stderr; returns `None` with a WARNING.
15. **`test_emit_state_cmd_writes_json(home, state_root, capsys)`**: call `emit_state_cmd(home, state_root, "stormtree")`; assert returncode `== 0`; assert `json.loads(capsys.readouterr().out)["hostname"] == "stormtree"`.

### What tests must NOT do

- NEVER call `discover_local_sessions(Path.home())` outside the Tier 2 `e2e_dummy` test. The autouse conftest guard refuses to run with the real HOME unless `CROAM_E2E=1` is set; the `e2e_dummy` fixture sets that flag.
- NEVER write to `~/.claude/projects/...` or `~/.claude/sessions/...` from any Tier 2 test. The dummy is read-only.
- NEVER monkeypatch `proc.run` or `subprocess.run` -- use the `ssh_shim` fixture (real fake binary on PATH). This catches argv-assembly bugs (anti-pattern B in FUNCTIONAL_QA_STRATEGY.md).
- NEVER mock `tmux` -- use the `tmux_socket` fixture and real tmux (anti-pattern C).

---

## Functional QA

Phase 3 ships parts of two surfaces: Surface 1 (the hidden `croam emit-state` verb -- the implementation lives in `commands/emit_state.py`; Phase 6 wires the typer registration) and Surface 4 (the inter-host wire format the verb returns). The picker is Phase 6; attach is Phase 7. Phase 3's functional checks therefore focus on the data layer.

Anti-patterns to watch for (from FUNCTIONAL_QA_STRATEGY.md):
- **A**: Tests that don't redirect HOME silently corrupt the user's real `~/.claude`. Always use the `home` fixture; never call `Path.home()` outside Tier 2.
- **B**: Tests that mock `subprocess.run` miss real reachability semantics. Use the `ssh_shim` fixture exclusively for SSH probes.
- **C**: Tests that mock tmux miss session-naming and socket-isolation bugs. Use real tmux on a private socket via `tmux_socket`.

### Checks (mark pass/fail in summary)

- [ ] **(state-file surface, Loop A)** `discover_local_sessions(home)` against a synthetic `home` containing one running session (build_jsonl + build_session_metadata) returns exactly one `ClaudeSession` whose `sid` matches the file stem, `cwd` matches the decoded encoded-cwd, `pid` matches the synthesized PID, `status in {"idle","busy"}`. Capture the returned dataclass and the synthesized `~/.claude/sessions/<PID>.json` content; paste both into the phase summary.
- [ ] **(state-file surface, Loop A)** `discover_local_sessions(home)` against a synthetic `home` containing one transcript with NO matching session-metadata file returns one `ClaudeSession` with `pid is None, status is None, started_at_ms is None, updated_at_ms is None`. Paste the returned dataclass.
- [ ] **(state-file surface, Loop B)** `probe_reachability(["fake-host"], timeout_s=2.0)` with the `ssh_shim` registered to make `ssh fake-host true` exit 0 returns `{"fake-host": HostStatus(reachable=True, error=None, last_probed=<utc>)}`. Capture the registered shim invocation log and the returned `HostStatus`.
- [ ] **(state-file surface, Loop B)** `probe_reachability(["slow-host"], timeout_s=0.5)` with the `ssh_shim` registered to `sleep 5` returns `reachable=False, error="timeout"`. Paste the elapsed wall-clock time (must be `< 2.0s`).
- [ ] **(wire-format surface, Loop C)** `emit_state(home, state_root, "stormtree")` against a `state_root` containing a synthetic `stormtree/ownership.json` and a `home` with one synthetic running session returns a dict with keys `{"hostname","ownership","lineage","host_cache","sessions"}` where `hostname == "stormtree"`, `ownership` equals the JSON we wrote, and `sessions[0]` has the wire shape `{"sid","cwd","transcript_path","pid","status","started_at_ms","updated_at_ms","name","version"}`. Paste the full returned dict.
- [ ] **(cli surface, Loop A precursor)** `emit_state_cmd(home, state_root, "stormtree")` (called as a Python function, not via typer) returns 0 and writes one line of valid JSON to stdout (captured via `capsys`). Paste the captured stdout.
- [ ] **(Tier 2, opt-in)** With `CROAM_E2E=1`, `discover_local_sessions(Path.home())` returns at least one `ClaudeSession` whose `sid == "ff7afd8a-ea17-4183-a131-566e7bcb0758"` and `cwd == Path("/tmp/croam-e2e")`. The test must NOT mutate any file under `~/.claude`. Paste the matching dataclass; paste `git status` of the repo (no files added) and `ls -la /home/tunc/.claude/projects/-tmp-croam-e2e/` (timestamps unchanged from before).

---

## External Interfaces Consumed

This phase reads two filesystem-native interfaces produced by the claude-code CLI plus the OpenSSH client. The coding agent must observe each before writing types or mocks and paste the captured sample into the phase summary's "Evidence Captured" section.

- **`~/.claude/sessions/<PID>.json` schema** (claude-native; live-process metadata, keyed by PID, joined to transcripts by `sessionId`).
  - **Consumed by**: `src/croam/sessions.py:discover_local_sessions` (parses the JSON; reads `sessionId`, `pid`, `status`, `startedAt`, `updatedAt`, `name`, `version`).
  - **How to capture**: `python3 -c "import json; print(json.dumps(json.load(open('/home/tunc/.claude/sessions/161066.json')), indent=2))"`. Confirm the keys you intend to read are all present. CODEBASE_CONTEXT.md "Data Models" already documents the schema; the agent must verify it has not drifted before writing the dataclass.
  - **If not observable**: `/home/tunc/.claude/sessions/161066.json` may not exist on a CI host. In that case, fall back to any other file in that directory: `ls /home/tunc/.claude/sessions/ | head -1` then read it. Document the chosen sample in the phase summary.

- **`~/.claude/projects/<encoded-cwd>/<sid>.jsonl` filename + presence** (claude-native; conversation transcripts).
  - **Consumed by**: `src/croam/sessions.py:discover_local_sessions` (extracts `sid` from filename stem; does NOT parse content -- Phase 7's peek does that).
  - **How to capture**: `ls /home/tunc/.claude/projects/-tmp-croam-e2e/`. Confirm the file shape is `<uuid>.jsonl`. Also peek at content shape (irrelevant to Phase 3, but informative for the wider system): `head -1 /home/tunc/.claude/projects/-tmp-croam-e2e/ff7afd8a-ea17-4183-a131-566e7bcb0758.jsonl | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).keys())"`. Phase 3 only needs to verify "sid is the filename stem" -- evidence requirement is light.
  - **If not observable**: the directory should exist (it is the dummy fixture set up at project init). If absent, the dummy fixture is broken -- escalate; do not paper over.

- **OpenSSH client behavior on connection failure** (the stderr shape that `ssh -o BatchMode=yes -o ConnectTimeout=2 host true` produces when the host does not exist).
  - **Consumed by**: `src/croam/hosts.py:probe_reachability._probe_one` (parses `result.stderr` to populate `HostStatus.error`).
  - **How to capture**: `ssh -o ConnectTimeout=2 -o BatchMode=yes -o StrictHostKeyChecking=no notarealhost true 2>&1; echo "rc=$?"`. Expected output: stderr message starting with `ssh: Could not resolve hostname notarealhost` and exit code 255. Capture the exact string so the `test_probe_unreachable_resolution` test asserts on a real substring.
  - **If not observable**: every Linux box with OpenSSH reproduces this; if it does not, escalate (the runtime is broken).

---

## Notes

- `proc.run` from Phase 1 is the ONLY subprocess wrapper used. Never import `subprocess` directly in Phase 3 code. The wrapper logs argv at DEBUG and translates `subprocess.TimeoutExpired` into `proc.ProcTimeoutError`. The agent must read Phase 1's `src/croam/proc.py` once at the start of the phase to confirm the actual function signature and exception name -- the brief calls it `proc.run` and `proc.ProcTimeoutError`; if Phase 1 named them differently, adapt.
- `decode_cwd` may probe the filesystem (Phase 2 is responsible for it). On the dummy `-tmp-croam-e2e`, the decoder probes `/tmp/croam-e2e` and confirms it exists. In tests, the encoded cwd points into `tmp_path` so the probe finds the synthetic dir there too. Synth_jsonl helpers (Phase 1) handle this; do NOT replicate.
- Multiple PIDs sharing a sessionId is rare but real (a user `--resume`s the session, the second process writes a fresh `sessions/<new-PID>.json` while the original is still recorded). Highest-`updatedAt` wins because that file represents the most recent live state. Tie on `updatedAt` -> lower PID (deterministic).
- The picker (Phase 6) will call `tmux_attached(sid, sock=...)` per row to compute the attached glyph. Phase 5's `tmux.py` will own `has_session`, `attach`, etc. -- but `tmux_attached` is a session-state QUERY (returns booleans, no exec), conceptually session metadata, and stays in `sessions.py`. Phase 5 may later refactor it to delegate; for v1 it stands alone.
- `emit_state` returns RAW dict-shaped state files (not Phase 4 dataclasses). Phase 4's `read_all_assertions(peer_states=...)` reparses them. This avoids a runtime dependency on `ownership.py` from `hosts.py` and lets the wire format stay JSON-native.
- `commands/__init__.py` is the FIRST file in that directory. Phases 5, 7, 8, 9 add sibling files (`launch.py`, `attach.py`, `peek.py`, `ls.py`, `claim.py`, `fork.py`, `doctor.py`, `default.py`). Do not add anything else to `__init__.py` beyond the docstring -- keep it minimal so later phases can collide-free import sibling modules.
- Logging discipline: `logger.warning(...)` for malformed JSON, missing/corrupt session metadata, SSH failure stderr capture; `logger.debug(...)` for SSH argv (already handled by `proc.run`); never `logger.info` in this phase (everything is either a warning or background detail).
- The `~/.claude/projects/<encoded>/<sid>.jsonl` line types listed in CODEBASE_CONTEXT.md (`last-prompt`, `permission-mode`, etc.) are RELEVANT to Phase 7 (peek render) but NOT to Phase 3. Phase 3 reads only the filename stem. Resist the urge to parse content.

---

