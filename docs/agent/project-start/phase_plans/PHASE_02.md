# Phase 2: Config & paths

**Feature**: project-start
**Estimated Context Budget**: ~60k tokens

**Difficulty**: medium
**Visual**: no
**Functional**: yes

**Execution Mode**: sequential
**Batch**: 2 (sole phase in this batch; blocks parallel batch 3)

---

## Objective

Ship two pure-Python modules that are the load-bearing wire format for everything downstream: `src/croam/paths.py` (encoded-cwd encode/decode + cross-host normalization) and `src/croam/config.py` (TOML loader + frozen `Config` dataclass tree). Every later phase consumes these. Both modules must be deterministic, fully unit-tested against synthetic fixtures, and verified against the real dummy session for the encode/decode rules.

This phase ships nothing user-facing on its own; it ships Surface 4 contracts (`cwd_normalized` in `ownership.json` is the field that has to round-trip across hosts) and the loader that every command will call at startup.

---

## Deliverables

1. `src/croam/paths.py` with public functions:
   - `encode_cwd(cwd: Path | str) -> str`
   - `decode_cwd(encoded: str, host_home: Path | None = None, fs_probe: bool = True) -> Path`
   - `normalize_cwd(cwd: Path, host_home: Path) -> str`
   - `denormalize_cwd(normalized: str, host_home: Path) -> Path`
2. `src/croam/config.py` with:
   - Frozen dataclasses: `HostEntry`, `StorageConfig`, `DiscoveryConfig`, `OwnershipConfig`, `PickerConfig`, `ShimConfig`, `Config`
   - `load_config(path: Path | None = None) -> Config`
   - `bootstrap_config(path: Path) -> Config`
3. `tests/test_paths.py` with the seven tests listed in "Testing Requirements".
4. `tests/test_config.py` with the six tests listed in "Testing Requirements".
5. Updates to `docs/agent/project-start/CODEBASE_CONTEXT.md` "Phase 2" section reflecting any signature changes from the placeholders. Use append-only updates; do not rewrite earlier sections.

---

## Detailed Requirements

### Step-by-step implementation order

1. **`src/croam/paths.py` first** (config.py imports nothing from paths but the test ordering is easier if paths is solid).
2. **`tests/test_paths.py`** -- full coverage including the e2e_dummy Tier 2 case.
3. **`src/croam/config.py`**.
4. **`tests/test_config.py`**.
5. **`CODEBASE_CONTEXT.md` Phase 2 update** -- one paragraph noting the actual signatures shipped.

### File: `src/croam/paths.py`

Header (mandatory):

```python
"""Path normalization and claude's encoded-cwd convention.

Linux-only. Windows paths are out of scope.
"""
from __future__ import annotations

from pathlib import Path

from croam.errors import ConfigError
```

#### `encode_cwd(cwd: Path | str) -> str`

Rules (verified against `~/.claude/projects/` real listings on 2026-04-30):

- Each `/` in the absolute path becomes `-`.
- Each path component starting with `.` has its leading `.` become `-`.
- Existing `-` characters in segments are preserved verbatim. Encoding is therefore lossy on decode.

Implementation sketch:

```python
def encode_cwd(cwd: Path | str) -> str:
    p = Path(cwd) if isinstance(cwd, str) else cwd
    if not p.is_absolute():
        raise ValueError(f"encode_cwd requires an absolute path; got {p!r}")
    # Collapse `//` -> `/` by going through Path.parts.
    parts = p.parts  # ('/', 'home', 'tunc', '.claude') for /home/tunc/.claude
    # First element is '/' on POSIX; replace with '' so the join produces a leading '-'.
    encoded_parts: list[str] = []
    for part in parts:
        if part == "/":
            encoded_parts.append("")
            continue
        if part.startswith("."):
            encoded_parts.append("-" + part[1:])
        else:
            encoded_parts.append(part)
    return "-".join(encoded_parts)
```

Verified examples (must pass as unit tests):

| Input | Output |
|---|---|
| `/tmp/croam-e2e` | `-tmp-croam-e2e` |
| `/home/tunc/.claude` | `-home-tunc--claude` |
| `/home/tunc/.claude/commands` | `-home-tunc--claude-commands` |
| `/home/tunc/Programs/croam` | `-home-tunc-Programs-croam` |
| `/home/tunc/Sync/.config/nvim` | `-home-tunc-Sync--config-nvim` |
| `/home/tunc/Sync/Programs/aegis/.claude/worktrees/agent-a4501029b9062dc9a` | `-home-tunc-Sync-Programs-aegis--claude-worktrees-agent-a4501029b9062dc9a` |

Edge cases:

- Empty path components (`//`, `/foo//bar`): `Path.parts` already collapses these (`Path("/foo//bar").parts == ('/', 'foo', 'bar')`), so the implementation is correct without extra handling. Add a test asserting this.
- Trailing `/`: `Path("/foo/")` has parts `('/', 'foo')`; trailing slash is ignored. OK.
- Relative paths: raise `ValueError` (not `ConfigError`; this is a programmer error, not a config-file error).
- Path with `~`: caller is expected to expand first. Document in the docstring. If the input contains `~` literally, treat it as a regular character (will produce odd output but caller's bug).

#### `decode_cwd(encoded: str, host_home: Path | None = None, fs_probe: bool = True) -> Path`

Decoding is genuinely lossy. Strategy:

1. Strip the leading `-` (it represents the leading `/`). If the input does not start with `-`, raise `ConfigError(field="encoded_cwd", reason=f"expected leading '-' in {encoded!r}")`.
2. Generate candidate parses. The ambiguity comes from two sources:
   - A `-` could be a `/` separator OR a literal `-` inside a segment.
   - A `--` could be `/` followed by a leading-dot segment (`/.claude` -> `--claude`), OR `/` followed by `-` literal in the segment (`/-foo` -> `--foo`), OR a literal `--` inside a segment.
3. For `fs_probe=True`: enumerate candidates and return the first that exists on the filesystem (probing under `host_home` if absolute resolution doesn't hit, then probing as absolute). Prefer candidates with more dot-prefixed segments (heuristic: `.claude/commands` is more likely than a literal dir named `claude-commands` in real life).
4. For `fs_probe=False`: return a deterministic best-guess candidate using the heuristic "every `--` decodes to `/.`, every other `-` decodes to `/`". This produces wrong answers for paths containing literal `-`, but is good enough for tests that pre-create the path.
5. If `fs_probe=True` and no candidate exists, raise `ConfigError(field="encoded_cwd", reason=f"no plausible decode of {encoded!r} exists on filesystem")`.

Algorithm for candidate generation (recursive):

```python
def _candidates(encoded_segments: list[str]) -> Iterator[list[str]]:
    """Given the result of splitting on '-', yield all plausible reconstructed
    path-component lists. A run of empty strings between non-empty segments
    indicates a `--` (or longer) which can mean: '/' + leading-dot, '/' + '-' literal,
    or part of a literal multi-dash run. We yield each interpretation."""
    # ... (see edge case analysis below)
```

Edge case analysis (these are the cases the test suite must cover):

- Input `-tmp-croam-e2e`: split-on-`-` yields `['', 'tmp', 'croam', 'e2e']`. Candidates: `/tmp/croam/e2e`, `/tmp/croam-e2e`, `/tmp-croam/e2e`, `/tmp-croam-e2e`. With `fs_probe=True` and `/tmp/croam-e2e` existing, that wins.
- Input `-home-tunc--claude`: split yields `['', 'home', 'tunc', '', 'claude']`. The empty between `tunc` and `claude` means `--` which most likely encodes `/.` (path component starting with dot). Candidate: `/home/tunc/.claude`. Alternative: `/home/tunc/-claude` (literal dash leading), much less plausible. Heuristic prefers the dot version.
- Input `-home-tunc--claude-commands`: split yields `['', 'home', 'tunc', '', 'claude', 'commands']`. Candidates: `/home/tunc/.claude/commands`, `/home/tunc/.claude-commands`, `/home/tunc/-claude/commands`, etc. fs_probe picks the existing one.
- Input with no host_home and fs_probe=True: still works, just probes absolute. Pass `host_home=None` and check `Path(candidate).exists()`.
- Input that does not start with `-`: raise `ConfigError`.
- Empty input string: raise `ConfigError`.

Implementation tip: build the candidate set lazily; return on first hit. Cap candidates at e.g. 64 to prevent pathological input from exploding (raise `ConfigError` if exceeded).

#### `normalize_cwd(cwd: Path, host_home: Path) -> str`

```python
def normalize_cwd(cwd: Path, host_home: Path) -> str:
    """Return ~/relative if cwd is under host_home, else absolute string."""
    cwd_resolved = Path(cwd)
    home_resolved = Path(host_home)
    try:
        rel = cwd_resolved.relative_to(home_resolved)
    except ValueError:
        return str(cwd_resolved)
    if rel == Path("."):
        return "~"
    return f"~/{rel}"
```

Edge cases:

- `cwd == host_home` -> `~` (just the tilde, no trailing slash).
- `cwd` outside `host_home` -> absolute string verbatim (e.g. `/tmp/croam-e2e`).
- Symlinks: do NOT resolve. Use `relative_to` on the literal paths. The caller may have already resolved.
- Relative cwd: raise `ValueError` (defensive; should never happen in our codepaths).

#### `denormalize_cwd(normalized: str, host_home: Path) -> Path`

```python
def denormalize_cwd(normalized: str, host_home: Path) -> Path:
    """Inverse of normalize_cwd. '~' or '~/...' becomes host_home / .... 
    Absolute paths returned as-is."""
    if normalized == "~":
        return Path(host_home)
    if normalized.startswith("~/"):
        return Path(host_home) / normalized[2:]
    return Path(normalized)
```

Edge case: `normalized` starts with `~user/...` (a different user's home). Out of scope; the spec assumes per-host `home` config handles user differences. If encountered, raise `ValueError` with a helpful message.

### File: `src/croam/config.py`

Header:

```python
"""TOML config loader and frozen Config dataclass tree.

Single-read at process startup; all consumers receive an immutable Config.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from croam.errors import ConfigError
```

#### Frozen dataclasses

```python
@dataclass(frozen=True)
class HostEntry:
    name: str
    ssh: str
    home: Path | None = None
    sync: bool = True

@dataclass(frozen=True)
class StorageConfig:
    state_root: Path

@dataclass(frozen=True)
class DiscoveryConfig:
    mode: Literal["syncthing", "ssh", "hybrid"]

@dataclass(frozen=True)
class OwnershipConfig:
    claim_verify: Literal["local", "ssh-strict"]

@dataclass(frozen=True)
class PickerConfig:
    default_filter: Literal["exact-pwd", "project-root"]
    last_window_days: int

@dataclass(frozen=True)
class ShimConfig:
    enabled: bool
    opt_out_env: str

@dataclass(frozen=True)
class Config:
    self_hostname: str
    hosts: dict[str, HostEntry]
    storage: StorageConfig
    discovery: DiscoveryConfig
    ownership: OwnershipConfig
    picker: PickerConfig
    shim: ShimConfig
```

Note: `dict[str, HostEntry]` inside a frozen dataclass is mutable. Document in a comment that callers MUST treat it as read-only. Do not wrap in `MappingProxyType` -- adds noise; the convention is enough.

#### `load_config(path: Path | None = None) -> Config`

Behavior:

1. If `path is None`, default to `Path(os.path.expanduser("~/.config/croam/config.toml"))`. The expansion uses `os.path.expanduser`, which honors `$HOME`. Tests redirect `$HOME` via the `home` fixture, so this path becomes `<tmp_path>/home/.config/croam/config.toml`.
2. If the file does not exist, raise `ConfigError(field="path", reason=f"config not found at {path}; run 'croam doctor' to bootstrap")`.
3. Parse via `tomllib.loads(path.read_text())` (or `tomllib.load` with binary open).
4. Validate the schema (see "Validation rules" below).
5. Construct and return `Config`.

Validation rules (every failure raises `ConfigError(field=<dotted-name>, reason=<why>)`):

- `[self]` table exists. `self.hostname` is a non-empty string. If missing -> `ConfigError(field="self.hostname", reason="required field missing")`.
- `[hosts]` table exists. `[hosts.<self_hostname>]` exists with at least an `ssh` key. If missing -> `ConfigError(field="hosts.<self_hostname>", reason="self host must be present in [hosts]")`.
- For each host entry: `ssh` is a non-empty string. If `home` is present, expand `~` and store as `Path`. If absent, leave as `None` (Phase 3 autodetects).
- `[storage]` table exists. `storage.state_root` is a string; expand `~` via `os.path.expanduser` then convert to `Path`. Default if missing: `Path(os.path.expanduser("~/.local/share/croam"))`.
- `[discovery]` table: `mode` in `{"syncthing", "ssh", "hybrid"}`. Default `"syncthing"` if missing.
- `[ownership]` table: `claim_verify` in `{"local", "ssh-strict"}`. Default `"ssh-strict"` if missing.
- `[picker]` table: `default_filter` in `{"exact-pwd", "project-root"}` (default `"exact-pwd"`); `last_window_days` is a positive int (default 30).
- `[shim]` table: `enabled` is bool (default `True`); `opt_out_env` is a non-empty string (default `"CROAM_NO_TMUX"`).

For invalid enum values, the `ConfigError.reason` must list the valid options. Example: `reason="discovery.mode must be one of {'syncthing', 'ssh', 'hybrid'}, got 'foo'"`.

#### `bootstrap_config(path: Path) -> Config`

Writes a minimal-valid skeleton to `path`, creating parent dirs. Uses `os.uname().nodename` as the self hostname. Returns the loaded `Config`.

Skeleton contents:

```toml
[self]
hostname = "<nodename>"

[hosts.<nodename>]
ssh = "<nodename>"
sync = true

[storage]
state_root = "~/.local/share/croam"

[discovery]
mode = "ssh"

[ownership]
claim_verify = "ssh-strict"

[picker]
default_filter = "exact-pwd"
last_window_days = 30

[shim]
enabled = true
opt_out_env = "CROAM_NO_TMUX"
```

After writing, call `load_config(path)` and return the result. Raises `ConfigError` if the freshly-written file fails to parse (defensive; should never happen).

Atomic write: write to `path.with_suffix(".toml.tmp")` first, then `os.replace(tmp, path)`. Mode 0o600 (config may eventually contain SSH config hints; safer to lock down).

---

## Dependencies

**Requires**:
- Phase 1: `src/croam/errors.py` (for `ConfigError`), `tests/conftest.py` (for `home`, `e2e_dummy` fixtures), `pyproject.toml` (for `tomllib` already in stdlib + uv environment).

**Enables**:
- Phase 3: needs `paths.encode_cwd` and `paths.normalize_cwd` for session discovery; needs `Config` for hostname and discovery-mode dispatch.
- Phase 4: needs `Config` (state_root, hostname) and `paths.normalize_cwd` (writing `cwd_normalized`).
- Phase 5: needs `Config` (shim settings, hostname).
- Phase 6, 7, 8, 9: all need `Config`.

---

## Completion Criteria

- [ ] `src/croam/paths.py` exists with the four public functions and signatures specified above
- [ ] `src/croam/config.py` exists with the seven dataclasses and two functions specified above
- [ ] `tests/test_paths.py` and `tests/test_config.py` exist and all tests pass under `uv run pytest tests/test_paths.py tests/test_config.py -v`
- [ ] 100% line coverage on `src/croam/paths.py` and `src/croam/config.py`: `uv run pytest --cov=src/croam/paths --cov=src/croam/config --cov-report=term-missing tests/test_paths.py tests/test_config.py` shows `100%` on both files
- [ ] `uv run pyright src/croam/paths.py src/croam/config.py` passes with zero errors
- [ ] `uv run ruff check src/croam/paths.py src/croam/config.py` passes
- [ ] Tier 2 test `test_e2e_dummy_encoding` passes when `CROAM_E2E=1 uv run pytest tests/test_paths.py::test_e2e_dummy_encoding -v` is invoked, confirming `encode_cwd("/tmp/croam-e2e") == "-tmp-croam-e2e"` AND that `Path.home() / ".claude/projects/-tmp-croam-e2e"` exists on the user's real machine
- [ ] CODEBASE_CONTEXT.md Phase 2 section updated with shipped signatures (one paragraph)

---

## Testing Requirements

All tests use the `home` fixture from Phase 1's conftest (redirects `HOME` to `tmp_path/home/`). The autouse conftest guard refuses to run if `HOME` points at the user's real home unless `CROAM_E2E=1`.

### `tests/test_paths.py`

1. **`test_encode_examples`**: parametrize the six verified examples in the table above. Each `encode_cwd(input) == expected`.
2. **`test_encode_dot_segment`**: explicit cases for `/x/.claude` -> `-x--claude`, `/x/.config` -> `-x--config`, `/x/.local` -> `-x--local`. Also `/.claude` -> `--claude` (root-level dot dir).
3. **`test_encode_double_slash_collapsed`**: `encode_cwd(Path("/foo//bar"))` returns `-foo-bar` (single dash between).
4. **`test_encode_relative_path_raises`**: `encode_cwd("foo/bar")` raises `ValueError`.
5. **`test_decode_lossy_with_fs_probe(home)`**: create `home/foo/bar/` and `home/foo-bar/`. `decode_cwd("-" + str(home).replace("/", "-")[1:] + "-foo-bar", host_home=home, fs_probe=True)` returns the path that actually exists on disk. Test both: with only `/foo/bar` existing, returns `/foo/bar`; with only `/foo-bar` existing (rebuild), returns `/foo-bar`.
6. **`test_decode_no_probe_returns_most_likely`**: `decode_cwd("-tmp-croam-e2e", fs_probe=False)` returns `Path("/tmp/croam/e2e")` (deterministic heuristic); document that this is a known-lossy path.
7. **`test_decode_dot_segment_with_fs_probe(home)`**: create `home/.claude/commands`. `decode_cwd("-" + str(home).replace("/", "-")[1:] + "--claude-commands", host_home=home, fs_probe=True)` returns `home/.claude/commands`.
8. **`test_decode_invalid_input_raises`**: `decode_cwd("no-leading-dash")` raises `ConfigError(field="encoded_cwd", ...)`. Empty string raises.
9. **`test_normalize_under_home(home)`**: `normalize_cwd(home / "Programs/croam", home) == "~/Programs/croam"`.
10. **`test_normalize_outside_home`**: `normalize_cwd(Path("/tmp/croam-e2e"), Path("/home/tunc")) == "/tmp/croam-e2e"`.
11. **`test_normalize_equals_home(home)`**: `normalize_cwd(home, home) == "~"`.
12. **`test_denormalize_round_trip(home)`**: `denormalize_cwd(normalize_cwd(home / "x/y", home), home) == home / "x/y"`.
13. **`test_denormalize_absolute(home)`**: `denormalize_cwd("/tmp/foo", home) == Path("/tmp/foo")`.
14. **`test_e2e_dummy_encoding(e2e_dummy)`** (Tier 2, gated on `CROAM_E2E=1`):
    ```python
    @pytest.mark.skipif(not os.environ.get("CROAM_E2E"), reason="needs real claude")
    def test_e2e_dummy_encoding(e2e_dummy):
        dummy_path, dummy_sid = e2e_dummy
        assert encode_cwd(dummy_path) == "-tmp-croam-e2e"
        # Sanity: the encoded dir actually exists in the user's real ~/.claude/projects
        encoded_dir = Path.home() / ".claude/projects" / "-tmp-croam-e2e"
        assert encoded_dir.is_dir(), f"expected {encoded_dir} to exist"
        assert (encoded_dir / f"{dummy_sid}.jsonl").is_file()
    ```

### `tests/test_config.py`

1. **`test_load_minimal_valid(home)`**: write a minimal-valid TOML to `home/.config/croam/config.toml`. Call `load_config()` (default path). Assert `Config.self_hostname == "test-host"`, `Config.hosts["test-host"].ssh == "test-host"`, `Config.discovery.mode == "ssh"`, `Config.storage.state_root == home / ".local/share/croam"`.
2. **`test_load_missing_self_hostname(home)`**: write TOML without `[self]`. Assert raises `ConfigError` with `field == "self.hostname"`. Use `pytest.raises(ConfigError) as exc_info` and `assert exc_info.value.field == "self.hostname"`.
3. **`test_load_missing_self_in_hosts(home)`**: write TOML with `self.hostname = "foo"` but `[hosts]` only contains `[hosts.bar]`. Assert raises `ConfigError` with `field == "hosts.foo"`.
4. **`test_load_invalid_discovery_mode(home)`**: write TOML with `[discovery] mode = "wibble"`. Assert raises `ConfigError` with `field == "discovery.mode"` and `reason` mentions valid options.
5. **`test_load_state_root_tilde_expansion(home)`**: write TOML with `[storage] state_root = "~/Sync/croam"`. Assert `Config.storage.state_root == home / "Sync/croam"` (expansion against test HOME, not user's real home).
6. **`test_load_invalid_claim_verify(home)`**: similar to #4 but for `[ownership] claim_verify = "wibble"`.
7. **`test_load_uses_defaults_for_optional_sections(home)`**: minimal TOML with only `[self]` and `[hosts.X]`. Assert defaults are populated (`discovery.mode == "syncthing"`, `ownership.claim_verify == "ssh-strict"`, `picker.last_window_days == 30`, `shim.enabled is True`, `shim.opt_out_env == "CROAM_NO_TMUX"`).
8. **`test_bootstrap_writes_skeleton(home)`**: call `bootstrap_config(home / ".config/croam/config.toml")`. Assert the file exists with mode `0o600`. Re-load via `load_config()` and assert the result matches the bootstrap output. Assert hostname matches `os.uname().nodename`.

### Test command

```bash
uv run pytest tests/test_paths.py tests/test_config.py -v
uv run pytest --cov=src/croam/paths --cov=src/croam/config --cov-report=term-missing tests/test_paths.py tests/test_config.py
CROAM_E2E=1 uv run pytest tests/test_paths.py::test_e2e_dummy_encoding -v
uv run pyright src/croam/paths.py src/croam/config.py
uv run ruff check src/croam/paths.py src/croam/config.py
```

---

## Functional QA

This phase ships at Surface 4 (per-host state files / inter-host wire format). `Config` is consumed by every other module; `cwd_normalized` round-trips across hosts via `ownership.json`. The checks below are concrete invocations against the modules.

- [ ] (Surface 4, Loop A) **Encoding rule matches reality.** Run `python -c "from croam.paths import encode_cwd; print(encode_cwd('/home/tunc/.claude/commands'))"` and capture stdout. Assert it equals `-home-tunc--claude-commands` exactly. Then run `ls /home/tunc/.claude/projects/ | grep -E '^-home-tunc--claude-commands$'` (off-test, on the real machine via `CROAM_E2E=1` only) and confirm the directory exists. Paste both outputs into the phase summary's "Functional QA Results" section.
- [ ] (Surface 4, Loop A) **Decode round-trips for the e2e_dummy.** Run the Tier 2 test `CROAM_E2E=1 uv run pytest tests/test_paths.py::test_e2e_dummy_encoding -v`. Output must show `1 passed`. Paste the full pytest output.
- [ ] (Surface 4, Loop A) **`load_config` raises with exact field name when self.hostname is missing.** Write a TOML containing `[hosts.x]\nssh = "x"\n` to `<tmp>/c.toml`, then run `python -c "from pathlib import Path; from croam.config import load_config; load_config(Path('<tmp>/c.toml'))"`. Assert exit code is non-zero and stderr (or the captured traceback) contains the exact string `field="self.hostname"`. Paste the stderr.
- [ ] (Surface 4, Loop A) **`normalize_cwd` returns home-rooted form, not absolute.** Run `python -c "from pathlib import Path; from croam.paths import normalize_cwd; print(normalize_cwd(Path.home()/'Programs/croam', Path.home()))"`. Output must be exactly `~/Programs/croam` (NOT `/home/tunc/Programs/croam`). Paste stdout.
- [ ] (Surface 4, Loop A) **State_root tilde expansion uses test HOME under pytest.** `uv run pytest tests/test_config.py::test_load_state_root_tilde_expansion -v` must pass. The conftest guard prevents the test from accidentally expanding against the real user home; if the guard fires, the test errors instead of polluting `~/.config/croam/`. Paste pytest output.

### Cross-cutting anti-patterns to watch (from FUNCTIONAL_QA_STRATEGY.md)

- **Anti-pattern A (HOME redirect)**: every test takes the `home` fixture. NEVER call `Path.home()` inside test code without the fixture; `Path.home()` returns the real home unless HOME is patched.
- **Anti-pattern D (encoded-cwd tests)**: do not test only `/home/tunc/foo`-shaped paths; the dot-segment cases (`/home/tunc/.claude/commands`) are where encoding rules go wrong. The deliverable mandates the dot cases.

---

## Helpers Required

> None. The encode/decode/normalize logic is pure Python; no shell helper required. The `home` and `e2e_dummy` fixtures from Phase 1 cover all environment setup.

---

## External Interfaces Consumed

- **TOML files (read via stdlib `tomllib`)**
  - **Consumed by**: `src/croam/config.py:load_config`. The shape returned by `tomllib.loads(...)` (a nested `dict` keyed by section name, with values that are `str | int | float | bool | list | dict`) is the interface this phase parses.
  - **How to capture**: write the canonical config from spec section 10 to a temp file, then run:
    ```bash
    python -c "import tomllib; from pathlib import Path; print(tomllib.loads(open('/tmp/sample-croam.toml','rb').read()))"
    ```
    where `/tmp/sample-croam.toml` is the spec section 10 example. Paste the printed dict into the phase summary's "Evidence Captured" section before writing the dataclass mapping logic.
  - **If not observable**: this is stdlib; always observable. The capture command never fails to produce output.

- **Filesystem listing of `~/.claude/projects/`**
  - **Consumed by**: `tests/test_paths.py::test_e2e_dummy_encoding` (Tier 2) and the encoding-rule verification in this phase plan. The interface is "what does the real claude binary write as directory names under `~/.claude/projects/`".
  - **How to capture**: run on the user's real machine (Tier 2 / `CROAM_E2E=1` only):
    ```bash
    ls /home/tunc/.claude/projects/ | head -20
    ```
    Verify the listing includes both ordinary entries (`-home-tunc-Programs-croam`) and dot-segment entries (`-home-tunc--claude`, `-home-tunc--claude-commands`). Paste the first 20 lines into the phase summary.
  - **If not observable**: only happens if the user has not run claude on this host. In that case, fall back to the dummy session at `/tmp/croam-e2e/` (the e2e_dummy fixture provides this) and run `ls /home/tunc/.claude/projects/ | grep tmp-croam-e2e` instead. If even that produces no output, the e2e_dummy fixture is broken; escalate before proceeding.

---

## Notes

- **Lossy decode is by design.** Resist the urge to engineer a clever invertible encoding. claude's encoding is the wire format; we MUST match it. Lossy decode disambiguated by filesystem probe is correct.
- **Avoid `os.path` strings** wherever `pathlib.Path` works. The dataclasses use `Path`; the loader expands `~` via `os.path.expanduser` (because `Path.expanduser()` honors `$HOME` correctly under the test fixture, but `os.path.expanduser` is more conventional for TOML-string handling -- both work, pick one and be consistent).
- **`HostEntry.home`**: `None` means "autodetect at use time". Phase 3 will resolve to `os.path.expanduser("~")` when reading the local host's home, or fail loudly when reading a remote host's home with `home=None`. This phase just stores `None`; do not autodetect here.
- **`os.replace` for atomic writes** in `bootstrap_config`. Never write directly to the destination path; use the `.tmp` -> `os.replace` pattern. Phase 4's ownership.json writer follows the same pattern.
- **Mode 0o600** on the bootstrapped file: use `tmp.chmod(0o600)` before `os.replace` so the destination inherits the locked-down mode. Test asserts `(path.stat().st_mode & 0o777) == 0o600`.
- **No logging in this phase.** The loader runs at startup before logging is configured. If a config error occurs, raise `ConfigError`; the CLI layer translates it to a stderr line.
- **Future enhancement reminder**: per-host `home` autodetect will need claude's `~/.claude/sessions/<PID>.json` `cwd` field to disambiguate username across hosts. That's Phase 3 territory; just leaves a TODO comment in `HostEntry` if helpful.
