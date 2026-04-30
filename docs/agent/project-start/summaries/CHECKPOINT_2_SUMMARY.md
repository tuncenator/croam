# Checkpoint 2: Post-Batch 2 Summary

**Date**: 2026-04-30
**Batch**: 2 (Config & paths)
**Phases Merged**: Phase 2 - Config & paths: TOML config loader, frozen dataclass tree, encode/decode/normalize cwd
**Result**: PASSED WITH FIXES

---

## Merge Results

| Phase | Branch | Merge Status | Conflicts |
|-------|--------|-------------|-----------|
| 2 | worktree-agent-a2f8f0e4deb88da4f | Clean | None |

---

## Test Results

```
57 passed, 1 skipped in 0.25s
```

- **Total tests**: 58
- **Passed**: 57
- **Failed**: 0
- **Skipped**: 1 (test_e2e_dummy_encoding, needs CROAM_E2E=1)

---

## Deployment Results

pending deploy-verify (deploy disabled for this feature)

---

## Verification Results

| # | Criterion | Command | Status | Key Output |
|---|----------|---------|--------|------------|
| 1 | `uv sync` exits 0 | `uv sync` | Pass | `Resolved 23 packages in 0.57ms` |
| 2 | `uv run pytest` full suite exits 0, no regressions | `uv run pytest` | Pass | `57 passed, 1 skipped in 0.25s` |
| 3 | `uv run pytest tests/test_paths.py tests/test_config.py -v` exits 0 | `uv run pytest tests/test_paths.py tests/test_config.py -v` | Pass | `43 passed, 1 skipped in 0.05s` |
| 4 | 100% coverage on paths.py and config.py | `uv run pytest --cov=croam.paths --cov=croam.config --cov-report=term-missing tests/test_paths.py tests/test_config.py` | Pass | `config.py 112 0 100%`, `paths.py 109 0 100%`, `TOTAL 221 0 100%` |
| 5 | `uv run pyright src` exits 0 | `uv run pyright src` | Pass | `0 errors, 0 warnings, 0 informations` |
| 6 | `uv run pyright src tests` exits 0 | `uv run pyright src tests` | Pass | `0 errors, 0 warnings, 0 informations` |
| 7 | `uv run ruff check src tests` exits 0 | `uv run ruff check src tests` | Pass | `All checks passed!` |
| 8 | `uv run ruff format --check src tests` exits 0 | `uv run ruff format --check src tests` | Pass (after fix) | `16 files already formatted` (initially 2 files needed reformatting; fixed inline) |
| 9 | `uv run croam --help` exits 0 | `uv run croam --help` | Pass | Usage text displayed with `croam [OPTIONS] COMMAND [ARGS]...` |
| 10 | Tier 2: `CROAM_E2E=1 uv run pytest tests/test_paths.py::test_e2e_dummy_encoding -v` | `CROAM_E2E=1 uv run pytest tests/test_paths.py::test_e2e_dummy_encoding -v` | Pass | `1 passed in 0.01s` (`~/.claude/projects/-tmp-croam-e2e` exists on this host) |
| 11 | `synth_jsonl._encode_cwd` cross-verification | `uv run pytest tests/test_paths.py::test_encode_matches_synth_jsonl -v` | Pass | `3 passed in 0.01s` (parametrized over `/tmp/croam-e2e`, `/home/tunc/Programs/croam`, `/home/tunc/.claude`) |

---

## Smoke Probe

pending deploy-verify (smoke disabled for this feature)

---

## Functional QA Evidence Check

Phase 2 plan specifies `Functional: yes` with 5 checks. All 5 present in the phase summary with:
- Surface exercised (Surface 4, Loop A for all)
- Actual invocation command (pasted, not paraphrased)
- Actual observed output (pasted byte-for-byte)
- Pass/fail verdict

No missing entries, no vague entries, no paraphrased outputs. **Functional QA evidence check: PASS.**

Phase 2 plan specifies `Visual: no`. No visual QA required.

---

## Helper Repairs

No helpers were listed for Phase 2. No phase summary reported helper issues.

---

## Fix Cycle History

| Attempt | Type | Target | Description | Result |
|---------|------|--------|-------------|--------|
| 1 | inline | `src/croam/paths.py`, `tests/test_paths.py` | `ruff format --check` failed on 2 files; ran `ruff format` to fix | Success |

### Fix Details

`ruff format --check src tests` reported `Would reformat: src/croam/paths.py` and `Would reformat: tests/test_paths.py`. The coder likely ran `ruff format` on specific files during development but the final state diverged slightly (possibly from a post-commit edit or ruff version difference). Applied `ruff format` to the two files, re-ran the full test suite (57 passed), and re-verified all lint/format/pyright checks pass.

---

## Codebase Context Updates

### Added

- `tests/test_paths.py`: 29 tests (28 Tier 1 + 1 Tier 2 e2e), includes cross-verification of `synth_jsonl._encode_cwd` against `croam.paths.encode_cwd`
- `tests/test_config.py`: 14 tests covering all config validation paths and bootstrap skeleton
- `src/croam/paths.py`: `encode_cwd`, `decode_cwd` (lossy, fs-probe with known-prefix optimization), `normalize_cwd`, `denormalize_cwd`
- `src/croam/config.py`: 7 frozen dataclasses (`HostEntry`, `StorageConfig`, `DiscoveryConfig`, `OwnershipConfig`, `PickerConfig`, `ShimConfig`, `Config`), `load_config`, `bootstrap_config`

### Modified

- CODEBASE_CONTEXT.md Phase 2 API section: replaced placeholder signatures with finalized ones (nested Config, `fs_probe` param on `decode_cwd`, new `denormalize_cwd` function, `load_config(path: Path | None = None)` signature, new `bootstrap_config`)
- CODEBASE_CONTEXT.md Key Files table: updated `config.py` and `paths.py` entries with accurate descriptions; added `test_paths.py` and `test_config.py` entries

### Removed

None.

---

## Notes for Next Batch

- **Config is nested, not flat**: access pattern is `config.storage.state_root`, `config.discovery.mode`, `config.ownership.claim_verify`, `config.picker.last_window_days`, `config.shim.enabled`, `config.shim.opt_out_env`. The original placeholder in the plan suggested flat access (`config.state_root`), which is wrong.
- **`decode_cwd` with many dashes**: for remote-host paths, always provide `host_home` so the known-prefix shortcut fires. Without it, paths containing many literal dashes (like pytest tmp paths) can exceed the 64-candidate cap.
- **`HostEntry.home = None`** means "autodetect at use time". For the local host, resolve to `Path(os.path.expanduser("~"))`. For remote hosts with `home=None`, fail loudly with a ConfigError. Phase 3 must handle this.
- **`bootstrap_config` overwrites atomically**: calling it when a config already exists will overwrite. Callers (Phase 9 doctor) should check file existence first.
- **`load_config(path=None)`** defaults to `~/.config/croam/config.toml` via `os.path.expanduser`, which honors `$HOME`. Tests redirect HOME via the `home` fixture, so the default path resolves to the test fixture directory.

---

## Status After Checkpoint

- **All phases in batch**: PASSED WITH FIXES
- **Cumulative project progress**: 18% (2/11 phases complete)
- **Ready for next batch**: Yes
