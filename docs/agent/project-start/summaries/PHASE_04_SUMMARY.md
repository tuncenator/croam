# Phase 4: Ownership state - Summary

**Date Completed:** 2026-04-30
**Completed By:** claude-sonnet-4-6 (agent-a32696885c62110f9)
**Actual Token Usage:** ~50k tokens

---

## Objective

Ship `src/croam/ownership.py`: per-host `ownership.json` read/write/merge/flatten with most-recent-`asserted_at`-wins semantics, plus `lineage.json` tracking. All writes use `os.replace` atomic rename with fsync. All datetimes are UTC-aware. The on-disk format is the inter-host wire contract; schema is frozen.

---

## Work Completed

### What Was Built

- `src/croam/ownership.py`: full implementation of all 11 public symbols plus 3 private helpers (`_parse_iso_utc`, `_atomic_write_json`, `_dict_to_assertions`). Wire format frozen. Singular `write_local_assertion` wrapper added for Phase 5 compatibility.
- `tests/_helpers/synth_assertions.py`: `build_assertion` and `write_assertions_file` test helpers for Phase 7, 8, 9, 10 consumption.
- `tests/test_ownership.py`: 43 tests covering all 22 spec cases plus additional validation-branch coverage. Final: 100% line coverage.

### Files Created

- `/home/tunc/Sync/Programs/croam/.claude/worktrees/agent-a32696885c62110f9/src/croam/ownership.py` -- full ownership module
- `/home/tunc/Sync/Programs/croam/.claude/worktrees/agent-a32696885c62110f9/tests/_helpers/synth_assertions.py` -- test helper
- `/home/tunc/Sync/Programs/croam/.claude/worktrees/agent-a32696885c62110f9/tests/test_ownership.py` -- 43 tests

### Files Modified

None. All files are new.

### Key Design Decisions

- `write_local_assertion` (singular) thin wrapper added on top of `write_local_assertions` (plural) so Phase 5's expected call site works without requiring Phase 5 to adapt. Documented in phase plan notes.
- `_dict_to_assertions` extracted as shared validation between `read_local_assertions` and `read_all_assertions` peer_states path, per spec.
- Loguru does not integrate with pytest's `caplog`. Test 18 (corrupt peer warning) captures loguru output by adding a temporary sink instead of using `caplog.at_level`. This is the correct pattern for loguru; noted so other phases using loguru-based warning checks can follow the same approach.
- Tests 7 and 8 (pure dataclass invariant tests) take the `home` fixture to satisfy the conftest safety guard, even though they don't use state_root. The guard fires on every test without regard for whether `home` is actually needed.
- `sort_keys=True` + `sorted(assertions.items())` in `write_local_assertions` produce byte-identical output for identical input, preventing syncthing from replicating spurious permutations.

---

## Completion Criteria Status

- [x] `src/croam/ownership.py` exists with all 11 public functions/classes. Verified: `uv run pyright src/croam/ownership.py` -- 0 errors.
- [x] `tests/_helpers/synth_assertions.py` exists with `build_assertion` and `write_assertions_file`. Verified: importable in all tests.
- [x] `tests/test_ownership.py` covers all 22 spec cases (43 total including coverage gap tests). Verified: `uv run pytest tests/test_ownership.py -v` -- 43 passed.
- [x] `uv run pytest tests/test_ownership.py -v` -- all green. 43 passed.
- [x] `uv run pyright src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py` -- 0 errors, 0 warnings.
- [x] `uv run ruff check ...` -- all checks passed.
- [x] `uv run ruff format --check ...` -- 3 files already formatted.
- [x] Coverage >= 95% on `src/croam/ownership.py`. Final: 100%.
- [x] Atomic write fault injection test present and passes. `test_write_atomic_crash_preserves_original` -- PASSED.
- [x] No new dependency added to `pyproject.toml`. All stdlib + loguru (already present).
- [x] `Assertion.__post_init__` validates tz-aware, claim requires previous_owner, non-claim forbids previous_owner.

### Deviations / Incomplete Items

None.

---

## Testing

### Tests Written

`tests/test_ownership.py` -- 43 tests:
- test_read_empty, test_read_one, test_read_z_suffix_accepted, test_read_naive_datetime_rejected
- test_read_malformed (parametrize x4), test_read_previous_owner_missing_or_null
- test_claim_without_previous_owner_rejected, test_create_with_previous_owner_rejected
- test_merge_two_hosts_no_overlap, test_merge_overlap_a_wins, test_merge_timezone_aware, test_merge_tiebreaker_alphabetical
- test_write_atomic_crash_preserves_original, test_write_stable_bytes
- test_flatten_drops_outclaimed, test_detect_outclaim
- test_read_all_skips_dirs_without_ownership, test_read_all_continues_past_corrupt_peer
- test_read_all_peer_states_override
- test_lineage_increments, test_lineage_independent_parents
- test_e2e_outclaim_recovery
- Coverage gap tests: test_parse_iso_utc_bad_format, test_dict_to_assertions_non_dict_entry, test_dict_to_assertions_missing_required_field, test_dict_to_assertions_non_str_owner, test_dict_to_assertions_non_str_cwd_normalized, test_dict_to_assertions_invalid_action, test_read_all_peer_states_invalid_skipped, test_merge_tiebreaker_loser_not_selected, test_write_local_assertion_singular, test_flatten_no_drops_debug_branch, test_read_lineage_malformed_json, test_read_lineage_non_object, test_read_lineage_entry_not_dict, test_read_lineage_missing_field, test_read_lineage_fork_n_not_int, test_assertion_naive_asserted_at_rejected, test_read_all_skips_non_dir_children, test_merge_later_assertion_displaces_earlier

### Test Results

```
$ uv run pytest tests/test_ownership.py --cov=croam.ownership --cov-report=term-missing -q
...........................................
================================ tests coverage ================================
Name                     Stmts   Miss  Cover   Missing
------------------------------------------------------
src/croam/ownership.py     179      0   100%
------------------------------------------------------
TOTAL                      179      0   100%
43 passed in 0.18s
```

Full suite (no regressions):

```
$ uv run pytest -q
........................................................................ [ 71%]
..............s..............                                            [100%]
=========================== short test summary info ===========================
SKIPPED [1] tests/test_paths.py:298: needs real claude
100 passed, 1 skipped in 0.32s
```

---

## Evidence Captured

### ownership.json wire format

- **How captured**: REPL via `uv run python -c "..."` writing a single Assertion and reading back the file.
- **Captured on**: 2026-04-30 against local worktree at commit 73bd275.
- **Consumed by**: `src/croam/ownership.py:_dict_to_assertions` (read path), `write_local_assertions` (write path).
- **Sample**:

  ```json
  {
    "ff7afd8a-ea17-4183-a131-566e7bcb0758": {
      "action": "create",
      "asserted_at": "2026-04-30T10:00:00+00:00",
      "cwd_normalized": "~/Programs/croam",
      "owner": "stormtree",
      "previous_owner": null
    }
  }
  ```

- **Notes**: `sort_keys=True` produces alphabetical key ordering (action before asserted_at before cwd_normalized before owner before previous_owner). `previous_owner` is always present in written output (null for non-claim). `asserted_at` uses `+00:00` suffix (Python `datetime.isoformat()` output), not `Z`. Reader accepts both.

### ISO8601 datetime string forms

- **How captured**: `uv run python -c "import datetime; ..."` stdlib output.
- **Captured on**: 2026-04-30.
- **Consumed by**: `src/croam/ownership.py:_parse_iso_utc`.
- **Sample**:

  ```
  aware UTC:     2026-04-30T19:31:01.980537+00:00
  aware -05:00:  2026-04-30T14:31:01.980551-05:00
  naive:         2026-04-30T22:31:01.980553
  Z form:        2026-04-30T19:31:01Z
  ```

- **Notes**: `_parse_iso_utc` accepts forms 1, 2, 4; rejects form 3 (naive). Z is normalized to `+00:00` before `fromisoformat`. Microseconds in forms 1/2 are retained but all datetimes normalized to UTC via `astimezone(UTC)` before storage.

---

## Helper Issues

No helpers were listed for this phase. None were needed.

---

## Functional QA Results

### (state-file surface, Loop C: Claim ownership) merge_assertions with vicar claiming from stormtree

- **Surface**: Surface 4 -- per-host state files (inter-host wire format)
- **Invocation**: Python REPL against synthetic `/tmp/croam-fqa/state/` with stormtree owning S1 at 10:00 and vicar claiming S1 at 11:00

  ```python
  from croam.ownership import read_all_assertions, merge_assertions
  from pathlib import Path
  m = merge_assertions(read_all_assertions(Path('/tmp/croam-fqa/state')))
  print(m['S1'])
  ```

- **Observed outcome**:

  ```
  merged[S1].owner: vicar
  merged[S1].action: claim
  Full assertion: Assertion(sid='S1', owner='vicar', asserted_at=datetime.datetime(2026, 4, 30, 11, 0, tzinfo=datetime.timezone.utc), action='claim', cwd_normalized='~/Programs/foo', previous_owner='stormtree')
  ```

- **Verdict**: pass

### (state-file surface, Loop C) flatten_local removes S1 from stormtree; vicar retains S1

- **Surface**: Surface 4
- **Invocation**: Continued from above, calling `flatten_local(state, 'stormtree', m)` then `flatten_local(state, 'vicar', m)`
- **Observed outcome**:

  ```
  stormtree after flatten:
  {}
  vicar after flatten:
  {
    "S1": {
      "action": "claim",
      "asserted_at": "2026-04-30T11:00:00+00:00",
      "cwd_normalized": "~/Programs/foo",
      "owner": "vicar",
      "previous_owner": "stormtree"
    }
  }
  ```

- **Verdict**: pass

### (state-file surface, anti-pattern E) Mixed-timezone test: A 10:00 UTC beats B 04:00-05:00 (09:00 UTC)

- **Surface**: Surface 4
- **Invocation**: Python REPL with A at `datetime(2026,4,30,10,0,utc)` and B at `datetime(2026,4,30,4,0,tz_minus5)`

- **Observed outcome**:

  ```
  winner owner: A
  A UTC instant: 2026-04-30 10:00:00+00:00
  B UTC instant: 2026-04-30 09:00:00+00:00
  A wins (later UTC): True
  ```

- **Verdict**: pass

### (state-file surface, atomicity) Atomic write fault injection

- **Surface**: Surface 4
- **Invocation**: monkeypatched `os.replace` to raise `OSError('disk full')`; attempted `write_local_assertions` with new content after pre-writing known-good file

- **Observed outcome**:

  ```
  === Before ===
  {
    "S1": {
      "action": "create",
      "asserted_at": "2026-04-30T10:00:00+00:00",
      "cwd_normalized": "~/x",
      "owner": "A",
      "previous_owner": null
    }
  }
  === Exception ===
  OSError('disk full')
  === After (should match Before) ===
  {
    "S1": {
      "action": "create",
      "asserted_at": "2026-04-30T10:00:00+00:00",
      "cwd_normalized": "~/x",
      "owner": "A",
      "previous_owner": null
    }
  }
  === ls -la state/A/ ===
  total 4
  drwxr-xr-x 2 tunc tunc  60 Apr 30 22:30 .
  drwxr-xr-x 3 tunc tunc  60 Apr 30 22:30 ..
  -rw-r--r-- 1 tunc tunc 163 Apr 30 22:30 ownership.json
  ```

- **Verdict**: pass -- original intact, no .tmp. files remain

### (state-file surface, fresh state) Empty directory returns {}

- **Surface**: Surface 4
- **Invocation**: `read_local_assertions(state, 'A')` with `A/` dir present but no ownership.json

- **Observed outcome**:

  ```
  result: {}
  type: <class 'dict'>
  is empty dict: True
  ```

- **Verdict**: pass

### (state-file surface, schema validation) Malformed JSON raises OwnershipConflict naming the file

- **Surface**: Surface 4
- **Invocation**: wrote `{not json` to `A/ownership.json`, called `read_local_assertions`

- **Observed outcome**:

  ```
  OwnershipConflict raised: Malformed JSON in /tmp/croam-fqa4/state/A/ownership.json: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
  File path in message: True
  ```

- **Verdict**: pass

### (state-file surface, lineage) Three-fork lineage returns 1, 2, 3

- **Surface**: Surface 4
- **Invocation**: three `add_lineage(state, 'stormtree', 'fN', 'parent')` calls

- **Observed outcome**:

  ```
  fork_n sequence: 1 2 3
  lineage.json:
  {
    "f1": {
      "fork_n": 1,
      "parent_sid": "parent"
    },
    "f2": {
      "fork_n": 2,
      "parent_sid": "parent"
    },
    "f3": {
      "fork_n": 3,
      "parent_sid": "parent"
    }
  }
  ```

- **Verdict**: pass

### Anti-Patterns Watched For

- **Anti-pattern E (timezone-unaware datetimes)**: every comparison goes through tz-aware datetimes. `Assertion.__post_init__` enforces this at construction. `_parse_iso_utc` normalizes all inputs to UTC via `astimezone(UTC)`. Test 11 specifically exercises mixed-offset comparison. Never used naive `datetime.now()` anywhere.
- **Anti-pattern A (HOME redirect)**: never called `Path.home()` or `os.path.expanduser("~")` in ownership.py or test code. All state paths are `state_root: Path` parameters. Tests 7 and 8 (no state_root) take `home` fixture to satisfy the guard.

### Strategy Updates

No strategy updates. The loguru/caplog incompatibility (anti-pattern: using `caplog.at_level` with loguru) is a new testing pattern worth documenting: add a temporary loguru sink instead. This is already implicit in the strategy's "use the real surface" guidance -- pytest caplog only captures Python stdlib logging, not loguru.

---

## Challenges & Solutions

### Challenge 1: Ruff import ordering (I001) on repeated edits
The lint-on-write hook triggered I001 repeatedly. Running `uv run ruff check --fix` auto-fixes the import block; the `SIM102` nested-if and `SIM105` suppress-pattern fixes required manual edits.

**Solution:** Let ruff --fix handle I001 on each save; fix SIM rules manually.

### Challenge 2: Tests 7/8 failing conftest safety guard
Pure dataclass tests with no state_root fixture still trigger the HOME redirect guard.

**Solution:** Added `home: Path` as a parameter to both tests. The fixture redirects HOME and the guard passes.

### Challenge 3: loguru warning not captured by pytest caplog
Test 18 used `caplog.at_level(logging.WARNING)` which only captures Python stdlib logging. Loguru bypasses this.

**Solution:** Added a temporary loguru sink (`logger.add(lambda msg: captured.append(msg), level='WARNING')`) in the test body, removed with `logger.remove(sink_id)` in a finally block.

---

## Code Quality

### Formatting
- [x] Code formatted per project conventions (ruff format)
- [x] Imports organized (ruff check --fix)
- [x] No unused imports

### Documentation
- [x] All public functions have one-line docstrings
- [x] Type annotations on all functions
- [x] Module-level docstring present

### Linting

```
$ uv run ruff check src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py
All checks passed!

$ uv run ruff format --check src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py
3 files already formatted

$ uv run pyright src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py
0 errors, 0 warnings, 0 informations
```

---

## Dependencies

### Required by This Phase
- Phase 1: `src/croam/errors.py` provides `OwnershipConflict`. `tests/conftest.py` provides `state_root` fixture and HOME guard.
- Phase 2: not required for compilation. `cwd_normalized` treated as opaque string.

### Unblocked Phases
- Phase 5: can now call `write_local_assertion` (singular wrapper) and `write_local_assertions` from `commands/launch.py`.
- Phase 7: can now call `read_all_assertions` + `merge_assertions` for picker view.
- Phase 8: can now use `Assertion`, `write_local_assertions`, `add_lineage` for claim/fork.
- Phase 9: can now call `read_all_assertions` for doctor diagnostics.
- Phase 10: can now write integration tests using `synth_assertions` helper.

---

## Codebase Context Updates

- Add `src/croam/ownership.py` to Key Files table: "per-host assertion read/write/merge/flatten + lineage -- Phase 4".
- Add `tests/_helpers/synth_assertions.py` to Key Files table: "`build_assertion` and `write_assertions_file` for tests -- Phase 4".
- Add `tests/test_ownership.py` to Key Files table.
- Populate Phase 4 section of Important APIs: all 11 public symbols with signatures as implemented (including `write_local_assertion` singular wrapper not in the original placeholder).
- Note in Phase 5 section: `commands/launch.py` can use `write_local_assertion(state_root, hostname, assertion)` -- the singular wrapper is present in ownership.py.

---

## Notes for Future Phases

- `write_local_assertion` (singular) is a thin wrapper around `write_local_assertions` (plural). Phase 5 should use it for single-assertion inserts. It reads the existing file, updates the single key, and rewrites atomically.
- `synth_assertions.write_assertions_file` bypasses atomic semantics deliberately -- it is for test seeding only. Do NOT use it in production code paths.
- The loguru sink pattern for testing warnings: `sink_id = logger.add(lambda msg: captured.append(msg), level="WARNING")` with `logger.remove(sink_id)` in a finally block. Phases 7, 8, 9 should follow this pattern for any loguru warning assertion.
- `read_all_assertions` iterates `state_root.iterdir()` -- it picks up ALL subdirectories that have an `ownership.json`, including any new hostname that gets a state directory. No configuration change needed when adding hosts.
- Wire format is frozen. Do not add fields to `Assertion`. Phase 8's snapshot need (JSONL line count at assertion time) goes in a separate `snapshots.json` file. See phase plan's snapshot decision section for the rationale and suggested shape.

---

## Integration Points

- `ownership.read_all_assertions` + `merge_assertions` consumed by Phase 7 picker and Phase 9 doctor.
- `ownership.write_local_assertion` consumed by Phase 5 launch command.
- `ownership.Assertion` + `write_local_assertions` + `add_lineage` consumed by Phase 8 claim/fork commands.
- `tests/_helpers/synth_assertions` consumed by Phase 7, 8, 9, 10 tests.

---

## Known Issues / Technical Debt

None. All spec requirements met. Wire format frozen.

---

## Next Steps

**Next Phase:** Phase 5 (tmux and shim) and Phase 3 (sessions and host probes) -- both run in parallel batch 3.

**Recommended Actions:**
1. Phase 5: import `write_local_assertion` from `croam.ownership` for launch command.
2. Phase 8: import `Assertion`, `write_local_assertions`, `add_lineage` for claim/fork. Do NOT add `transcript_lines_at_assertion` to `Assertion` -- use separate `snapshots.json`.

---

## Approval

**Phase Status:** COMPLETE
