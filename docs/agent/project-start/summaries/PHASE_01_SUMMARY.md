# Phase 1: Foundation: project skeleton, logging, test harness - Summary

**Date Completed:** 2026-04-30
**Completed By:** Spark coding agent (Phase 1)

---

## Objective

Establish the croam Python project: `pyproject.toml` (uv-managed, `uv_build` backend, console script `croam = "croam.cli:app"`), the `src/croam/` package skeleton, the loguru logging module, the typed errors module, the `proc.run` subprocess wrapper, and the pytest test harness with every fixture future phases depend on.

---

## Work Completed

### What Was Built

- Project root scaffold: `pyproject.toml`, `.python-version`, `.gitignore`, `README.md`, `uv.lock`
- Source package: `src/croam/__init__.py`, `cli.py` (typer stub with callback), `errors.py` (CroamError hierarchy), `log.py` (loguru configure), `proc.py` (subprocess wrapper)
- Test harness: `tests/conftest.py` with 5 fixtures + hookwrapper safety guard, 3 test helpers under `tests/_helpers/`, and `tests/test_smoke.py` with 14 passing tests

### Files Created

- `pyproject.toml` - uv-managed metadata, runtime/dev deps, tool configs
- `.python-version` - Python 3.11
- `.gitignore` - standard Python ignores
- `README.md` - minimal stub
- `uv.lock` - generated lockfile (committed)
- `src/croam/__init__.py` - empty package marker
- `src/croam/cli.py` - typer stub with `@app.callback(invoke_without_command=True)`
- `src/croam/errors.py` - CroamError + 7 subclasses
- `src/croam/log.py` - loguru configure() with stderr + optional JSON file sink
- `src/croam/proc.py` - subprocess.run wrapper with DEBUG logging and TimeoutError translation
- `tests/__init__.py` - empty
- `tests/_helpers/__init__.py` - empty
- `tests/_helpers/synth_jsonl.py` - build_jsonl() with inlined _encode_cwd
- `tests/_helpers/synth_session.py` - build_session_metadata()
- `tests/_helpers/fake_ssh.py` - SSH_SHIM_SCRIPT + fixture_path_for()
- `tests/conftest.py` - home, tmux_socket, state_root, ssh_shim, e2e_dummy fixtures + safety guard
- `tests/test_smoke.py` - 14 tests

### Key Design Decisions

- Safety guard implemented as `pytest_runtest_call` hookwrapper instead of autouse fixture. Autouse fixtures execute before the test's own fixtures (like `home`) in dependency order, causing the guard to fire before HOME is redirected. The hookwrapper fires after all fixture setup completes, so by the time it checks HOME, the `home` fixture has already redirected it via monkeypatch.
- The guard logic is extracted into `_check_home_redirected(home, e2e)` so it can be tested in isolation via `test_safety_guard_logic`.
- The fake SSH shim uses a Python shebang (`#!/usr/bin/env python3`) instead of bash to avoid shell-quoting hazards. Argv hash is `sha1(json.dumps(argv, sort_keys=True))[:16]`.
- `synth_jsonl._encode_cwd` is intentionally duplicated from the future Phase 2 `paths.encode_cwd`. This ensures the test helper has zero src/ dependencies and works standalone.
- The typer stub requires a `@app.callback(invoke_without_command=True)` to make `croam --help` work. A bare `typer.Typer()` with no commands and no callback raises `RuntimeError: Could not get a command for this Typer instance`.

---

## Completion Criteria Status

- [x] `uv sync` exits 0 from the project root - Verified: `uv sync` resolves 23 packages, installs 20
- [x] `uv.lock` exists and is committed - Verified: `ls uv.lock` shows 424 lines, tracked in git
- [x] `uv run croam --help` exits 0 (typer stub registered) - Verified: exits 0, prints "croam" and "Options" section
- [x] `uv run python -c "from croam import log; log.configure()"` exits 0 - Verified: no errors
- [x] `uv run python -c "from croam.errors import CroamError, ConfigError, SshError, OwnershipConflict, TmuxError, SessionNotFound, OrphanRefused"` exits 0 - Verified: all imports succeed
- [x] `uv run python -c "from croam.proc import run; print(run(['true']).returncode)"` prints `0` - Verified: prints 0
- [x] `uv run pytest tests/test_smoke.py -v` exits 0 with all named tests passing - Verified: 14 passed in 0.20s
- [x] `uv run ruff check src tests` exits 0 - Verified: "All checks passed!"
- [x] `uv run ruff format --check src tests` exits 0 - Verified: "12 files already formatted"
- [x] `uv run pyright src tests` exits 0 - Verified: "0 errors, 0 warnings, 0 informations"
- [x] Safety guard present, refuses unredirected HOME - Verified: `test_safety_guard_logic` passes; external subprocess test with `HOME=/home/tunc` and no `home` fixture produces "HOME is not redirected" failure
- [x] All seven required harness fixtures exist: `home`, `tmux_socket`, `ssh_shim`, `state_root`, `e2e_dummy`, safety guard hook, plus `synth_jsonl` and `synth_session` helpers
- [x] No file outside the deliverables list created in `src/croam/` or `tests/`

---

## Testing

### Tests Written

- `tests/test_smoke.py`
  - test_home_redirect
  - test_tmux_socket_path_resolves
  - test_state_root_has_default_hosts
  - test_ssh_shim_basic
  - test_ssh_shim_with_args
  - test_ssh_shim_failure
  - test_synth_jsonl
  - test_synth_session
  - test_log_configure_default
  - test_log_configure_with_file
  - test_errors_import
  - test_proc_run_basic
  - test_proc_run_timeout
  - test_safety_guard_logic

### Test Results

```
$ uv run pytest tests/test_smoke.py -v
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.0.3, pluggy-1.6.0 -- .venv/bin/python
cachedir: .pytest_cache
rootdir: /home/tunc/Sync/Programs/croam/.claude/worktrees/agent-a2b907e97bed12a8a
configfile: pyproject.toml
plugins: cov-7.1.0
collecting ... collected 14 items

tests/test_smoke.py::test_home_redirect PASSED                           [  7%]
tests/test_smoke.py::test_tmux_socket_path_resolves PASSED               [ 14%]
tests/test_smoke.py::test_state_root_has_default_hosts PASSED            [ 21%]
tests/test_smoke.py::test_ssh_shim_basic PASSED                          [ 28%]
tests/test_smoke.py::test_ssh_shim_with_args PASSED                      [ 35%]
tests/test_smoke.py::test_ssh_shim_failure PASSED                        [ 42%]
tests/test_smoke.py::test_synth_jsonl PASSED                             [ 50%]
tests/test_smoke.py::test_synth_session PASSED                           [ 57%]
tests/test_smoke.py::test_log_configure_default PASSED                   [ 64%]
tests/test_smoke.py::test_log_configure_with_file PASSED                 [ 71%]
tests/test_smoke.py::test_errors_import PASSED                           [ 78%]
tests/test_smoke.py::test_proc_run_basic PASSED                          [ 85%]
tests/test_smoke.py::test_proc_run_timeout PASSED                        [ 92%]
tests/test_smoke.py::test_safety_guard_logic PASSED                      [100%]

============================== 14 passed in 0.20s ==============================
```

---

## Evidence Captured

### tomllib parse of pyproject.toml

- **How captured**: `uv run python -c "import tomllib; print(list(tomllib.load(open('pyproject.toml','rb')).keys()))"`
- **Captured on**: 2026-04-30 against local pyproject.toml
- **Consumed by**: uv build system (reads pyproject.toml at sync time)
- **Sample**:

  ```
  ['project', 'build-system', 'dependency-groups', 'tool']
  ```

### loguru serialize=True record shape

- **How captured**: `uv run python -c "from pathlib import Path; from croam import log; from loguru import logger; p = Path('/tmp/croam-phase1-loguru.log'); log.configure(level='DEBUG', log_file=p, debug=True); logger.info('capture-shape'); logger.complete(); print(p.read_text())"`
- **Captured on**: 2026-04-30 against loguru 0.7.3
- **Consumed by**: `tests/test_smoke.py::test_log_configure_with_file` reads record["record"]["message"]
- **Sample**:

  ```json
  {"text": "capture-shape\n", "record": {"elapsed": {"repr": "0:00:00.010482", "seconds": 0.010482}, "exception": null, "extra": {}, "file": {"name": "<string>", "path": "<string>"}, "function": "<module>", "level": {"icon": "ℹ️", "name": "INFO", "no": 20}, "line": 7, "message": "capture-shape", "module": "<string>", "name": "__main__", "process": {"id": 1477033, "name": "MainProcess"}, "thread": {"id": 140569590847296, "name": "MainThread"}, "time": {"repr": "2026-04-30 21:41:25.551087+03:00", "timestamp": 1777574485.551087}}}
  ```

### subprocess.CompletedProcess shape

- **How captured**: `uv run python -c "import subprocess; r = subprocess.run(['echo', 'hi'], capture_output=True, text=True); print(repr(r))"`
- **Captured on**: 2026-04-30, Python 3.11.15
- **Consumed by**: `src/croam/proc.py:run()` returns this type; callers unpack `.returncode`, `.stdout`, `.stderr`
- **Sample**:

  ```
  CompletedProcess(args=['echo', 'hi'], returncode=0, stdout='hi\n', stderr='')
  ```

### typer.Typer constructor signature

- **How captured**: `uv run python -c "import inspect, typer; print(inspect.signature(typer.Typer.__init__))"`
- **Captured on**: 2026-04-30, typer 0.25.0
- **Consumed by**: `src/croam/cli.py` constructs `app = typer.Typer(name=..., pretty_exceptions_enable=..., add_completion=..., no_args_is_help=...)`
- **Notes**: All four kwargs confirmed present in typer 0.25.0. The `invoke_without_command` kwarg (used on `@app.callback`) is also present.

---

## Helper Issues

No helpers were listed for Phase 1. None were invoked.

---

## Functional QA Results

### Check 1: Surface 4, Loop A -- uv sync + pytest

- **Surface**: Surface 4 (per-host state files, harness foundation)
- **Invocation**: `uv sync && uv run pytest tests/test_smoke.py -v`
- **Observed outcome**:

  ```
  Resolved 23 packages in 0.59ms
  Checked 20 packages in 0.25ms
  ---UV-SYNC-OK---
  tests/test_smoke.py::test_home_redirect PASSED                           [  7%]
  tests/test_smoke.py::test_tmux_socket_path_resolves PASSED               [ 14%]
  tests/test_smoke.py::test_state_root_has_default_hosts PASSED            [ 21%]
  tests/test_smoke.py::test_ssh_shim_basic PASSED                          [ 28%]
  tests/test_smoke.py::test_ssh_shim_with_args PASSED                      [ 35%]
  tests/test_smoke.py::test_ssh_shim_failure PASSED                        [ 42%]
  tests/test_smoke.py::test_synth_jsonl PASSED                             [ 50%]
  tests/test_smoke.py::test_synth_session PASSED                           [ 57%]
  tests/test_smoke.py::test_log_configure_default PASSED                   [ 64%]
  tests/test_smoke.py::test_log_configure_with_file PASSED                 [ 71%]
  tests/test_smoke.py::test_errors_import PASSED                           [ 78%]
  tests/test_smoke.py::test_proc_run_basic PASSED                          [ 85%]
  tests/test_smoke.py::test_proc_run_timeout PASSED                        [ 92%]
  tests/test_smoke.py::test_safety_guard_logic PASSED                      [100%]
  ============================== 14 passed in 0.20s ==============================
  ```

- **Verdict**: pass

### Check 2: Surface 1, Loop A -- croam --help

- **Surface**: Surface 1 (CLI verbs)
- **Invocation**: `uv run croam --help`
- **Observed outcome**:

  ```
   Usage: croam [OPTIONS] COMMAND [ARGS]...

   croam: cross-host claude-code session manager.

  -- Options --
    --help          Show this message and exit.
  ```

  Output contains "croam" (program name) and "Options" (standard typer help section). Exit code 0.

- **Verdict**: pass

### Check 3: Harness, Loop A -- safety guard blocks unredirected HOME

- **Surface**: Harness
- **Invocation**: Created `tests/test_guard_check.py` with `def test_guard_should_block(): assert True` (no `home` fixture), ran with `HOME=/home/tunc uv run pytest tests/test_guard_check.py -v`
- **Observed outcome**:

  ```
  RETURNCODE: 1
  tests/test_guard_check.py::test_guard_should_block FAILED                [100%]
                  f"HOME is not redirected (HOME={home!r}); refusing to run. "
  E           Failed: HOME is not redirected (HOME='/home/tunc'); refusing to run. Use the `home` fixture or set CROAM_E2E=1.
  tests/conftest.py:35: Failed
  FAILED tests/test_guard_check.py::test_guard_should_block - Failed: HOME is n...
  ============================== 1 failed in 0.02s ===============================
  ```

- **Verdict**: pass

### Check 4: Harness, fixture round-trip -- synth_jsonl encoding

- **Surface**: Harness
- **Invocation**: `uv run python -c "from pathlib import Path; from tests._helpers.synth_jsonl import build_jsonl; import tempfile; t = Path(tempfile.mkdtemp()); (t/'home/.claude/projects').mkdir(parents=True); p = build_jsonl(t/'home', 'test-sid-123', Path('/tmp/croam-e2e'), n_user=3); print(p); print(p.read_text()[:500])"`
- **Observed outcome**:

  ```
  /tmp/tmpzu7hh9u1/home/.claude/projects/-tmp-croam-e2e/test-sid-123.jsonl
  {"type": "last-prompt", "leafUuid": "0a50dcbd-b835-49b9-b932-5fe55a0b6cc8", "sessionId": "test-sid-123"}
  {"type": "permission-mode", "permissionMode": "default", "sessionId": "test-sid-123"}
  {"parentUuid": "11cc3a0e-32f9-4095-9258-04bf2b45f3ca", ...
  ```

  Parent dir is `-tmp-croam-e2e` (correct encoded-cwd).

- **Verdict**: pass

### Check 5: Harness, log file sink

- **Surface**: Harness
- **Invocation**: `uv run python -c "from pathlib import Path; from croam import log; from loguru import logger; p = Path('/tmp/croam-phase1-test.log'); log.configure(level='DEBUG', log_file=p, debug=True); logger.info('phase1-qa-sink-line'); logger.complete(); print(p.read_text()[:500]); p.unlink()"`
- **Observed outcome**:

  ```json
  {"text": "phase1-qa-sink-line\n", "record": {"elapsed": {"repr": "0:00:00.010944", "seconds": 0.010944}, "exception": null, "extra": {}, "file": {"name": "<string>", "path": "<string>"}, "function": "<module>", "level": {"icon": "ℹ️", "name": "INFO", "no": 20}, "line": 7, "message": "phase1-qa-sink-line", ...}}
  ```

- **Verdict**: pass

### Check 6: Harness, ssh shim end-to-end

- **Surface**: Harness
- **Invocation**: `uv run pytest tests/test_smoke.py::test_ssh_shim_basic tests/test_smoke.py::test_ssh_shim_with_args tests/test_smoke.py::test_ssh_shim_failure -v`
- **Observed outcome**:

  ```
  tests/test_smoke.py::test_ssh_shim_basic PASSED                          [ 33%]
  tests/test_smoke.py::test_ssh_shim_with_args PASSED                      [ 66%]
  tests/test_smoke.py::test_ssh_shim_failure PASSED                        [100%]
  ============================== 3 passed in 0.07s ===============================
  ```

- **Verdict**: pass

### Check 7: Tier 2 (optional)

- **Surface**: Harness (Tier 2)
- **Invocation**: `ls -la /tmp/croam-e2e/`
- **Observed outcome**: Directory exists but is empty (no dummy session data populated).
- **Verdict**: skipped (no dummy session data at /tmp/croam-e2e/)

### Anti-Patterns Watched For

- **A. Tests that don't redirect HOME**: every smoke test takes the `home` fixture. The `test_tmux_socket_path_resolves` was updated to include `home` as well. The safety guard hookwrapper blocks tests without HOME redirect.
- **B. Mocking subprocess.run**: `proc.run` tests use real `true`, `false`, `sleep` binaries. SSH shim tests use the real fake-ssh binary on PATH via OS-level dispatch.
- **G. Forgetting to commit uv.lock**: `uv.lock` is tracked and committed (424 lines).

### Strategy Updates

No strategy updates. Phase 1 uncovered no new surfaces or anti-patterns beyond what was already documented.

---

## Code Quality

### Formatting
- [x] Code formatted per project conventions (`uv run ruff format --check` passes)
- [x] Imports organized (ruff I001 auto-fixed)
- [x] No unused imports

### Documentation
- [x] All public functions have one-line docstrings
- [x] Type annotations on all public signatures
- [x] Module-level docstrings present

### Linting
```
$ uv run ruff check src tests
All checks passed!

$ uv run pyright src tests
0 errors, 0 warnings, 0 informations
```

---

## Dependencies

### Required by This Phase
None. This is the foundation phase.

### Unblocked Phases
- Phase 2: Config and paths (consumes errors.ConfigError, conftest fixtures, synth_jsonl)
- Phase 3: Sessions and host probes (consumes errors, proc.run, home, ssh_shim, state_root, synth_jsonl, synth_session)
- Phase 4: Ownership state (consumes errors, state_root)
- Phase 5: Tmux and shim (consumes errors, proc.run, tmux_socket, home)
- Phase 6-11: all transitively depend on the harness

---

## Codebase Context Updates

- Added `pyproject.toml` to Key Files (project metadata, deps, console script, tool configs)
- Added `src/croam/__init__.py` to Key Files (package marker)
- Added `src/croam/cli.py` to Key Files (typer stub with callback; Phase 6 replaces)
- Added `src/croam/log.py` to Key Files (loguru configure with FilterDict-typed filter_map)
- Added `src/croam/errors.py` to Key Files (CroamError hierarchy, 7 subclasses)
- Added `src/croam/proc.py` to Key Files (subprocess wrapper)
- Added `tests/conftest.py` to Key Files (5 fixtures + hookwrapper safety guard)
- Added `tests/_helpers/synth_jsonl.py` to Key Files (build_jsonl with inlined _encode_cwd)
- Added `tests/_helpers/synth_session.py` to Key Files (build_session_metadata)
- Added `tests/_helpers/fake_ssh.py` to Key Files (SSH_SHIM_SCRIPT + fixture_path_for)
- Updated "Patterns and Conventions" note: safety guard is a `pytest_runtest_call` hookwrapper (not autouse fixture) to ensure it runs after all fixture setup. Tests that don't use `home` must still be aware the guard will fire.
- Note for Phase 2: `_encode_cwd` in synth_jsonl.py is a standalone copy. Phase 2's test_paths.py should verify `paths.encode_cwd` matches `synth_jsonl._encode_cwd` for representative paths.

## Notes for Future Phases

- The typer stub in `cli.py` uses `@app.callback(invoke_without_command=True)`. Phase 6 replaces this entirely.
- The safety guard uses `pytest_runtest_call` hookwrapper, not an autouse fixture. Future phases adding tests must include `home` in any test that touches the filesystem, or the guard will reject the test.
- `log.configure()` uses `filter_map: dict[str | None, str | int | bool]` for pyright compatibility with loguru's FilterDict type.
- `synth_jsonl._encode_cwd` is a standalone implementation. Do not import from `src/croam/paths.py` (which doesn't exist yet). Phase 2 owns the canonical implementation.
- The `e2e_dummy` fixture skips when `/tmp/croam-e2e` has no data. Phase 2 or later should populate the dummy.

---

## Integration Points

- `pyproject.toml` `[project.scripts] croam = "croam.cli:app"` wires the console script
- `tests/conftest.py` is auto-discovered by pytest for all tests under `tests/`
- `tests/_helpers/` modules are imported by conftest and by individual test files
- `src/croam/proc.py` imports from `src/croam/errors.py`
- `src/croam/log.py` re-exports `logger` from loguru

---

## Known Issues / Technical Debt

None. All completion criteria met. No TODOs or FIXMEs left.

---

## Security Considerations

- Tests never touch the real `~/.claude` tree (safety guard enforced)
- No credentials, tokens, or secrets stored in any file
- SSH shim is test-only; never deployed to PATH outside test runs

---

## Next Steps

**Next Phase:** 2 - Config and paths

**Recommended Actions:**
1. Phase 2 creates `src/croam/config.py` and `src/croam/paths.py`
2. Phase 2 should cross-verify `paths.encode_cwd` matches `synth_jsonl._encode_cwd` for at least three paths
3. Phase 2 should populate the `/tmp/croam-e2e` dummy if Tier 2 tests are desired
