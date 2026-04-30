# Phase 6: Picker & CLI dispatcher - Summary

**Date Completed:** 2026-04-30
**Completed By:** Spark agent (Phase 6, Batch 4)

---

## Objective

Wire the typer CLI app with all global flags and the full verb set (mostly stubs, filled in by phases 7-9), and implement the fzf picker (row layout, hidden filter columns, multi-select intersection, dispatch via --expect). After this phase, `croam --help` lists every public verb, `croam emit-state` returns valid JSON, and the picker can be driven end-to-end against a fake-fzf fixture.

---

## Work Completed

### What Was Built

- Replaced the Phase 1 `cli.py` stub with the full typer app: 7 public verbs (ls, attach, peek, claim, fork, launch, doctor) plus hidden emit-state. Global callback wires --debug, --json, --all, -p, --host, --last, --orphans. No-verb path dispatches to picker. main() wraps app() with CroamError -> SystemExit(2) translation.
- Implemented `picker.py` with PickerRow dataclass, 5 pure formatting functions, render_rows joining sessions/assertions/host_statuses/lineage, format_input_lines wire-format encoder, build_fzf_argv constructor, launch_picker subprocess orchestrator, and compute_action_intersection for multi-select.
- Implemented `commands/default.py` orchestrator: discover_local_sessions + read_local_assertions + merge_assertions + probe_reachability -> render_rows -> launch_picker -> stub dispatch.
- Created `tests/_helpers/fake_fzf.py` helper for deterministic fzf subprocess testing.
- Updated `pyproject.toml` entry point from `croam.cli:app` to `croam.cli:main`.

### Files Created

- `src/croam/picker.py` - fzf picker: PickerRow dataclass, pure formatters, render_rows, launch_picker, compute_action_intersection
- `src/croam/commands/default.py` - no-verb picker orchestrator with stub dispatch
- `tests/test_picker.py` - 24 tests (10 parametrized format_last_column + 14 other picker tests)
- `tests/test_cli.py` - 5 tests for CLI surface
- `tests/_helpers/fake_fzf.py` - fake-fzf shell script generator

### Files Modified

- `src/croam/cli.py` - Full rewrite from Phase 1 stub (Phase 6 has full ownership)
- `pyproject.toml` - Entry point changed from `croam.cli:app` to `croam.cli:main`

### Key Design Decisions

- **SystemExit(2) instead of typer.Exit(2)**: `main()` catches `CroamError` and raises `SystemExit(2)` because `typer.Exit` raised outside click's context manager results in exit code 1, not the intended 2.
- **Mapping[str, object] for assertion/lineage params**: Used `Mapping` (covariant in value type) instead of `dict` (invariant) to allow `dict[str, Assertion]` to pass pyright without casts. Protected under `TYPE_CHECKING` to avoid runtime import.
- **Empty rows short-circuit**: `launch_picker` returns `("", [])` without launching fzf when rows list is empty, avoiding a subprocess call that would confuse fzf.
- **_resolve_cwd uses Path.home()**: For cwd resolution, uses Path.home() (redirected by tests via HOME env) unless host_homes dict is provided.

---

## Completion Criteria Status

- [x] `src/croam/cli.py` rewritten with all 8 verbs (7 visible + emit-state hidden) - Verified: `uv run croam --help` shows 7 verbs, `emit-state` absent
- [x] `pyproject.toml` entry updated from `croam.cli:app` to `croam.cli:main` - Verified: grep confirms `croam = "croam.cli:main"`
- [x] `src/croam/picker.py` exposes all required public functions - Verified: all imports resolve in test_picker.py
- [x] `src/croam/commands/__init__.py` exists (unchanged from Phase 3) - Verified: file present
- [x] `src/croam/commands/default.py` exists - Verified: file present with run_picker orchestrator
- [x] `tests/_helpers/fake_fzf.py` exposes make_fake_fzf - Verified: imported and used in test_picker.py
- [x] `tests/test_cli.py` passes all 5 tests - Verified: `uv run pytest tests/test_cli.py -v` 5 passed
- [x] `tests/test_picker.py` passes all tests (24 including 10 parametrized) - Verified: `uv run pytest tests/test_picker.py -v` 24 passed
- [x] `uv run croam --help` lists verbs, hides emit-state - Verified: output captured below
- [x] `uv run croam emit-state` exits 0 with parseable JSON (with config) - Verified: test_emit_state_runs passes
- [x] `uv run croam --debug ls` reaches global callback - Verified: raises NotImplementedError("Phase 7") after configuring logging
- [x] `uv run pytest -v` exits 0 across full suite - Verified: 208 passed, 2 skipped
- [x] `ruff check src/ tests/` exits 0 - Verified: All checks passed
- [x] `pyright src/` exits 0 - Verified: 0 errors, 0 warnings, 0 informations

---

## Testing

### Tests Written

- `tests/test_cli.py`
  - test_help_shows_verbs
  - test_help_does_not_show_emit_state
  - test_emit_state_runs
  - test_global_debug_flag
  - test_top_level_croam_error_handler

- `tests/test_picker.py`
  - test_format_last_column (10 parametrized cases)
  - test_format_input_lines_exact_shape
  - test_format_input_lines_scrubs_tabs_and_newlines
  - test_format_input_lines_empty
  - test_render_rows_with_lineage
  - test_render_rows_missing_cwd
  - test_compute_action_intersection_excludes_claim_and_fork_when_unreachable_or_missing
  - test_compute_action_intersection_empty
  - test_build_fzf_argv_includes_required_flags
  - test_build_fzf_argv_no_pwd
  - test_launch_picker_happy_path
  - test_launch_picker_cancel
  - test_launch_picker_no_match
  - test_launch_picker_error
  - test_launch_picker_refuses_non_tty

### Test Results

```
$ uv run pytest tests/test_cli.py tests/test_picker.py -v
tests/test_cli.py::test_help_shows_verbs PASSED
tests/test_cli.py::test_help_does_not_show_emit_state PASSED
tests/test_cli.py::test_emit_state_runs PASSED
tests/test_cli.py::test_global_debug_flag PASSED
tests/test_cli.py::test_top_level_croam_error_handler PASSED
tests/test_picker.py::test_format_last_column[None--] PASSED
tests/test_picker.py::test_format_last_column[30000-0m] PASSED
tests/test_picker.py::test_format_last_column[840000-14m] PASSED
tests/test_picker.py::test_format_last_column[3600000-1h] PASSED
tests/test_picker.py::test_format_last_column[169200000-47h] PASSED
tests/test_picker.py::test_format_last_column[172800000-2D] PASSED
tests/test_picker.py::test_format_last_column[432000000-5D] PASSED
tests/test_picker.py::test_format_last_column[2592000000-30D] PASSED
tests/test_picker.py::test_format_last_column[2678400000-1M] PASSED
tests/test_picker.py::test_format_last_column[5184000000-2M] PASSED
tests/test_picker.py::test_format_input_lines_exact_shape PASSED
tests/test_picker.py::test_format_input_lines_scrubs_tabs_and_newlines PASSED
tests/test_picker.py::test_format_input_lines_empty PASSED
tests/test_picker.py::test_render_rows_with_lineage PASSED
tests/test_picker.py::test_render_rows_missing_cwd PASSED
tests/test_picker.py::test_compute_action_intersection_excludes_claim_and_fork_when_unreachable_or_missing PASSED
tests/test_picker.py::test_compute_action_intersection_empty PASSED
tests/test_picker.py::test_build_fzf_argv_includes_required_flags PASSED
tests/test_picker.py::test_build_fzf_argv_no_pwd PASSED
tests/test_picker.py::test_launch_picker_happy_path PASSED
tests/test_picker.py::test_launch_picker_cancel PASSED
tests/test_picker.py::test_launch_picker_no_match PASSED
tests/test_picker.py::test_launch_picker_error PASSED
tests/test_picker.py::test_launch_picker_refuses_non_tty PASSED
29 passed in 0.25s
```

Full suite:

```
$ uv run pytest -q
208 passed, 2 skipped in 3.19s
```

### Coverage

```
$ uv run pytest --cov=croam.cli --cov=croam.picker --cov-report=term-missing tests/test_cli.py tests/test_picker.py
Name                  Stmts   Miss  Cover   Missing
---------------------------------------------------
src/croam/cli.py         55     20    64%   54-59, 77, 86, 96, 106, 113-117, 129, 150-154
src/croam/picker.py     152     14    91%   65, 72, 75-77, 106, 166-168, 268, 285, 289, 293, 305
---------------------------------------------------
TOTAL                   207     34    84%
```

picker.py at 91% (target >= 90%). cli.py at 64% (target >= 80%, acknowledged lower due to stub verb handlers). Uncovered cli.py lines are all `NotImplementedError("Phase N")` stubs.

---

## Evidence Captured

### fzf stdin/stdout protocol

- **How captured**: Verified via fake-fzf shell script in test_launch_picker_happy_path; also confirmed fzf 0.70.0 on PATH via `fzf --version`
- **Captured on**: 2026-04-30 against fzf 0.70.0 (eacef5ea)
- **Consumed by**: `src/croam/picker.py:launch_picker` (lines 240-305), `build_fzf_argv` (lines 204-228)
- **Sample** (from test happy path, fake fzf output):

  ```
  p\nrow1-sid\to\trunning-idle\treachable\tpresent\th\t-\t~\tr1\nrow2-sid\to\trunning-idle\treachable\tpresent\th\t-\t~\tr2\n
  ```

  First line = expect key "p", subsequent lines = selected rows verbatim (tab-delimited). Exit code 0 = selected.

### typer.testing.CliRunner output shape

- **How captured**: REPL invocation in test development
- **Captured on**: 2026-04-30, typer >= 0.21.0
- **Consumed by**: `tests/test_cli.py` (all 5 tests)
- **Sample**: `CliRunner()` (no `mix_stderr` param). `result.exit_code`, `result.output`, `result.exception` are the key attributes. `result.stderr` exists but typer's CliRunner does not separate stderr from stdout.
- **Notes**: Phase plan assumed `CliRunner(mix_stderr=False)` which is a click-only kwarg. Adjusted to plain `CliRunner()`.

---

## Functional QA Results

### (Surface 1, Loop A) --help lists public verbs, hides emit-state

- **Surface**: Surface 1 (CLI verbs)
- **Invocation**: `CliRunner().invoke(app, ["--help"])`
- **Observed outcome**:

  ```
  exit_code: 0
  Commands section contains: ls, attach, peek, claim, fork, launch, doctor
  "emit-state" NOT in output
  ```

- **Verdict**: pass

### (Surface 1, Loop A) emit-state returns valid JSON

- **Surface**: Surface 1 (CLI verbs)
- **Invocation**: `CliRunner().invoke(app, ["emit-state"])` with redirected HOME and config
- **Observed outcome**:

  ```
  exit_code: 0
  payload keys: ['host_cache', 'hostname', 'lineage', 'ownership', 'sessions']
  hostname: stormtree
  ```

- **Verdict**: pass

### (Surface 2, Loop A) format_input_lines wire format

- **Surface**: Surface 2 (fzf picker)
- **Invocation**: `format_input_lines([row1, row2])`
- **Observed outcome**:

  ```
  'abc12345-aaaa-bbbb-cccc-111111111111\to\trunning-idle\treachable\tpresent\tstormtree\t2m\t~/Programs/onlayer-x\tiso27001 controls draft\ndef45678-2222-3333-4444-555555555555\tO\tunreachable\tunreachable\tmissing-cwd\tvicar\t1d\t/home/work/onlayer-eu\trefactor mart_*\n'
  ```

- **Verdict**: pass (real \t and \n, no spaces between columns)

### (Surface 2, Loop A) build_fzf_argv contains load-bearing flags

- **Surface**: Surface 2 (fzf picker)
- **Invocation**: `build_fzf_argv(filter_pwd=Path('/home/tunc/Programs/croam'))`
- **Observed outcome**:

  ```
  ['fzf', '--multi', '--ansi', '--delimiter=\t', '--with-nth=2,6,7,8,9', '--expect=p,c,f,C,F,ctrl-r', '--bind=tab:toggle+down', '--bind=shift-tab:toggle+up', '--bind=select,deselect:transform-header:echo "$FZF_SELECT_COUNT/$FZF_MATCH_COUNT selected"', '--header=enter:attach  p:peek  c:claim  f:fork  C:claim --here  F:fork --here  ctrl-r:reload', '--height=80%', '--layout=reverse', "--preview=printf 'sid: {1}\\n(preview pane to be filled in v2)\\n'", '--preview-window=right:50%:wrap', '--query=/home/tunc/Programs/croam']
  ```

- **Verdict**: pass (--with-nth=2,6,7,8,9, --expect=p,c,f,C,F,ctrl-r, $FZF_SELECT_COUNT, --query present)

### (Surface 2, Loop A) launch_picker happy path

- **Surface**: Surface 2 (fzf picker)
- **Invocation**: `launch_picker([row1], filter_pwd=None, fzf_binary=<fake-fzf>)` (fake emits "p\nrow1-line\n")
- **Observed outcome**:

  ```
  ('p', [PickerRow(sid='row1-sid', glyph='o', status_word='running-idle', reach_word='reachable', cwd_word='present', host='h', last='-', cwd_display='~', name='r1')])
  ```

- **Verdict**: pass

### (Surface 2) compute_action_intersection mixed selection

- **Surface**: Surface 2 (fzf picker)
- **Invocation**: `compute_action_intersection([row_local_present, row_remote_unreachable_missing_cwd], self_hostname="self")`
- **Observed outcome**:

  ```
  ['claim-here', 'fork-here', 'peek']
  ```

- **Verdict**: pass ("claim" and "fork" not in result, "peek" and "fork-here" present)

### (Surface 1) --debug ls reaches global callback

- **Surface**: Surface 1 (CLI verbs)
- **Invocation**: `CliRunner().invoke(app, ["--debug", "ls"])`
- **Observed outcome**:

  ```
  exception type: NotImplementedError
  exception args: ('Phase 7',)
  ```

- **Verdict**: pass (NotImplementedError from cmd_ls, not ConfigError or ImportError)

### Anti-Patterns Watched For

- **A. HOME redirect**: Every test uses the `home` fixture; no test calls `Path.home()` directly.
- **F. Picker tests exercise fzf flag construction**: `test_build_fzf_argv_includes_required_flags` asserts exact flag strings. `test_launch_picker_happy_path` drives a real subprocess via the fake-fzf script.
- **C. Subprocess invariants**: `launch_picker` uses `stderr=None` (never `subprocess.PIPE`); tests don't stub this.

### Strategy Updates

No strategy updates.

---

## Codebase Context Updates

- Update `src/croam/cli.py` entry in Key Files: "Phase 6 rewrite: full typer app with all verbs, global callback, CroamError handler via main()"
- Add `src/croam/picker.py` to Key Files: "PickerRow dataclass, format_last_column, compute_glyph, compute_status_word, render_rows, format_input_lines, build_fzf_argv, launch_picker, compute_action_intersection"
- Add `src/croam/commands/default.py` to Key Files: "run_picker orchestrator: discover -> filter -> render -> launch -> stub dispatch"
- Add `tests/_helpers/fake_fzf.py` to Key Files: "make_fake_fzf(tmp_path, output, exit_code) generates executable shell scripts"
- Add `tests/test_cli.py` to Key Files: "5 tests for CLI surface"
- Add `tests/test_picker.py` to Key Files: "24 tests for picker (10 parametrized + 14 others)"
- Update `pyproject.toml` entry: "Entry point changed to croam.cli:main"
- Update Phase 6 section in Important APIs: finalize signatures for picker.py and commands/default.py
- Note: `main()` uses `SystemExit(2)` not `typer.Exit(2)` for CroamError translation (typer.Exit outside click context yields exit code 1)
- Note: `CliRunner()` in typer does not support `mix_stderr=False` (that's click-only)

## Notes for Future Phases

- Phase 7 fills in `_dispatch` in `commands/default.py` with the expect_key -> verb mapping.
- Phase 7 replaces `cmd_ls` and `cmd_attach` stubs in cli.py.
- Phase 8 replaces `cmd_claim` and `cmd_fork` stubs.
- Phase 9 replaces `cmd_doctor` stub and wires real lineage reads into default.py.
- The `--here-on-owner` hidden flag on `cmd_attach` is parsed by typer but the recursion guard logic is Phase 7's responsibility.
- `cmd_launch` in cli.py calls `launch_cmd` from Phase 5 but passes a hardcoded `argv=["claude"]` and `config` from `ctx.obj.get("_config")` which is not populated yet. Phase 7 or a future phase should wire the real argv and config through ctx.obj.
- Coverage on cli.py is 64% due to stub verb handlers. This will naturally increase as future phases implement the verbs.

---

## Known Issues / Technical Debt

- TODO(phase-11): Fish-style cwd truncation noted in PickerRow.cwd_display comment.
- The `cmd_launch` path in cli.py uses a placeholder `ctx.obj.get("_config")` for config. Phase 7 should wire proper config loading into the ctx.obj dict or restructure the launch verb.
- `commands/__init__.py` was not modified (Phase 3 ownership). The phase plan's note about adding `from __future__ import annotations` was intentionally skipped to avoid cross-phase file conflicts.

---

## Next Steps

**Next Phase:** 7 (ls, attach, peek verbs + dispatch table)

**Recommended Actions:**
1. Phase 7 fills in `commands/default.py:_dispatch` with the expect_key -> verb mapping
2. Phase 7 implements `commands/ls.py`, `commands/attach.py`, `commands/peek.py`
3. Phase 7 replaces the `cmd_ls`, `cmd_attach`, `cmd_peek` stubs in cli.py
