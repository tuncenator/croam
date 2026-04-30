# Phase 5: Tmux integration & claude shim - Summary

**Date Completed:** 2026-04-30
**Completed By:** claude-sonnet-4-6 (agent-a0cee160f00c7109f)
**Actual Token Usage:** ~60k tokens

---

## Objective

Implement tmux subprocess wrappers, the claude shim decision logic, and the `croam launch` orchestrator that wraps interactive `claude` invocations inside a tmux session named `claude-<sid>`.

---

## Work Completed

### What Was Built

- `src/croam/tmux.py`: five argv-builders + five side-effecting wrappers. `kill_session` idempotency covers five distinct tmux server-state stderr substrings observed in real testing.
- `src/croam/shim.py`: five pure decision functions (`should_wrap`, `derive_sid`, `strip_no_tmux`, `find_claude_real`, `is_in_tmux`). 100% branch coverage.
- `src/croam/commands/__init__.py`: package marker with module docstring.
- `src/croam/commands/launch.py`: `LaunchPlan` frozen dataclass, `build_launch_plan` (pure), `launch_cmd` (assertion-before-side-effect, `--no-exec` mode).
- `src/croam/ownership.py`: Phase 4 stub satisfying the import contract (`Assertion`, `write_local_assertion`, `write_local_assertions`, `read_local_assertions`, `merge_assertions`, `flatten_local`). Will be superseded by Phase 4's real implementation at checkpoint merge.
- `tests/test_tmux.py`: 13 tests (argv-builder unit tests + real tmux integration via `tmux_socket` fixture).
- `tests/test_shim.py`: 24 tests (all branches of all five functions).
- `tests/test_launch.py`: 8 tests (5 plan-level + 2 launch_cmd integration + 1 assertion-persistence crash-safety).

### Files Created

- `src/croam/tmux.py` - tmux subprocess wrappers and pure argv builders
- `src/croam/shim.py` - pure shim decision functions
- `src/croam/commands/__init__.py` - package marker
- `src/croam/commands/launch.py` - launch orchestrator
- `src/croam/ownership.py` - Phase 4 stub (will be replaced at merge)
- `tests/test_tmux.py` - 13 real-tmux tests
- `tests/test_shim.py` - 24 pure-function tests
- `tests/test_launch.py` - 8 integration tests

### Files Modified

None (all new files).

### Key Design Decisions

- `should_wrap` receives the original `argv` (not `cleaned_argv`) so `--no-tmux` detection works before stripping. `claude_argv` is built from `cleaned_argv` (stripped). This is a deviation from the spec's literal code which passed `cleaned_argv` to `should_wrap` -- the spec's code would have silently broken the `--no-tmux` passthrough.
- `kill_session` idempotency extended beyond spec's two substrings to cover all observed tmux exit messages: `"can't find session"`, `"no server running"`, `"error connecting to"`, `"server exited unexpectedly"`, `"no current target"`. The last two appear when the inner command (fake claude) exits immediately and tmux auto-cleans the server.
- `list_sessions` similarly extended for `"server exited unexpectedly"` to handle the race in cleanup code.
- `stdin_isatty` resolution in `launch_cmd` uses an explicitly typed `resolved_isatty: bool` local to satisfy pyright's narrowing (the ternary `x if x is not None else y` pattern is not narrowed by pyright 1.1.x).
- Ownership stub written at `src/croam/ownership.py` with the full expected API so Phase 5 tests run in isolation without waiting for Phase 4. The checkpoint will overlay Phase 4's implementation.
- `test_launch_cmd_real_tmux` uses `monkeypatch.setenv("PATH", f"{bindir}:{original_path}")` (prepend not replace) so `tmux` remains reachable while `find_claude_real()` resolves to the fake binary.

---

## Completion Criteria Status

- [x] `src/croam/tmux.py` implements all five argv-builders and all five wrappers; `pytest tests/test_tmux.py -v` passes. Verified: 13 passed.
- [x] `src/croam/shim.py` implements `should_wrap`, `derive_sid`, `strip_no_tmux`, `find_claude_real`, `is_in_tmux`; `pytest tests/test_shim.py -v` passes. Verified: 24 passed.
- [x] `src/croam/commands/__init__.py` exists (empty with docstring). Verified: file present, ruff passes.
- [x] `src/croam/commands/launch.py` implements `LaunchPlan`, `build_launch_plan`, `launch_cmd`; `pytest tests/test_launch.py -v` passes. Verified: 8 passed.
- [x] `should_wrap` has 100% branch coverage. Verified: `uv run pytest tests/test_shim.py --cov=croam.shim --cov-report=term-missing` -> `src/croam/shim.py 36 0 100%`.
- [x] No call site of `os.execvp` lacks a corresponding argv-builder. Verified: two execvp call sites in `tmux.attach` and `launch_cmd`, both backed by `build_attach_argv` and `build_launch_plan` argv builders.
- [x] `launch_cmd` writes the ownership.json assertion BEFORE invoking tmux/exec. Verified: `test_assertion_persists_on_tmux_failure` passes (assertion on disk when `new_session_detached` raises).
- [x] All public functions have type hints and one-line docstrings. Verified: manual inspection.
- [x] `ruff check` passes on all phase files. Verified: `All checks passed!`
- [x] `pyright` passes on all phase src files. Verified: `0 errors, 0 warnings, 0 informations`.

### Deviations / Incomplete Items

- `commands/__init__.py` docstring used `"croam command handlers (one module per verb)."` (Phase 5 spec wording) not `"croam command modules. Each verb maps to one module here."` (Phase 3 spec wording). The merge will resolve which survives; both are correct.
- Ownership stub created at `src/croam/ownership.py` to unblock Phase 5 testing. This is a Phase 4 file by ownership, but the parallel execution required it. Phase 4's real implementation will replace it at checkpoint merge.

---

## Testing

### Tests Written

- `tests/test_tmux.py` (13 tests):
  - `test_build_has_session_argv`, `test_build_new_session_argv`, `test_build_attach_argv_default`, `test_build_attach_argv_read_only`, `test_build_kill_session_argv`, `test_build_list_sessions_argv` (argv builder unit tests)
  - `test_has_session_false_no_server`, `test_new_and_has`, `test_list_sessions_empty`, `test_list_sessions_three`, `test_idempotent_kill_no_session`, `test_idempotent_kill_no_server`, `test_new_session_failure_raises` (real tmux integration)

- `tests/test_shim.py` (24 tests):
  - `test_should_wrap_*` (9 tests covering all 7 short-circuit branches + default True)
  - `test_derive_sid_*` (5 tests: space form, equals form, mid-argv, dangling, no-resume)
  - `test_strip_no_tmux_*` (3 tests: present, absent, multiple)
  - `test_find_claude_real_*` (3 tests: prefers real, falls back, neither)
  - `test_is_in_tmux_*` (4 tests: set, empty, unset, whitespace)

- `tests/test_launch.py` (8 tests):
  - `test_build_launch_plan_wrap_path`
  - `test_build_launch_plan_passthrough_in_tmux`
  - `test_build_launch_plan_passthrough_print_flag`
  - `test_build_launch_plan_resume_uses_provided_sid`
  - `test_build_launch_plan_strips_no_tmux`
  - `test_launch_cmd_no_exec_writes_assertion`
  - `test_launch_cmd_real_tmux`
  - `test_assertion_persists_on_tmux_failure`

### Test Results

```
$ uv run pytest tests/test_tmux.py tests/test_shim.py tests/test_launch.py -v --tb=short
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.0.3, pluggy-1.6.0
collecting ... collected 45 items

tests/test_tmux.py::test_build_has_session_argv PASSED
tests/test_tmux.py::test_build_new_session_argv PASSED
tests/test_tmux.py::test_build_attach_argv_default PASSED
tests/test_tmux.py::test_build_attach_argv_read_only PASSED
tests/test_tmux.py::test_build_kill_session_argv PASSED
tests/test_tmux.py::test_build_list_sessions_argv PASSED
tests/test_tmux.py::test_has_session_false_no_server PASSED
tests/test_tmux.py::test_new_and_has PASSED
tests/test_tmux.py::test_list_sessions_empty PASSED
tests/test_tmux.py::test_list_sessions_three PASSED
tests/test_tmux.py::test_idempotent_kill_no_session PASSED
tests/test_tmux.py::test_idempotent_kill_no_server PASSED
tests/test_tmux.py::test_new_session_failure_raises PASSED
tests/test_shim.py::test_should_wrap_default PASSED
tests/test_shim.py::test_should_wrap_in_tmux PASSED
tests/test_shim.py::test_should_wrap_not_tty PASSED
tests/test_shim.py::test_should_wrap_no_tmux_flag PASSED
tests/test_shim.py::test_should_wrap_print_flag PASSED
tests/test_shim.py::test_should_wrap_help_long PASSED
tests/test_shim.py::test_should_wrap_help_short PASSED
tests/test_shim.py::test_should_wrap_opt_out_env_default_name PASSED
tests/test_shim.py::test_should_wrap_opt_out_env_custom_name PASSED
tests/test_shim.py::test_derive_sid_resume_space PASSED
tests/test_shim.py::test_derive_sid_resume_equals PASSED
tests/test_shim.py::test_derive_sid_resume_in_middle PASSED
tests/test_shim.py::test_derive_sid_resume_dangling PASSED
tests/test_shim.py::test_derive_sid_no_resume_returns_uuid PASSED
tests/test_shim.py::test_strip_no_tmux_present PASSED
tests/test_shim.py::test_strip_no_tmux_absent PASSED
tests/test_shim.py::test_strip_no_tmux_multiple PASSED
tests/test_shim.py::test_find_claude_real_prefers_real PASSED
tests/test_shim.py::test_find_claude_real_falls_back_to_claude PASSED
tests/test_shim.py::test_find_claude_real_neither PASSED
tests/test_shim.py::test_is_in_tmux_set PASSED
tests/test_shim.py::test_is_in_tmux_empty PASSED
tests/test_shim.py::test_is_in_tmux_unset PASSED
tests/test_shim.py::test_is_in_tmux_whitespace PASSED
tests/test_launch.py::test_build_launch_plan_wrap_path PASSED
tests/test_launch.py::test_build_launch_plan_passthrough_in_tmux PASSED
tests/test_launch.py::test_build_launch_plan_passthrough_print_flag PASSED
tests/test_launch.py::test_build_launch_plan_resume_uses_provided_sid PASSED
tests/test_launch.py::test_build_launch_plan_strips_no_tmux PASSED
tests/test_launch.py::test_launch_cmd_no_exec_writes_assertion PASSED
tests/test_launch.py::test_launch_cmd_real_tmux PASSED
tests/test_launch.py::test_assertion_persists_on_tmux_failure PASSED

============================== 45 passed in 0.17s ==============================
```

Full suite (no regressions):
```
$ uv run pytest -v --tb=short
102 passed, 1 skipped in 0.42s
```

---

## Evidence Captured

### tmux subprocess interface (exit codes and stderr text)

- **How captured**: `bash` session running tmux against a private socket (`/tmp/croam-capture.sock`, `/tmp/croam-capture2.sock`, `/tmp/croam-capture3.sock`). Captured on 2026-04-30.
- **Consumed by**: `src/croam/tmux.py` -- `kill_session` and `list_sessions` stderr substring checks.
- **Sample**:

  ```
  # No server / socket doesn't exist:
  tmux -S /tmp/croam-capture2.sock has-session -t notexist
  error connecting to /tmp/croam-capture2.sock (No such file or directory)
  EXIT=1

  tmux -S /tmp/croam-capture2.sock list-sessions -F "#{session_name}:#{session_attached}"
  error connecting to /tmp/croam-capture2.sock (No such file or directory)
  EXIT=1

  tmux -S /tmp/croam-capture2.sock kill-session -t notexist
  error connecting to /tmp/croam-capture2.sock (No such file or directory)
  EXIT=1

  # After server exits (session ended):
  tmux -S /tmp/croam-capture3.sock list-sessions ...
  server exited unexpectedly
  EXIT=1

  tmux -S /tmp/croam-capture3.sock has-session -t captest
  no server running on /tmp/croam-capture3.sock
  EXIT=1

  tmux -S /tmp/croam-capture3.sock kill-session -t captest
  no server running on /tmp/croam-capture3.sock
  EXIT=1

  # Session running, duplicate new-session:
  tmux -S $SOCK new-session -d -s captest -- sleep 30
  EXIT=0
  captest:0
  EXIT=0 (has-session)
  duplicate session: captest
  EXIT=1

  # Kill nonexistent session with server running:
  tmux -S $SOCK kill-session -t notexist
  can't find session: notexist
  EXIT=1
  ```

- **Notes**: The spec only documented `"can't find session"` and `"no server running"` as idempotent substrings. Real execution also produces `"error connecting to"` (no socket file), `"server exited unexpectedly"` (inner command exited causing auto-cleanup), and `"no current target"` (server has no sessions). All five are now handled.

### claude binary on PATH

- **How captured**: `which claude` on the host. `which claude-real` not present (pre-shim-install). Tests use a fake binary written into `tmp_path/bin/`.
- **Consumed by**: `src/croam/shim.py:find_claude_real()` -- only path existence matters.
- **Sample**: `/home/tunc/.local/bin/claude` (real host path; tests use tmp path)

---

## Helper Issues

No helpers listed for Phase 5. None invoked.

---

## Functional QA Results

### (shim surface, Loop A) should_wrap returns True for basic interactive case

- **Surface**: Surface 3 (shim wrapping decision)
- **Invocation**: `uv run python -c "from croam import shim; print(shim.should_wrap(argv=['claude'], env={}, stdin_isatty=True, in_tmux=False))"`
- **Observed outcome**:
  ```
  True
  ```
- **Verdict**: pass

### (shim surface, Loop A) should_wrap returns False for --print flag

- **Surface**: Surface 3 (shim wrapping decision)
- **Invocation**: `uv run python -c "from croam import shim; print(shim.should_wrap(argv=['claude', '--print', 'x'], env={}, stdin_isatty=True, in_tmux=False))"`
- **Observed outcome**:
  ```
  False
  ```
- **Verdict**: pass

### (shim surface, Loop A) derive_sid with --resume space form

- **Surface**: Surface 3 (shim wrapping decision)
- **Invocation**: `uv run python -c "from croam import shim; print(shim.derive_sid(argv=['claude', '--resume', 'abc-123'], env={}))"`
- **Observed outcome**:
  ```
  abc-123
  ```
- **Verdict**: pass

### (shim surface, Loop A) derive_sid with --resume= equals form

- **Surface**: Surface 3 (shim wrapping decision)
- **Invocation**: `uv run python -c "from croam import shim; print(shim.derive_sid(argv=['claude', '--resume=abc-123'], env={}))"`
- **Observed outcome**:
  ```
  abc-123
  ```
- **Verdict**: pass

### (launch surface, Loop A) launch_cmd no-exec writes plan and ownership.json

- **Surface**: Surface 1 (`croam launch` via `launch_cmd`)
- **Invocation**: Python script constructing Config, calling `launch_cmd(..., no_exec=True)`, reading stdout + ownership.json
- **Observed outcome**:
  ```
  FQA5 rc: 0
  FQA5 plan mode: wrap
  FQA5 plan sid: ea6f2b14-b84e-4dd8-911e-cfe756af8925
  FQA5 stdout JSON:
  {
    "mode": "wrap",
    "sid": "ea6f2b14-b84e-4dd8-911e-cfe756af8925",
    "claude_argv": ["/tmp/tmpx4j8lumt/home/bin/claude"],
    "cwd_normalized": "~",
    "tmux_session_name": "claude-ea6f2b14-b84e-4dd8-911e-cfe756af8925",
    "tmux_new_argv": ["tmux","new-session","-d","-s","claude-ea6f2b14-b84e-4dd8-911e-cfe756af8925","--","/tmp/tmpx4j8lumt/home/bin/claude"],
    "tmux_attach_argv": ["tmux","attach","-t","claude-ea6f2b14-b84e-4dd8-911e-cfe756af8925"],
    "passthrough_argv": null
  }
  FQA5 ownership.json:
  {
    "ea6f2b14-b84e-4dd8-911e-cfe756af8925": {
      "owner": "stormtree",
      "asserted_at": "2026-04-30T19:34:09.297945+00:00",
      "action": "create",
      "cwd_normalized": "~",
      "previous_owner": null
    }
  }
  ```
- **Verdict**: pass

### (launch surface, Loop A) tmux_new_argv matches expected pattern

- **Surface**: Surface 1 (`croam launch` via `launch_cmd`)
- **Invocation**: same as FQA5 above; `plan['tmux_new_argv']` inspected
- **Observed outcome**:
  ```
  FQA6 tmux_new_argv: ['tmux', 'new-session', '-d', '-s', 'claude-ea6f2b14-b84e-4dd8-911e-cfe756af8925', '--', '/tmp/tmpx4j8lumt/home/bin/claude']
  ```
- **Verdict**: pass -- matches `["tmux", "new-session", "-d", "-s", "claude-<sid>", "--", <claude-real-path>]`

### (launch surface, Loop A) real tmux session appears in tmux ls

- **Surface**: Surface 1 (real tmux integration)
- **Invocation**: Python script calling `launch_cmd` with patched `tmux.attach`, then `tmux -S <sock> ls`
- **Observed outcome**:
  ```
  FQA7 tmux ls output:
  claude-481a0836-f4a7-4c93-94b6-9637563ec873: 1 windows (created Thu Apr 30 22:34:21 2026)

  FQA7 sessions found: ['claude-481a0836-f4a7-4c93-94b6-9637563ec873']
  ```
- **Verdict**: pass

### (shim surface) is_in_tmux with empty TMUX returns False

- **Surface**: Surface 3 (shim wrapping decision)
- **Invocation**: `uv run python -c "from croam import shim; print(shim.is_in_tmux({'TMUX': ''}))"`
- **Observed outcome**:
  ```
  False
  ```
- **Verdict**: pass

### (launch surface) crash-safety: assertion persists when tmux fails

- **Surface**: Surface 1 (assertion-before-side-effect contract)
- **Invocation**: Python script patching `tmux.new_session_detached` to raise `TmuxError`, calling `launch_cmd`, reading ownership.json
- **Observed outcome**:
  ```
  FQA9 exception raised: injected tmux failure for FQA9
  FQA9 ownership.json (assertion persists):
  {
    "9c032b7e-eb03-468f-8f03-ccfb9d5d3376": {
      "owner": "stormtree",
      "asserted_at": "2026-04-30T19:34:32.467863+00:00",
      "action": "create",
      "cwd_normalized": "~",
      "previous_owner": null
    }
  }
  ```
- **Verdict**: pass -- TmuxError raised AND assertion on disk with `action=create`

### Anti-Patterns Watched For

- **Anti-pattern A (HOME redirect)**: all tests that touch the filesystem use the `home` fixture. Even pure argv-builder tests use `home` to satisfy the conftest safety guard.
- **Anti-pattern C (Mocked tmux misses session-naming bugs)**: `test_tmux.py` uses real tmux against `tmux_socket`. `subprocess.run` is not mocked. Only `tmux.attach` is monkeypatched in `test_launch_cmd_real_tmux` to prevent replacing the pytest process.

### Strategy Updates

No strategy updates.

---

## Challenges & Solutions

### Challenge 1: tmux idempotency edge cases

The spec documented two idempotent substrings (`"can't find session"`, `"no server running"`). Real testing exposed three more: `"error connecting to"` (no socket file exists), `"server exited unexpectedly"` (auto-cleanup after inner command exits), `"no current target"` (server has no sessions left). All five added to the idempotency check.

**Solution:** Captured real tmux output before writing the implementation (per Evidence Captured above). Added all observed substrings.

### Challenge 2: should_wrap receives cleaned vs original argv

The spec's `build_launch_plan` code called `should_wrap(argv=cleaned_argv, ...)` where `cleaned_argv` has `--no-tmux` stripped. This made `should_wrap`'s `"--no-tmux" in argv` check unreachable, silently breaking that passthrough path.

**Solution:** Pass original `argv` to `should_wrap`; use `cleaned_argv` only for constructing `claude_argv`.

### Challenge 3: pyright doesn't narrow ternary assignment to bool

`stdin_isatty = x if x is not None else sys.stdin.isatty()` remains `bool | None` for pyright.

**Solution:** Use `resolved_isatty: bool = ...` explicit type annotation on a new local, then pass `resolved_isatty` to `build_launch_plan`.

### Challenge 4: Phase 4 ownership.py not available (parallel phase)

Phase 4 runs in parallel; `ownership.py` didn't exist when Phase 5 needed to run its tests.

**Solution:** Created a minimal stub at `src/croam/ownership.py` implementing the full expected API. The checkpoint will overlay Phase 4's real implementation.

---

## Code Quality

### Formatting
- [x] Code formatted per project conventions (ruff format passes)
- [x] Imports/dependencies organized (ruff I001 clean)
- [x] No unused imports or dependencies

### Documentation
- [x] All public functions have one-line docstrings
- [x] Type annotations on all parameters and return types
- [x] Module-level docstrings present

### Linting
```
$ uv run ruff check src/croam/tmux.py src/croam/shim.py src/croam/commands/__init__.py src/croam/commands/launch.py tests/test_tmux.py tests/test_shim.py tests/test_launch.py
All checks passed!

$ uv run pyright src/croam/tmux.py src/croam/shim.py src/croam/commands/launch.py
0 errors, 0 warnings, 0 informations
```

---

## Dependencies

### Required by This Phase

- Phase 1: `errors.py` (`CroamError`, `TmuxError`), `log.py`, `conftest.py` fixtures
- Phase 2: `config.py` (`Config`, nested dataclasses), `paths.py` (`normalize_cwd`)
- Phase 4: `ownership.py` (`Assertion`, `write_local_assertion`) -- stubbed locally for parallel execution

### Unblocked Phases

- Phase 6: `cli.py` can now dispatch `croam launch` to `launch_cmd`
- Phase 7: `commands/attach.py` can use `tmux.has_session`, `tmux.new_session_detached`, `tmux.attach`
- Phase 8: `commands/claim.py` can use `tmux.kill_session`

---

## Codebase Context Updates

- Add `src/croam/tmux.py` to Key Files table: "tmux subprocess wrappers (argv-builders + side-effecting wrappers)"
- Add `src/croam/shim.py` to Key Files table: "Pure shim decision functions (should_wrap, derive_sid, strip_no_tmux, find_claude_real, is_in_tmux)"
- Add `src/croam/commands/__init__.py` to Key Files table: "package marker"
- Add `src/croam/commands/launch.py` to Key Files table: "launch orchestrator (LaunchPlan, build_launch_plan, launch_cmd)"
- Add `src/croam/ownership.py` to Key Files table: "Phase 4 stub -- will be replaced at merge"
- Update Phase 5 API section in CODEBASE_CONTEXT.md with actual signatures (they differ from the placeholder stubs):
  - `has_session(name, sock)` not `has_session(sock, name)` (order swapped vs placeholder)
  - `list_sessions(sock)` returns `list[tuple[str, bool]]` not `list[str]`
  - `attach(name, *, sock, read_only)` not `attach(sock, name, read_only)` and type is `NoReturn` not `int`
  - `should_wrap` signature includes `in_tmux: bool` and `opt_out_env_name: str` parameters not in the placeholder

## Notes for Future Phases

- `kill_session` is now idempotent for five distinct tmux server-state substrings. Phase 7/8 can call it safely in cleanup without checking session existence first.
- `build_launch_plan` is pure and testable without any filesystem access (except `find_claude_real` which uses `shutil.which`). Phase 6 can test the full dispatch path by calling `build_launch_plan` directly.
- The ownership stub at `src/croam/ownership.py` implements atomic write via `os.replace` and the full merge/flatten API. Phase 4's real implementation must maintain the same JSON schema: `{sid: {owner, asserted_at, action, cwd_normalized, previous_owner}}`.
- `LaunchPlan` is frozen. Future phases that need to add fields must add them as optional with defaults to avoid breaking existing callers.

---

## Next Steps

**Next Phase:** Phase 6 - CLI dispatcher and picker

**Recommended Actions:**

1. Proceed to Phase 6 which wires `launch_cmd` into the typer CLI.
2. Phase 4 ownership implementation will be merged at checkpoint -- verify the JSON schema matches the stub's format.
3. The `commands/__init__.py` docstring conflict (Phase 3 vs Phase 5 wording) will need checkpoint resolution.
