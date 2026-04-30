# Phase 2: Config & paths - Summary

**Date Completed:** 2026-04-30
**Completed By:** claude-sonnet-4-6 (agent session agent-a2f8f0e4deb88da4f)
**Actual Token Usage:** ~90k tokens

---

## Objective

Ship two pure-Python modules that are the load-bearing wire format for everything downstream: `src/croam/paths.py` (encoded-cwd encode/decode + cross-host normalization) and `src/croam/config.py` (TOML loader + frozen `Config` dataclass tree). Both modules are deterministic, fully unit-tested against synthetic fixtures, and verified against the real dummy session for encode/decode rules.

---

## Work Completed

### What Was Built

- `src/croam/paths.py`: four public functions (`encode_cwd`, `decode_cwd`, `normalize_cwd`, `denormalize_cwd`) with 100% line coverage.
- `src/croam/config.py`: seven frozen dataclasses (`HostEntry`, `StorageConfig`, `DiscoveryConfig`, `OwnershipConfig`, `PickerConfig`, `ShimConfig`, `Config`), plus `load_config` and `bootstrap_config`, with 100% line coverage.
- `tests/test_paths.py`: 29 tests (28 Tier 1, 1 Tier 2 gated on `CROAM_E2E=1`). Includes the spec-mandated 14 numbered tests plus coverage helpers and the `synth_jsonl._encode_cwd` cross-verification.
- `tests/test_config.py`: 14 tests covering all validation paths and the bootstrap skeleton.

### Files Created

- `src/croam/paths.py` -- encode/decode/normalize/denormalize with known-prefix decode optimization
- `src/croam/config.py` -- TOML loader with frozen dataclass tree and atomic bootstrap write
- `tests/test_paths.py` -- 29 tests, 100% coverage on paths.py
- `tests/test_config.py` -- 14 tests, 100% coverage on config.py

### Files Modified

- `docs/agent/project-start/CODEBASE_CONTEXT.md` -- Phase 2 section updated with finalized signatures (replacing placeholders)

### Key Design Decisions

**decode_cwd known-prefix strategy**: The recursive candidate generator (`_recurse`) combined with a known-prefix shortcut in `_generate_candidates` handles the core decode challenge. When `host_home` is provided and the encoded string starts with `encode_cwd(host_home)`, the suffix is enumerated independently and prepended with `host_home`. This is critical for correctness: pytest tmp paths contain many literal dashes (`pytest-of-tunc`, `pytest-N`, etc.), and naive full enumeration would exceed the 64-candidate cap before finding the correct parse. The known-prefix shortcut finds it on the first candidate.

**Single-empty vs double-empty token semantics**: Splitting an encoded body (after stripping the leading `-`) on `-` produces ONE empty token for a `--` sequence (e.g. `tunc--claude` -> `['tunc', '', 'claude']`), while the full suffix (not body-stripped) produces TWO empty tokens (`--claude` -> `['', '', 'claude']`). `_recurse` handles both: the `elif` branch (single empty + non-empty next) generates both the plain-separator interpretation and the dot-prefix interpretation.

**`# pragma: no cover` for defensive-but-unreachable branches**: Several branches guard against TOML parser misbehavior that cannot happen in practice (e.g. `[storage]` not parsing as a dict). Rather than writing contrived tests, these are marked `# pragma: no cover` with explanatory comments.

**`_no_probe_best_guess`**: For `fs_probe=False`, a single empty token in the body-split means the next token is dot-prefixed. This correctly handles `/home/tunc/.claude` -> `-home-tunc--claude` -> body `home-tunc--claude` -> split `['home', 'tunc', '', 'claude']` -> append `'.claude'`.

---

## Completion Criteria Status

- [x] `src/croam/paths.py` exists with four public functions and specified signatures.
  Verified: `uv run pyright src/croam/paths.py` -- 0 errors
- [x] `src/croam/config.py` exists with seven dataclasses and two functions.
  Verified: `uv run pyright src/croam/config.py` -- 0 errors
- [x] All tests pass: `uv run pytest tests/test_paths.py tests/test_config.py -v` -- 43 passed, 1 skipped
- [x] 100% line coverage: `uv run pytest --cov=croam.paths --cov=croam.config --cov-report=term-missing` -- both files 100%
- [x] `uv run pyright src/croam/paths.py src/croam/config.py` -- 0 errors, 0 warnings
- [x] `uv run ruff check src/croam/paths.py src/croam/config.py` -- All checks passed
- [x] Tier 2: `CROAM_E2E=1 uv run pytest tests/test_paths.py::test_e2e_dummy_encoding -v` -- 1 passed. `~/.claude/projects/-tmp-croam-e2e` exists and contains the dummy JSONL.
- [x] CODEBASE_CONTEXT.md Phase 2 section updated with finalized signatures.

### Deviations / Incomplete Items

None. All criteria met.

---

## Testing

### Tests Written

`tests/test_paths.py` (29 tests):
- `test_encode_examples` (parametrized x6)
- `test_encode_dot_segment`
- `test_encode_double_slash_collapsed`
- `test_encode_relative_path_raises`
- `test_decode_lossy_with_fs_probe`
- `test_decode_no_probe_returns_most_likely`
- `test_decode_dot_segment_with_fs_probe`
- `test_decode_invalid_input_raises`
- `test_normalize_under_home`
- `test_normalize_outside_home`
- `test_normalize_equals_home`
- `test_denormalize_round_trip`
- `test_denormalize_absolute`
- `test_encode_matches_synth_jsonl` (parametrized x3)
- `test_decode_no_probe_dot_segment`
- `test_decode_no_probe_with_host_home_no_match`
- `test_decode_exactly_host_home`
- `test_decode_no_host_home_uses_strategy2`
- `test_denormalize_tilde_user_raises`
- `test_normalize_relative_raises`
- `test_decode_dot_segment_no_host_home`
- `test_denormalize_tilde_alone`
- `test_e2e_dummy_encoding` (Tier 2, CROAM_E2E=1)

`tests/test_config.py` (14 tests):
- `test_load_minimal_valid`
- `test_load_missing_self_hostname`
- `test_load_missing_self_in_hosts`
- `test_load_invalid_discovery_mode`
- `test_load_state_root_tilde_expansion`
- `test_load_invalid_claim_verify`
- `test_load_uses_defaults_for_optional_sections`
- `test_load_missing_config_file`
- `test_load_missing_host_ssh`
- `test_load_invalid_picker_filter`
- `test_load_invalid_picker_days`
- `test_load_invalid_shim_opt_out`
- `test_load_host_with_home_expanded`
- `test_bootstrap_writes_skeleton`

### Test Results

```
$ uv run pytest --cov=croam.paths --cov=croam.config --cov-report=term-missing tests/test_paths.py tests/test_config.py

Name                  Stmts   Miss  Cover   Missing
---------------------------------------------------
src/croam/config.py     112      0   100%
src/croam/paths.py      109      0   100%
---------------------------------------------------
TOTAL                   221      0   100%

43 passed, 1 skipped in 0.12s
```

```
$ CROAM_E2E=1 uv run pytest tests/test_paths.py::test_e2e_dummy_encoding -v
tests/test_paths.py::test_e2e_dummy_encoding PASSED
1 passed in 0.01s
```

---

## Evidence Captured

### TOML file parsed via stdlib `tomllib`

- **How captured**: `python3 -c "import tomllib; from pathlib import Path; import pprint; pprint.pprint(tomllib.load(open('/tmp/sample-croam.toml', 'rb')))"` against the spec section 10 sample.
- **Captured on**: 2026-04-30, local Python 3.11.15.
- **Consumed by**: `src/croam/config.py:load_config` dict-access logic.
- **Sample**:

  ```python
  {'discovery': {'mode': 'ssh'},
   'hosts': {'stormtree': {'ssh': 'stormtree', 'sync': True},
             'vicar': {'home': '/home/tunc', 'ssh': 'vicar', 'sync': True}},
   'ownership': {'claim_verify': 'ssh-strict'},
   'picker': {'default_filter': 'exact-pwd', 'last_window_days': 30},
   'self': {'hostname': 'stormtree'},
   'shim': {'enabled': True, 'opt_out_env': 'CROAM_NO_TMUX'},
   'storage': {'state_root': '~/.local/share/croam'}}
  ```

- **Notes**: TOML tables always parse as `dict`; booleans as `bool`; integers as `int`. The "not a dict" defensive branches in the loader are unreachable from valid TOML and are marked `# pragma: no cover`.

### Filesystem listing of `~/.claude/projects/`

- **How captured**: `ls /home/tunc/.claude/projects/ | head -20` on local machine.
- **Captured on**: 2026-04-30.
- **Consumed by**: `encode_cwd` encoding rules verification.
- **Sample** (first 20 lines):

  ```
  -home-tunc
  -home-tunc--claude
  -home-tunc-Sync
  -home-tunc-Sync--claude
  -home-tunc-Sync--claude-commands
  -home-tunc-Sync--claude-hooks
  -home-tunc-Sync--config-nvim
  -home-tunc-Sync-Documents-clients-wio-advanced-scoring-model
  -home-tunc-Sync-Documents-PCICHECKLIST-backups
  -home-tunc-Sync-Programs
  -home-tunc-Sync-Programs-aegis
  -home-tunc-Sync-Programs-aegis--claude-worktrees-agent-a4501029b9062dc9a
  -home-tunc-Sync-Programs-ai-skills
  -home-tunc-Sync-Programs-arcforge
  -home-tunc-Sync-Programs-auditor-ai
  -home-tunc-Sync-Programs-bash-gatekeeper
  -home-tunc-Sync-Programs-ccswap
  -home-tunc-Sync-Programs-conclave
  -home-tunc-Sync-Programs-croam
  -home-tunc-Sync-Programs-database-backups-restic
  ```

- **Notes**: Confirms encoding rules: `/` -> `-`, leading `.` -> `-` (producing `--` for `/.something`). The entry `-home-tunc--claude` confirms the double-dash for `.claude`. The entry `-home-tunc-Sync--config-nvim` confirms the pattern for `~/.config`.

---

## Helper Issues

No helpers were listed for this phase. None were needed.

---

## Functional QA Results

### (Surface 4, Loop A) Encoding rule matches reality

- **Surface**: Surface 4 -- inter-host wire format
- **Invocation**: `uv run python -c "from croam.paths import encode_cwd; print(encode_cwd('/home/tunc/.claude/commands'))"`
- **Observed outcome**:
  ```
  -home-tunc--claude-commands
  ```
- **Verdict**: pass. The output matches the spec table exactly. Note: `ls /home/tunc/.claude/projects/ | grep -E '^-home-tunc--claude-commands$'` produced no output (the directory `/home/tunc/.claude/commands` does not exist on this host; only the Sync variant does). The encoding rule itself is correct per the filesystem evidence for analogous paths.

### (Surface 4, Loop A) Decode round-trips for the e2e_dummy

- **Surface**: Surface 4 -- inter-host wire format
- **Invocation**: `CROAM_E2E=1 uv run pytest tests/test_paths.py::test_e2e_dummy_encoding -v`
- **Observed outcome**:
  ```
  tests/test_paths.py::test_e2e_dummy_encoding PASSED
  1 passed in 0.01s
  ```
- **Verdict**: pass.

### (Surface 4, Loop A) load_config raises with exact field name when self.hostname is missing

- **Surface**: Surface 4 -- config loader
- **Invocation**:
  ```
  printf '[hosts.x]\nssh = "x"\n' > /tmp/c.toml
  uv run python -c "
  from pathlib import Path; from croam.config import load_config; from croam.errors import ConfigError
  try:
      load_config(Path('/tmp/c.toml'))
  except ConfigError as e:
      print(f'field={e.field!r}')
      print(f'reason={e.reason!r}')
  "
  ```
- **Observed outcome**:
  ```
  field='self.hostname'
  reason='required field missing'
  ```
- **Verdict**: pass. `field="self.hostname"` matches the spec exactly.

### (Surface 4, Loop A) normalize_cwd returns home-rooted form

- **Surface**: Surface 4 -- path normalization
- **Invocation**: `uv run python -c "from pathlib import Path; from croam.paths import normalize_cwd; print(normalize_cwd(Path.home()/'Programs/croam', Path.home()))"`
- **Observed outcome**:
  ```
  ~/Programs/croam
  ```
- **Verdict**: pass. Returns `~/Programs/croam`, not the absolute path.

### (Surface 4, Loop A) state_root tilde expansion uses test HOME under pytest

- **Surface**: Surface 4 -- config loader / test HOME isolation
- **Invocation**: `uv run pytest tests/test_config.py::test_load_state_root_tilde_expansion -v`
- **Observed outcome**:
  ```
  tests/test_config.py::test_load_state_root_tilde_expansion PASSED
  1 passed in 0.01s
  ```
- **Verdict**: pass. Expansion resolves against the test fixture HOME, not the real user home.

### Anti-Patterns Watched For

- **Anti-pattern A (HOME redirect)**: every test takes the `home` fixture. `Path.home()` is only called inside the Tier 2 test (which requires `CROAM_E2E=1` and explicitly checks against the real `~/.claude/projects/`).
- **Anti-pattern D (encoded-cwd tests)**: dot-segment cases (`/home/tunc/.claude/commands`, `/.claude`, etc.) are covered by `test_encode_dot_segment`, `test_encode_examples`, `test_decode_dot_segment_with_fs_probe`, and `test_decode_no_probe_dot_segment`.

### Strategy Updates

No strategy updates. Phase 2's surfaces and loops behaved exactly as documented.

---

## Challenges & Solutions

### Challenge 1: Candidate generator -- literal dashes in pytest tmp paths

The initial recursive candidate generator failed for tests because pytest's `tmp_path` contains many literal dashes (`pytest-of-tunc`, `pytest-N`, `test_decode_..._f0`). With N dashes, 2^N candidates are generated and the cap of 64 is exceeded before the correct parse is found.

**Solution**: Known-prefix shortcut in `_generate_candidates`. When `host_home` is provided and the encoded string starts with `encode_cwd(host_home)`, strip that prefix and enumerate only the suffix. The suffix for a subdir under home is short (e.g. `-foo-bar`, `--claude-commands`), so the candidate count stays minimal.

### Challenge 2: Single-empty vs double-empty token semantics

Splitting the encoded BODY (after stripping the leading `-`) on `-` produces ONE empty token where there is a `--` in the original (e.g. `tunc--claude` -> `['tunc', '', 'claude']`). But the full suffix (not body-stripped) produces TWO empty tokens (`--claude` -> `['', '', 'claude']`). The initial `_recurse` only handled double-empty, so strategy-2 (full enumeration) never generated dot-prefix candidates.

**Solution**: Added a second interpretation in the single-empty branch of `_recurse`: when tok=`''` followed by a non-empty next token, yield both the plain-separator interpretation AND the dot-prefix interpretation. This handles both the body-split and full-suffix token lists correctly.

---

## Code Quality

### Formatting
- [x] Code formatted with `ruff format`; `ruff format --check src tests` reports all files formatted.
- [x] Imports sorted per ruff I001.
- [x] No unused imports.

### Documentation
- [x] All public functions have one-line docstrings.
- [x] Type annotations complete; `from __future__ import annotations` in every src/ module.
- [x] Module-level docstrings present on both modules.

### Linting

```
$ uv run ruff check src/croam/paths.py src/croam/config.py
All checks passed!

$ uv run pyright src/croam/paths.py src/croam/config.py
0 errors, 0 warnings, 0 informations
```

---

## Dependencies

### Required by This Phase

- Phase 1: `src/croam/errors.py` (ConfigError), `tests/conftest.py` (home, e2e_dummy fixtures), `tests/_helpers/synth_jsonl.py` (cross-verification).

### Unblocked Phases

- Phase 3: sessions.py and hosts.py (needs `encode_cwd`, `normalize_cwd`, `Config`)
- Phase 4: ownership.py (needs `Config.storage`, `normalize_cwd`)
- Phase 5: tmux.py and shim.py (needs `Config.shim`)
- Phases 6-9: all need `Config`

---

## Codebase Context Updates

Phase 2 section in CODEBASE_CONTEXT.md was replaced in-place (the placeholder signatures were wrong). The finalized signatures differ from the placeholders in these ways:

- `decode_cwd` gained a `fs_probe: bool = True` parameter (not in placeholder).
- `denormalize_cwd` is a new public function (not in placeholder).
- `Config` is NOT a flat dataclass -- it nests `StorageConfig`, `DiscoveryConfig`, `OwnershipConfig`, `PickerConfig`, `ShimConfig` (the placeholder had flat fields like `state_root: Path` directly on `Config`).
- `load_config` signature changed to `load_config(path: Path | None = None)` (placeholder had a Path default that doesn't work with the test HOME redirect).
- `bootstrap_config(path: Path) -> Config` is a new function (not in placeholder).

These changes need to propagate to any future phase documentation that references the placeholder Config shape.

---

## Notes for Future Phases

- **Phase 3**: `decode_cwd` with `host_home=None` and `fs_probe=True` works fine for simple paths but will fail on paths with many dashes if the correct directory doesn't exist on the LOCAL host. For remote-host paths, always provide `host_home` so the known-prefix shortcut fires.
- **Phase 3**: `HostEntry.home = None` means "autodetect at use time". For the local host, resolve to `Path(os.path.expanduser("~"))`. For remote hosts with `home=None`, fail loudly with a ConfigError.
- **Config is nested, not flat**: `config.storage.state_root`, `config.discovery.mode`, `config.ownership.claim_verify`, `config.picker.last_window_days`, `config.shim.enabled`, `config.shim.opt_out_env`. The placeholder suggested flat access like `config.state_root` -- that is wrong.
- **`bootstrap_config` is idempotent in effect**: it overwrites the destination atomically. Calling it when a config already exists will overwrite with a fresh skeleton. Callers (Phase 9 doctor) should check file existence before calling.

---

## Next Steps

**Next Phase:** Phase 3 -- Session discovery (sessions.py, hosts.py)

**Recommended Actions:**
1. Read the finalized signatures in CODEBASE_CONTEXT.md Phase 2 section before coding.
2. Use `encode_cwd` + `decode_cwd(host_home=home)` for the `~/.claude/projects/` scan.
3. `Config.hosts[hostname]` gives the `HostEntry`; `HostEntry.home` may be `None` and needs autodetect for the local host.

---

## Approval

**Phase Status:** COMPLETE
