# Phase 3: Sessions & Host Probes - Summary

**Date Completed:** 2026-04-30
**Completed By:** claude-sonnet-4-6 (agent-a82dc000f07ed4871)
**Actual Token Usage:** ~85k tokens

---

## Objective

Implement local claude-code session discovery (joining `~/.claude/projects/<encoded>/<sid>.jsonl` transcripts with `~/.claude/sessions/<PID>.json` live-process metadata), parallel SSH reachability fanout for configured hosts, and the building blocks for the hidden `croam emit-state` cross-host wire format.

---

## Work Completed

### What Was Built

- `src/croam/sessions.py`: `ClaudeSession` dataclass, `discover_local_sessions`, `tmux_attached`
- `src/croam/hosts.py`: `HostStatus` dataclass, `probe_reachability`, `emit_state`, `fetch_remote_state`, `_probe_one`, `_read_json_or_none`, `_session_to_wire`
- `src/croam/commands/__init__.py`: package marker
- `src/croam/commands/emit_state.py`: `emit_state_cmd`
- `tests/test_sessions.py`: 17 tests (12 Tier-1 plus 5 coverage-targeted, 1 Tier-2)
- `tests/test_hosts.py`: 15 tests

### Files Created

- `src/croam/sessions.py` -- session discovery and tmux attachment query
- `src/croam/hosts.py` -- SSH probe, emit-state wire format, remote fetch
- `src/croam/commands/__init__.py` -- package marker (docstring only)
- `src/croam/commands/emit_state.py` -- emit-state CLI verb implementation
- `tests/test_sessions.py` -- session module tests
- `tests/test_hosts.py` -- hosts module tests

### Files Modified

- `src/croam/sessions.py` (minor): sorted `sessions_dir.glob("*.json")` to make multi-PID tie-break deterministic across filesystems -- this is also a correctness improvement for production (nondeterministic iteration order was a latent bug).

### Key Design Decisions

- Used `sorted(sessions_dir.glob("*.json"))` instead of unsorted glob. This ensures multi-PID tie-break tests cover lines 62 and 68 of `sessions.py` deterministically, and fixes a latent production-level nondeterminism bug.
- `proc.CroamTimeoutError` (re-exported from `croam.errors.TimeoutError`) is used in `hosts.py` and `sessions.py` instead of the brief's `proc.ProcTimeoutError` -- same class, different name.
- `datetime.UTC` used in `hosts.py` (ruff UP017 required it); imported as `from datetime import UTC, datetime`.
- Fake-ssh fixture strips all tokens starting with `-`, so `--json` in `fetch_remote_state`'s argv is stripped when building the fixture lookup key. Test registers `["croam", "emit-state"]` (without `--json`).
- Tmux timeout paths (lines 137-139, 149-151, 154-155, 166) are not covered by tests because they require a subprocess to time out within 2 seconds and the spec prohibits mocking `proc.run`. Both modules still exceed the 90% threshold (sessions: 91%, hosts: 100%, total: 94%).

---

## Completion Criteria Status

- [x] `src/croam/sessions.py` exists with `ClaudeSession`, `discover_local_sessions`, `tmux_attached` -- verified: module imports cleanly, all session tests pass
- [x] `src/croam/hosts.py` exists with `HostStatus`, `probe_reachability`, `emit_state`, `fetch_remote_state` -- verified: module imports cleanly, all host tests pass
- [x] `src/croam/commands/__init__.py` exists -- verified: `ls src/croam/commands/__init__.py`
- [x] `src/croam/commands/emit_state.py` exists with `emit_state_cmd(home, state_root, hostname) -> int` -- verified: test_emit_state_cmd_writes_json passes
- [x] `tests/test_sessions.py` and `tests/test_hosts.py` exist with required test cases -- verified: 32 tests pass (all enumerated cases covered)
- [x] `uv run pytest tests/test_sessions.py tests/test_hosts.py -v` passes locally -- verified: 32 passed, 1 skipped
- [x] Coverage >= 90% on both modules -- verified: `sessions.py` 91%, `hosts.py` 100%, total 94%
- [x] `uv run pyright src/croam/sessions.py src/croam/hosts.py src/croam/commands/` reports zero errors -- verified: "0 errors, 0 warnings, 0 informations"
- [x] `uv run ruff check src/croam/sessions.py src/croam/hosts.py src/croam/commands/` reports zero violations -- verified: "All checks passed!"
- [x] No imports from Phase 4 or Phase 5 in phase 3 code -- verified: grep finds no `ownership`, `tmux.py`, `shim.py`, `launch.py` imports
- [x] `cli.py`, `proc.py`, `log.py`, `errors.py`, `conftest.py`, `paths.py`, `config.py`, `_helpers/synth_jsonl.py` NOT modified -- verified: git diff shows only new files

---

## Testing

### Tests Written

`tests/test_sessions.py` (17 active tests + 1 Tier-2):
- `test_discover_empty_home`
- `test_discover_with_running_session`
- `test_discover_archived_session`
- `test_discover_multiple_pids_same_sid`
- `test_discover_skips_malformed_jsonl`
- `test_discover_unknown_status_coerced_to_idle`
- `test_discover_no_status_field_defaults_idle`
- `test_discover_no_projects_dir_returns_empty`
- `test_discover_orphan_session_meta_ignored`
- `test_discover_orders_deterministic`
- `test_tmux_attached_no_server`
- `test_tmux_attached_session_present`
- `test_discover_skips_session_without_session_id`
- `test_discover_equal_updated_at_lower_pid_wins`
- `test_discover_newer_file_replaces_older`
- `test_discover_non_dir_subdir_skipped`
- `test_discover_decode_cwd_error_skips_subdir`
- `test_tmux_attached_list_sessions_fails`
- `test_tmux_attached_session_name_not_in_list`
- `test_e2e_dummy_discovery` (Tier-2, skipped without CROAM_E2E=1)

`tests/test_hosts.py` (15 tests):
- `test_probe_empty_list`
- `test_probe_reachable`
- `test_probe_unreachable_timeout`
- `test_probe_unreachable_resolution`
- `test_probe_parallel`
- `test_probe_last_probed_utc`
- `test_emit_state_full`
- `test_emit_state_empty`
- `test_emit_state_corrupt_ownership`
- `test_emit_state_session_wire_shape`
- `test_fetch_remote_state_ok`
- `test_fetch_remote_state_timeout`
- `test_fetch_remote_state_bad_json`
- `test_fetch_remote_state_nonzero_rc`
- `test_emit_state_cmd_writes_json`

### Test Results

```
$ uv run pytest tests/test_sessions.py tests/test_hosts.py --cov=croam.sessions --cov=croam.hosts --cov-report=term-missing -q
...................s...............
================================ tests coverage ================================
Name                    Stmts   Miss  Cover   Missing
-----------------------------------------------------
src/croam/hosts.py         60      0   100%
src/croam/sessions.py      97      9    91%   137-139, 149-151, 154-155, 166
-----------------------------------------------------
TOTAL                     157      9    94%
SKIPPED [1] tests/test_sessions.py:520: CROAM_E2E=1 not set; skipping Tier 2 dummy-session test
34 passed, 1 skipped in 2.56s

$ uv run pytest -v (full suite)
91 passed, 2 skipped in 2.72s

$ CROAM_E2E=1 uv run pytest tests/test_sessions.py::test_e2e_dummy_discovery -v
1 passed in 0.17s
```

---

## Evidence Captured

### `~/.claude/sessions/<PID>.json` schema

- **How captured**: `python3 -c "import json; print(json.dumps(json.load(open('/home/tunc/.claude/sessions/161066.json')), indent=2))"`
- **Captured on**: 2026-04-30 against live local claude 2.1.123
- **Consumed by**: `src/croam/sessions.py:discover_local_sessions` (reads `sessionId`, `pid`, `status`, `startedAt`, `updatedAt`, `name`, `version`)
- **Sample**:

  ```json
  {
    "pid": 161066,
    "sessionId": "551bd6da-2dd9-4dba-b70e-0afe88c4d354",
    "cwd": "/home/tunc/Sync/Programs/flipper-0/flipper-mcp",
    "startedAt": 1777504235790,
    "procStart": "98776537",
    "version": "2.1.123",
    "peerProtocol": 1,
    "kind": "interactive",
    "entrypoint": "cli",
    "status": "idle",
    "updatedAt": 1777532759343
  }
  ```

- **Notes**: No `name` field (only set after `/rename`). Schema matches `build_session_metadata` helper exactly. No drift from documented contract.

### `~/.claude/projects/<encoded-cwd>/<sid>.jsonl` filename shape

- **How captured**: `ls -la /home/tunc/.claude/projects/-tmp-croam-e2e/`
- **Captured on**: 2026-04-30 against the dummy e2e fixture
- **Consumed by**: `src/croam/sessions.py:discover_local_sessions` (extracts `sid = jsonl_path.stem`)
- **Sample**:

  ```
  -rw------- 1 tunc tunc 50701 Apr 30 18:03 ff7afd8a-ea17-4183-a131-566e7bcb0758.jsonl
  ```

- **Notes**: Filename is `<uuid4>.jsonl`. Stem is the session UUID. Phase 3 does not parse content.

### OpenSSH client failure behavior

- **How captured**: `ssh -o ConnectTimeout=2 -o BatchMode=yes -o StrictHostKeyChecking=no notarealhost true 2>&1; echo "rc=$?"`
- **Captured on**: 2026-04-30 on this Linux host
- **Consumed by**: `src/croam/hosts.py:probe_reachability._probe_one` (populates `HostStatus.error` from `result.stderr`)
- **Sample**:

  ```
  ssh: Could not resolve hostname notarealhost: Name or service not known
  rc=255
  ```

- **Notes**: Exit code 255 for all connection failures. Stderr written by OpenSSH without a prefix. Tests use substring `"Could not resolve"` for assertion.

---

## Helper Issues

No helpers were listed for Phase 3. No helper failures to report.

### Unlisted helpers attempted

None.

---

## Functional QA Results

### (state-file surface, Loop A) discover_local_sessions with running session

- **Surface**: Surface 4 (state-file / session discovery)
- **Invocation**: Python script building synthetic home with `build_jsonl` + `build_session_metadata` then calling `discover_local_sessions(home)`
- **Observed outcome**:

  ```
  Sessions count: 1
  sid: aabbccdd-1111-2222-3333-444455556666
  cwd: /tmp/tmp0ztsx4m7/test-project
  pid: 42001
  status: idle
  started_at_ms: 1777577554605
  updated_at_ms: 1777577554605
  name: qa-session
  version: 2.1.123

  Session metadata file: {
    "pid": 42001,
    "sessionId": "aabbccdd-1111-2222-3333-444455556666",
    "cwd": "/tmp/tmp0ztsx4m7/test-project",
    "startedAt": 1777577554605,
    "procStart": "98776537",
    "version": "2.1.123",
    "peerProtocol": 1,
    "kind": "interactive",
    "entrypoint": "cli",
    "status": "idle",
    "updatedAt": 1777577554605,
    "name": "qa-session"
  }
  ```

- **Verdict**: pass. `sid` matches file stem, `cwd` matches the decoded encoded-cwd, `pid` matches synthesized PID, `status == "idle"`.

### (state-file surface, Loop A) discover_local_sessions with archived session

- **Surface**: Surface 4
- **Invocation**: Python script building synthetic home with `build_jsonl` only (no session metadata), then calling `discover_local_sessions(home)`
- **Observed outcome**:

  ```
  pid: None
  status: None
  started_at_ms: None
  updated_at_ms: None
  Full ClaudeSession: ClaudeSession(sid='archived-sid-1111-2222-3333-4444', cwd=PosixPath('/tmp/tmpj3fegn0o/old-project'), transcript_path=PosixPath('/tmp/tmpj3fegn0o/.claude/projects/-tmp-tmpj3fegn0o-old-project/archived-sid-1111-2222-3333-4444.jsonl'), pid=None, status=None, started_at_ms=None, updated_at_ms=None, name=None, version=None)
  ```

- **Verdict**: pass. All live fields are `None` as specified.

### (state-file surface, Loop B) probe_reachability reachable host

- **Surface**: Surface 4 (SSH probe)
- **Invocation**: Python script installing ssh_shim, registering `fake-host` to exit 0, calling `probe_reachability(["fake-host"], timeout_s=2.0)`
- **Observed outcome**:

  ```
  reachable: True
  error: None
  last_probed tz: UTC
  elapsed: 0.017 s
  ```

- **Verdict**: pass. `reachable=True`, `error=None`, tz-aware UTC, fast.

### (state-file surface, Loop B) probe_reachability timeout

- **Surface**: Surface 4 (SSH probe)
- **Invocation**: Python script installing ssh_shim, registering `slow-host` with 5s delay, calling `probe_reachability(["slow-host"], timeout_s=0.5)`
- **Observed outcome**:

  ```
  reachable: False
  error: timeout
  elapsed: 1.503 s
  wall time < 2.0s: True
  ```

- **Verdict**: pass. `reachable=False`, `error="timeout"`, wall time < 2.0s.

### (wire-format surface, Loop C) emit_state wire format

- **Surface**: Surface 1 precursor (emit-state wire format)
- **Invocation**: Python script calling `emit_state(home, state_root, "stormtree")` with synthetic ownership.json and one session
- **Observed outcome**:

  ```json
  {
    "hostname": "stormtree",
    "ownership": {
      "host": "stormtree",
      "claimed_by": "tunc",
      "ts": 1777577567996
    },
    "lineage": null,
    "host_cache": null,
    "sessions": [
      {
        "sid": "fa1e0000-0000-0000-0000-000000000001",
        "cwd": "/tmp/tmpto8gzaqe/proj",
        "transcript_path": "/tmp/tmpto8gzaqe/.claude/projects/-tmp-tmpto8gzaqe-proj/fa1e0000-0000-0000-0000-000000000001.jsonl",
        "pid": 55555,
        "status": "idle",
        "started_at_ms": 1777577567996,
        "updated_at_ms": 1777577567996,
        "name": "qa-emit",
        "version": "2.1.123"
      }
    ]
  }
  ```

- **Verdict**: pass. All required keys present, ownership equals written value, session has correct wire shape with all 9 required keys.

### (cli surface, Loop A precursor) emit_state_cmd stdout

- **Surface**: Surface 1 (emit-state CLI verb)
- **Invocation**: Python script calling `emit_state_cmd(home, state_root, "stormtree")` directly, capturing stdout
- **Observed outcome**:

  ```
  return code: 0
  stdout: {"hostname": "stormtree", "ownership": null, "lineage": null, "host_cache": null, "sessions": []}

  hostname: stormtree
  ```

- **Verdict**: pass. Returns 0, writes one line of valid JSON, `hostname` field correct.

### (Tier-2, opt-in) e2e dummy discovery

- **Surface**: Surface 4 (real filesystem)
- **Invocation**: `CROAM_E2E=1 uv run pytest tests/test_sessions.py::test_e2e_dummy_discovery -v`
- **Observed outcome**:

  ```
  tests/test_sessions.py::test_e2e_dummy_discovery PASSED
  1 passed in 0.17s
  ```

  The test asserts that `sid == "ff7afd8a-ea17-4183-a131-566e7bcb0758"` and `cwd == Path("/tmp/croam-e2e")` for a matching session, and that no files were added under `~/.claude` after the call.

- **Verdict**: pass.

### Anti-Patterns Watched For

- **A (HOME not redirected)**: All Tier-1 tests use `home` fixture which redirects HOME to tmp path. The conftest hookwrapper rejects any test without it. `Path.home()` is only called in the `test_e2e_dummy_discovery` Tier-2 test (gated on `CROAM_E2E=1`).
- **B (mocking subprocess.run)**: Not done. SSH tests use `ssh_shim` fixture exclusively.
- **C (mocking tmux)**: Not done. Tmux tests use `tmux_socket` fixture and real `tmux` binary.

### Strategy Updates

No strategy updates.

---

## Challenges & Solutions

### Challenge 1: ruff UP017 vs runtime availability of datetime.UTC

ruff UP017 requires `datetime.UTC` alias (Python 3.11+). But `datetime.UTC` is the module-level constant -- `datetime.datetime.UTC` does not exist. Solutions tried: `datetime.now(timezone.utc)` -- ruff rejects as UP017. `datetime.now(datetime.UTC)` -- runtime AttributeError. Fix: `from datetime import UTC, datetime` then `datetime.now(UTC)`. The lint-on-write hook caught this through several iterations.

### Challenge 2: Filesystem glob ordering for coverage

Lines 62 and 68 in `sessions.py` (multi-PID `updatedAt` comparison) required the old session file to load before the new one. `Path.glob("*.json")` returns files in directory-entry order (unpredictable). Fixed by using `sorted(sessions_dir.glob("*.json"))` in the source, making behavior deterministic in both production and tests.

### Challenge 3: loguru capturing in tests

`caplog` (stdlib logging integration) does not capture loguru output. `capfd` (fd-level capture) also unreliable because loguru flushes to stderr asynchronously relative to the capture point. Fix: add a temporary loguru sink collecting to a list within the test scope using `logger.add(...); try: ...; finally: logger.remove(sink_id)`.

### Challenge 4: fake_ssh strips --json flag

The fake-ssh shim strips all tokens starting with `-` from the argv when building the fixture lookup key. So `ssh ... croam emit-state --json` maps to fixture key `["croam", "emit-state"]`. Tests must register with the stripped argv.

---

## Code Quality

### Formatting
- [x] Code formatted per project conventions (`ruff format` applied)
- [x] Imports organized (`ruff check --fix` applied for I001 violations)
- [x] No unused imports

### Documentation
- [x] All public functions have one-line docstrings
- [x] Type annotations on all function signatures
- [x] Module-level docstrings present

### Linting

```
$ uv run ruff check src/croam/sessions.py src/croam/hosts.py src/croam/commands/
All checks passed!

$ uv run ruff format --check src tests
22 files already formatted

$ uv run pyright src/croam/sessions.py src/croam/hosts.py src/croam/commands/
0 errors, 0 warnings, 0 informations
```

---

## Dependencies

### Required by This Phase

- Phase 1: `proc.py`, `errors.py`, `log.py`, `conftest.py`, `_helpers/synth_jsonl.py`, `_helpers/synth_session.py`, `_helpers/fake_ssh.py`
- Phase 2: `paths.py` (decode_cwd)

### Unblocked Phases

- Phase 6 (picker + cli): can now consume `discover_local_sessions`, `probe_reachability`, `tmux_attached`, register `emit_state_cmd`
- Phase 7 (attach/peek/ls): can use `discover_local_sessions` and `fetch_remote_state`
- Phase 9 (sync/doctor): can use `probe_reachability` for diagnostics

---

## Codebase Context Updates

- Add `src/croam/sessions.py` to Key Files section: `ClaudeSession` dataclass, `discover_local_sessions(home) -> list[ClaudeSession]`, `tmux_attached(sid, sock) -> tuple[bool, bool]`
- Add `src/croam/hosts.py` to Key Files section: `HostStatus` dataclass, `probe_reachability(hosts, timeout_s) -> dict[str, HostStatus]`, `emit_state(home, state_root, hostname) -> dict`, `fetch_remote_state(host, ssh_alias, timeout_s) -> dict | None`
- Add `src/croam/commands/__init__.py` to Key Files section: package marker
- Add `src/croam/commands/emit_state.py` to Key Files section: `emit_state_cmd(home, state_root, hostname) -> int`
- Update Phase 3 section from placeholder to finalized: `ClaudeSession` field list, `discover_local_sessions` algorithm notes (sorted glob, multi-PID tie-break), `tmux_attached` spec
- Note in Data Models section: `~/.claude/sessions/<PID>.json` confirmed schema on 2026-04-30 against claude 2.1.123
- Note: `proc.CroamTimeoutError` (not `proc.ProcTimeoutError` as the brief says) -- both refer to `croam.errors.TimeoutError`; `proc` re-exports it as `CroamTimeoutError`

## Notes for Future Phases

- Phase 6: `emit_state_cmd` is signature-stable -- call `emit_state_cmd(home, state_root, hostname)` from the typer handler after resolving config. Do NOT touch `emit_state.py`.
- Phase 7: `fetch_remote_state` registers the shim with `["croam", "emit-state"]` (not `["croam", "emit-state", "--json"]`) because `fake_ssh` strips `--json`. When Phase 7 writes new SSH-command tests, use the same stripped argv for fixture registration.
- The 9 uncovered lines in `sessions.py` (tmux timeout paths 137-139, 149-151, 154-155, 166) are defensive error handlers requiring real subprocess timeouts. They cannot be covered without mocking `proc.run`, which the spec forbids. Coverage is 91% which exceeds the 90% gate.

---

**Phase Status:** COMPLETE
