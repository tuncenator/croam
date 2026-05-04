# Phase 9: Sync mode & doctor

**Feature**: project-start
**Estimated Context Budget**: ~65k tokens

**Difficulty**: medium
**Visual**: no
**Functional**: yes

**Execution Mode**: parallel
**Batch**: 6 (parallel with Phase 8; both depend on prior batches but have no mutual file contention)

---

## Objective

Implement two cross-cutting modules. `src/croam/sync.py` reads the syncthing mirror (peer state subdirs, conflict files, mtime freshness) without ever calling syncthing's API -- everything is filesystem-only. `src/croam/doctor.py` is the verb that exercises every layer the project has built so far: config, paths, sessions, hosts, ownership, sync. Doctor is the project's smoke test. If `croam doctor` is green on a freshly-installed host, the install works.

This phase does NOT add new wire-level functionality. It composes existing modules into one diagnostic surface and one read-side helper module that Phase 8's forced claim and Phase 10's integration tests both depend on.

---

## Deliverables

1. `src/croam/sync.py` -- syncthing mirror read functions. Pure filesystem access; no syncthing daemon contact.
2. `src/croam/doctor.py` -- diagnostic checks + `run_doctor()` orchestrator + first-run config bootstrap fallback.
3. `croam doctor` typer command wired into `src/croam/cli.py`. The `app` instance and the verb registration pattern were established in Phase 6; this phase only adds the doctor subcommand registration.
4. `tests/test_sync.py` -- unit tests for sync module against synthetic state_root.
5. `tests/test_doctor.py` -- unit + functional tests for the doctor verb via `typer.testing.CliRunner`.

Files this phase MUST NOT touch (other phases own them):

- `src/croam/config.py`, `src/croam/paths.py` (Phase 2)
- `src/croam/sessions.py`, `src/croam/hosts.py` (Phase 3)
- `src/croam/ownership.py` (Phase 4)
- `src/croam/tmux.py`, `src/croam/shim.py` (Phase 5)
- `src/croam/picker.py` (Phase 6)
- `src/croam/commands/*.py` (Phases 7, 8)
- `tests/conftest.py` (Phase 1; only consume its fixtures)

The only edit to `src/croam/cli.py` permitted in this phase is registering the new `doctor` typer command. Do NOT refactor anything else in `cli.py`.

---

## Detailed Requirements

### `src/croam/sync.py`

```python
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from loguru import logger


def read_peer_state_from_mirror(state_root: Path, peer_hostname: str) -> dict[str, Any] | None:
    """Read <state_root>/<peer>/{ownership.json,lineage.json,host-cache.json}.

    Returns a dict with keys 'ownership', 'lineage', 'host_cache' (each value
    is the parsed JSON or {} when the file is absent). Returns None if the
    peer subdir itself does not exist (peer not yet seen on this mirror).
    """


def detect_conflict_files(state_root: Path) -> list[Path]:
    """Return all paths under state_root matching syncthing's conflict pattern.

    Glob: every path matching '*.sync-conflict-*' at any depth under state_root.
    Result is sorted (deterministic for tests). Empty list if state_root is
    missing or contains no conflict files.
    """


def mirror_freshness(state_root: Path, peer_hostname: str) -> timedelta | None:
    """Return time-since-most-recent-mtime under <state_root>/<peer>.

    Walks the peer subdir, collects mtimes of every regular file, returns
    (now - max(mtimes)) as a timedelta. Returns None if the peer subdir
    does not exist OR contains no files.
    """


def mirror_jsonl_path(
    state_root: Path,
    peer_hostname: str,
    encoded_cwd: str,
    sid: str,
) -> Path | None:
    """Return the path to the peer's mirrored JSONL or None if not present.

    Path: <state_root>/<peer>/projects/<encoded_cwd>/<sid>.jsonl
    Returns the Path object only if the file exists. Used by Phase 8's
    forced-claim path.
    """
```

Implementation notes:

- All four functions are pure. They take a `Path` and return data; they never write.
- `read_peer_state_from_mirror` returns the empty dict `{}` for missing component files (not None), so callers can do `state["ownership"].get(sid)` without a None-check on each component. Reserve None for the "peer subdir entirely missing" case.
- JSON parse errors raise `CroamError` (subclass `ConfigError`? no -- introduce nothing new; just log a WARNING and treat the broken file as `{}`). Rationale: syncthing may be mid-write. The doctor's `check_conflict_files` and `check_ownership_consistency` will surface real corruption separately.
- `detect_conflict_files` uses `Path.rglob("*.sync-conflict-*")`. Symlinks are NOT followed (default `rglob` behavior in pathlib follows directory symlinks but does not chase them recursively in a way that loops; we still keep `follow_symlinks=False` semantics by relying on `rglob`'s default).
- `mirror_freshness` does NOT recurse into the peer's own `projects/` subtree by default? Yes it does -- per the brief, mtime of any file under the peer's subdir counts as freshness evidence. Use `Path.rglob("*")` and filter to `is_file()`.
- `mirror_freshness` uses `datetime.now(timezone.utc)` minus `datetime.fromtimestamp(max_mtime, tz=timezone.utc)`. Tests inject mtimes via `os.utime`.
- Log every read at DEBUG level: which file, parsed-vs-skipped, time taken.

### `src/croam/doctor.py`

Module-level constants for thresholds (so tests can monkeypatch):

```python
SYNCTHING_WARN_AGE = timedelta(hours=1)
SYNCTHING_FAIL_AGE = timedelta(hours=24)
SSH_PROBE_TIMEOUT = 2.0
EXTERNAL_TOOLS = ("fzf", "tmux", "ssh", "claude")
```

Dataclass:

```python
@dataclass(frozen=True)
class DiagnosticResult:
    name: str         # short identifier, e.g. "config", "hosts.vicar", "syncthing.corpsefire"
    level: Literal["OK", "WARN", "FAIL"]
    reason: str       # human one-line explanation
    detail: str | None = None  # optional indented second line for the formatter
```

Per-check functions (each returns `DiagnosticResult` or `list[DiagnosticResult]`):

```python
def check_config(config_path: Path) -> DiagnosticResult:
    """OK if file exists and config.load_config(config_path) succeeds.
    FAIL on parse/validation error; the reason names the failed field."""


def check_state_root_writable(state_root: Path) -> DiagnosticResult:
    """OK if state_root exists, is a dir, and a tempfile write+unlink succeeds.
    FAIL otherwise. Use os.access(state_root, os.W_OK) plus a real write probe
    to a hidden tempfile (the host can be lying via mount options)."""


def check_external_tools() -> list[DiagnosticResult]:
    """One result per tool in EXTERNAL_TOOLS.
    OK with version string when found.
    FAIL if not on PATH.
    Use shutil.which(tool) to locate; for version, run `<tool> --version`
    via croam.proc.run with a 2s timeout. If `claude` is on PATH and
    its parent is the user's PATH dir but resolves to a shim, also note
    that `claude-real` exists (informational; OK either way)."""


def check_hosts(config: Config) -> list[DiagnosticResult]:
    """One result per host in config.hosts (excluding self).
    Calls hosts.probe_reachability(...) (Phase 3).
    OK with measured RTT in ms when reachable.
    WARN with the reason string when unreachable (NOT FAIL -- a peer being
    offline is a normal state, not a config error)."""


def check_syncthing(state_root: Path, config: Config) -> list[DiagnosticResult]:
    """One result per peer with sync=True in config (excluding self).
    Calls sync.mirror_freshness(state_root, peer).
    OK if age <= SYNCTHING_WARN_AGE.
    WARN if SYNCTHING_WARN_AGE < age <= SYNCTHING_FAIL_AGE.
    FAIL if age > SYNCTHING_FAIL_AGE OR mirror_freshness returns None
    (peer subdir not present at all -- syncthing has never delivered).
    Returns [] (empty list) if discovery_mode == 'ssh' (no syncthing in use)."""


def check_ownership_consistency(state_root: Path, hostnames: list[str]) -> list[DiagnosticResult]:
    """Read all peer states (via sync.read_peer_state_from_mirror), call
    ownership.merge_assertions on the per-host dicts, and detect:
      - 'outclaim': two hosts assert ownership of the same sid with the
        SAME asserted_at timestamp (true tie -- the merge cannot decide).
        Report as one WARN per ambiguous sid.
      - normal supersession (one host's later assertion overrides another)
        is NOT a problem -- merge handles it. Don't surface it.
    Returns [DiagnosticResult(level='OK', name='ownership', reason='no conflicts')]
    when clean."""


def check_conflict_files(state_root: Path) -> DiagnosticResult:
    """Calls sync.detect_conflict_files. OK if empty list. FAIL otherwise --
    list each conflict file path in detail (newline-joined, indented)."""


def bootstrap_config_if_missing(config_path: Path, default_state_root: Path) -> bool:
    """If config_path does not exist, write a minimal default config to it.
    Returns True if a bootstrap happened, False if the file already existed.

    The default config:
      [self]
      hostname = <socket.gethostname()>

      [hosts.<hostname>]
      ssh = "<hostname>"
      home = "<os.path.expanduser('~')>"
      sync = false

      [storage]
      state_root = "<default_state_root as POSIX string>"

      [discovery]
      mode = "ssh"

      [ownership]
      claim_verify = "local"

      [picker]
      default_filter = "exact-pwd"
      last_window_days = 30

      [shim]
      enabled = false
      opt_out_env = "CROAM_NO_TMUX"

    Use Path.write_text with mode 0o600. Create the parent directory with
    mkdir(parents=True, exist_ok=True) first."""


def run_doctor(config_path: Path, home: Path) -> int:
    """Top-level orchestrator.

    1. If config_path missing: bootstrap_config_if_missing, log INFO.
    2. config = config.load_config(config_path)
    3. Collect results from every check above (in this order):
       - check_config
       - check_state_root_writable(config.state_root)
       - check_hosts(config)
       - check_syncthing(config.state_root, config)
       - check_ownership_consistency(config.state_root, list of all hostnames in config.hosts)
       - check_external_tools
       - check_conflict_files(config.state_root)
    4. format_results(results) -> stdout (printed via plain print/typer.echo;
       NOT loguru -- this is the user-facing report).
    5. Return 0 if no FAIL-level results, else 1.

    NOTE: WARN does NOT cause non-zero exit. Only FAIL does. This matches
    the brief's 'doctor must NOT exit non-zero just because syncthing is stale'."""
```

Output format -- implement this exactly. The header timestamp uses UTC with second resolution (`datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")`):

```
croam doctor (2026-04-30T14:30Z)
================
config:        [OK]   ~/.config/croam/config.toml exists, 3 hosts configured
state_root:    [OK]   ~/Sync/croam writable
hosts:
  stormtree    [OK]   ssh ok (87ms)
  vicar        [OK]   ssh ok (134ms)
  corpsefire   [WARN] ssh failed: Connection refused (last reachable 3h ago)
syncthing:
  vicar        [OK]   mirror fresh (last sync 2m ago)
  corpsefire   [WARN] mirror stale (last sync 4h ago)
ownership:     [OK]   no conflicts
external tools:
  fzf          [OK]   0.65.1
  tmux         [OK]   3.5a
  claude       [OK]   /usr/bin/claude
  ssh          [OK]   OpenSSH_9.9p1
conflict files: [OK]   none

Summary: 1 warning, 0 failures
```

Formatting rules:

- Top-level checks (config, state_root, ownership, conflict files) get one line: `<name>:<padding>[<LEVEL>] <reason>`. Pad the name+colon column to width 16 so all `[`s align. The closing `:` is part of the name column.
- Group sections (hosts, syncthing, external tools) print `<group>:` on its own line and indent each entry two spaces. Inside a group, pad the per-entry name column to width 12.
- The top-level summary line counts `[WARN]` and `[FAIL]` results across every entry (group entries count individually). When zero of either, still print `Summary: 0 warnings, 0 failures` -- never omit the summary.
- All formatting uses ASCII only -- per project rules, no unicode glyphs.
- Print to stdout via `typer.echo()`. Logging stays loguru-style at DEBUG level for the trace of which check ran.

CLI registration in `src/croam/cli.py` (single addition; existing code unchanged):

```python
@app.command("doctor")
def cmd_doctor() -> None:
    """Run diagnostic checks on the croam install."""
    from croam.config import DEFAULT_CONFIG_PATH  # Phase 2 constant
    from croam.doctor import run_doctor
    home = Path.home()
    exit_code = run_doctor(DEFAULT_CONFIG_PATH, home)
    raise typer.Exit(code=exit_code)
```

If `DEFAULT_CONFIG_PATH` does not exist as a Phase 2 export (verify by reading `src/croam/config.py` first), use `Path("~/.config/croam/config.toml").expanduser()` directly inside `cmd_doctor`. Do NOT add a new export to `config.py`.

### Edge cases (handle every one explicitly; do NOT collapse)

1. **Config missing entirely**: `run_doctor` bootstraps via `bootstrap_config_if_missing`, prints an info line `bootstrapped default config at <path>; please review and edit as needed`, then proceeds with the rest of the checks against the freshly-written config. Bootstrap failures (e.g., parent dir not writable) are surfaced as a `FAIL` result for the `config` check.
2. **Config bootstrap is racy with syncthing**: not our problem in v1; the bootstrap writes a file and proceeds.
3. **Peer subdir under state_root missing**: `read_peer_state_from_mirror` returns None. `check_syncthing` treats this as `FAIL` ("syncthing has never delivered for this peer"). `check_ownership_consistency` skips the peer (no assertions to merge).
4. **Peer subdir present but every JSON file inside is missing**: `read_peer_state_from_mirror` returns `{"ownership": {}, "lineage": {}, "host_cache": {}}`. `check_syncthing` looks at `mirror_freshness`, which considers ALL files including any non-JSON debris. If only debris exists, the freshness check still works.
5. **JSON file in peer subdir is malformed**: `read_peer_state_from_mirror` logs a WARNING via loguru and returns `{}` for that component. `check_ownership_consistency` will then see an empty assertion set for that peer; surface this only via the WARNING log line (do NOT add an extra `WARN` to the doctor report -- this is too noisy when syncthing is mid-write; the conflict-file check covers actual corruption).
6. **A `*.sync-conflict-*` file is found**: `check_conflict_files` returns a single `FAIL`. Each conflict path goes into the `detail` field, indented by 2 spaces, newline-joined. Doctor exit code becomes 1.
7. **State root does not exist**: `check_state_root_writable` returns `FAIL`. `check_syncthing` returns `[]` because there is no peer subdir to enumerate. `check_ownership_consistency` returns `[OK]`-equivalent (no peers to compare).
8. **External tool missing**: `check_external_tools` reports `FAIL` for that tool. Other checks unaffected. Exit code becomes 1.
9. **Tool present but `--version` errors out**: report `OK` with reason `present (version probe failed)`. The tool exists; that is the actual check. Version is informational.
10. **Hosts list is empty (no hosts beyond self)**: `check_hosts` returns `[]`. Doctor still passes. Use `[OK] hosts: only self configured` as a single fallback entry so the section is not missing from the report.
11. **discovery_mode = "ssh"**: `check_syncthing` returns `[OK] syncthing: not in use (discovery_mode=ssh)` as a single info entry rather than empty (so the section header stays meaningful).
12. **All hosts unreachable**: every `check_hosts` entry is `WARN`. Doctor exit code is still 0 -- offline peers do not constitute a failure.
13. **Tie-asserted_at outclaim**: `check_ownership_consistency` returns `WARN` with `detail` listing each conflicting `(sid, host_a, host_b, timestamp)` tuple.
14. **Encoded-cwd does not appear here**: this phase does not parse JSONL. `mirror_jsonl_path` only joins paths; it does not decode anything. Phase 8 owns the decoding.
15. **State root contains stray non-hostname directories**: `check_syncthing` only inspects subdirs that match a configured peer hostname. Stray subdirs are silently ignored at this layer (Phase 11's polish may add a "stray dir" warning later).

### Implementation order within this phase

1. Read `src/croam/config.py` (Phase 2 output) to confirm the exact `Config` dataclass field names and `load_config` signature. If `DEFAULT_CONFIG_PATH` exists as an export, use it; else use `Path("~/.config/croam/config.toml").expanduser()` inline.
2. Read `src/croam/hosts.py` (Phase 3) to confirm the exact `probe_reachability` signature and `HostStatus` shape (including whether RTT is exposed; if not, measure it locally with `time.perf_counter()` around the call).
3. Read `src/croam/ownership.py` (Phase 4) to confirm `merge_assertions` and `Assertion` shape.
4. Read `tests/conftest.py` (Phase 1) to confirm the `home`, `state_root`, and `ssh_shim` fixtures and how to populate them.
5. Implement `src/croam/sync.py` with the four functions.
6. Write `tests/test_sync.py` with the four tests in the brief plus the malformed-JSON edge case.
7. Implement `src/croam/doctor.py` -- start with the dataclass, then per-check functions in the order they're called by `run_doctor`, then the formatter, then `run_doctor` itself.
8. Wire `cmd_doctor` into `src/croam/cli.py` (single function addition; do not modify existing commands).
9. Write `tests/test_doctor.py` with the six tests in the brief.
10. Run `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run pyright src/croam/sync.py src/croam/doctor.py`, `uv run pytest tests/test_sync.py tests/test_doctor.py -v`.
11. Run `uv run pytest --cov=src/croam/sync --cov=src/croam/doctor tests/test_sync.py tests/test_doctor.py` and confirm >= 95% coverage.

### Helper for repeat formatting

`_format_results(results: list[DiagnosticResult]) -> str` builds the ASCII report. Pure function, easily unit-tested. Keep this internal to `doctor.py`.

---

## Dependencies

**Requires**:

- Phase 1: logging (`from loguru import logger`), error classes (`CroamError`), `croam.proc.run` wrapper, test conftest with `home`, `state_root`, `ssh_shim` fixtures, autouse HOME guard.
- Phase 2: `Config` dataclass, `load_config(path)`, possibly `DEFAULT_CONFIG_PATH`, `bootstrap` helpers if any. Path normalization functions are not needed here.
- Phase 3: `hosts.probe_reachability(hostnames, timeout_s)` returning `dict[str, HostStatus]`. Used by `check_hosts`.
- Phase 4: `ownership.merge_assertions(per_host)` returning a merged `dict[str, Assertion]`. Used by `check_ownership_consistency`.

**Enables**:

- Phase 8: `sync.mirror_jsonl_path(...)` for the forced-claim path -- claim falls back to the syncthing mirror when the origin is offline.
- Phase 10: integration tests assert that `croam doctor` reports OK against a fully-populated synthetic two-host fixture, and reports the right WARN/FAIL pattern when the fixture is corrupted.
- Phase 11: install/README docs reference `croam doctor` as the post-install verification step.

---

## Completion Criteria

- [ ] `src/croam/sync.py` exists with all four functions, each typed and docstring'd.
- [ ] `src/croam/doctor.py` exists with `DiagnosticResult`, all per-check functions, `bootstrap_config_if_missing`, `run_doctor`, and the internal `_format_results` helper.
- [ ] `src/croam/cli.py` has a new `@app.command("doctor")` function and no other modifications.
- [ ] `tests/test_sync.py` and `tests/test_doctor.py` exist and pass.
- [ ] `uv run ruff check src/ tests/` reports zero issues.
- [ ] `uv run ruff format --check src/ tests/` is clean.
- [ ] `uv run pyright src/croam/sync.py src/croam/doctor.py` reports zero errors.
- [ ] `uv run pytest tests/test_sync.py tests/test_doctor.py -v` is green.
- [ ] `uv run pytest --cov=src/croam/sync --cov=src/croam/doctor tests/test_sync.py tests/test_doctor.py` shows >= 95% coverage on both modules.
- [ ] `uv run croam doctor` runs end-to-end against a synthetic config in a `tmp_path`-rooted HOME and prints the expected report.
- [ ] All edge cases #1-#15 above are exercised by at least one test case.

---

## Testing Requirements

### `tests/test_sync.py`

Tests use the `state_root` and `home` fixtures from `tests/conftest.py` (Phase 1). Synthetic data is hand-constructed JSON files; do NOT depend on `tests/_helpers/synth_assertions.py` (that helper is Phase 4's deliverable -- if it exists and matches the schema, fine to use; otherwise just write JSON literally with `json.dump`).

```python
from datetime import timedelta

def test_read_peer_state_returns_parsed_dict(state_root):
    peer_dir = state_root / "vicar"
    peer_dir.mkdir(parents=True)
    (peer_dir / "ownership.json").write_text('{"sid1": {"owner": "vicar", "asserted_at": "2026-04-30T10:00:00+00:00", "action": "create", "cwd_normalized": "~/foo"}}')
    (peer_dir / "lineage.json").write_text("{}")
    (peer_dir / "host-cache.json").write_text("{}")
    result = read_peer_state_from_mirror(state_root, "vicar")
    assert result is not None
    assert "sid1" in result["ownership"]
    assert result["lineage"] == {}
    assert result["host_cache"] == {}


def test_read_peer_state_returns_none_when_subdir_missing(state_root):
    assert read_peer_state_from_mirror(state_root, "ghost") is None


def test_read_peer_state_handles_partial_files(state_root):
    peer_dir = state_root / "vicar"
    peer_dir.mkdir(parents=True)
    (peer_dir / "ownership.json").write_text('{"sid1": {}}')
    # lineage.json and host-cache.json are missing
    result = read_peer_state_from_mirror(state_root, "vicar")
    assert result == {"ownership": {"sid1": {}}, "lineage": {}, "host_cache": {}}


def test_read_peer_state_handles_malformed_json(state_root, caplog):
    peer_dir = state_root / "vicar"
    peer_dir.mkdir(parents=True)
    (peer_dir / "ownership.json").write_text("{not valid json")
    result = read_peer_state_from_mirror(state_root, "vicar")
    assert result is not None
    assert result["ownership"] == {}  # falls back to empty
    # WARNING was logged; precise assertion depends on loguru/caplog wiring


def test_detect_conflict_files_finds_synthetic(state_root):
    (state_root / "vicar").mkdir(parents=True)
    conflict = state_root / "vicar" / "ownership.sync-conflict-20260430-100000-XYZ.json"
    conflict.write_text("{}")
    result = detect_conflict_files(state_root)
    assert conflict in result


def test_detect_conflict_files_empty_when_none(state_root):
    (state_root / "vicar").mkdir(parents=True)
    (state_root / "vicar" / "ownership.json").write_text("{}")
    assert detect_conflict_files(state_root) == []


def test_detect_conflict_files_handles_missing_root(tmp_path):
    assert detect_conflict_files(tmp_path / "nope") == []


def test_mirror_freshness_returns_age_of_newest_file(state_root, monkeypatch):
    import os, time
    peer_dir = state_root / "vicar"
    peer_dir.mkdir(parents=True)
    f = peer_dir / "ownership.json"
    f.write_text("{}")
    two_hours_ago = time.time() - 7200
    os.utime(f, (two_hours_ago, two_hours_ago))
    age = mirror_freshness(state_root, "vicar")
    assert age is not None
    assert timedelta(hours=1, minutes=58) <= age <= timedelta(hours=2, minutes=2)


def test_mirror_freshness_returns_none_for_missing_peer(state_root):
    assert mirror_freshness(state_root, "ghost") is None


def test_mirror_freshness_returns_none_for_empty_peer(state_root):
    (state_root / "vicar").mkdir(parents=True)
    assert mirror_freshness(state_root, "vicar") is None


def test_mirror_jsonl_path_returns_path_when_present(state_root):
    p = state_root / "vicar" / "projects" / "-tmp-foo" / "abc-sid.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("")
    assert mirror_jsonl_path(state_root, "vicar", "-tmp-foo", "abc-sid") == p


def test_mirror_jsonl_path_returns_none_when_absent(state_root):
    assert mirror_jsonl_path(state_root, "vicar", "-tmp-foo", "abc-sid") is None
```

### `tests/test_doctor.py`

Use `typer.testing.CliRunner` (Surface 1: CLI verbs mechanic from FUNCTIONAL_QA_STRATEGY.md). Tests pass `mix_stderr=False`.

```python
from typer.testing import CliRunner
from croam.cli import app

def test_doctor_clean_setup(home, state_root, ssh_shim, monkeypatch):
    """Loop A. Synthetic clean fixture. Exit 0, every line [OK]."""
    # write a minimal config.toml under home with one self-only host
    # populate state_root/<self>/ with valid empty ownership.json etc.
    # ssh_shim returns success for any reachable probe (only self matters here)
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "[FAIL]" not in result.stdout
    assert "[OK]" in result.stdout
    assert "Summary: 0 warnings, 0 failures" in result.stdout


def test_doctor_missing_config_bootstraps(home, monkeypatch):
    """Loop A. No config.toml. Doctor bootstraps and proceeds."""
    config_path = home / ".config" / "croam" / "config.toml"
    assert not config_path.exists()
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, ["doctor"])
    assert config_path.exists()
    assert "bootstrapped" in result.stdout.lower()
    # exit code may be 0 or 1 depending on whether the bootstrapped state
    # is healthy on its own; assertions on the bootstrap message are the
    # contract here, not exit code.


def test_doctor_unreachable_host(home, state_root, ssh_shim, monkeypatch):
    """Loop G. One host fails the SSH probe. Reports WARN, exit 0."""
    # configure two hosts: self + 'vicar'
    # ssh_shim configured to fail for 'vicar'
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0  # WARN does not fail
    assert "vicar" in result.stdout
    assert "[WARN]" in result.stdout


def test_doctor_stale_syncthing(home, state_root, monkeypatch):
    """Loop G. Peer subdir mtime is 2h old. Reports WARN."""
    import os, time
    peer = state_root / "vicar"
    peer.mkdir(parents=True)
    f = peer / "ownership.json"
    f.write_text("{}")
    two_hours_ago = time.time() - 7200
    os.utime(f, (two_hours_ago, two_hours_ago))
    # configure discovery_mode=syncthing with vicar as a sync=true peer
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0  # WARN does not fail
    assert "syncthing" in result.stdout.lower()
    assert "[WARN]" in result.stdout


def test_doctor_very_stale_syncthing_fails(home, state_root, monkeypatch):
    """24h+ stale mirror is FAIL, exit 1."""
    import os, time
    peer = state_root / "vicar"
    peer.mkdir(parents=True)
    f = peer / "ownership.json"
    f.write_text("{}")
    very_old = time.time() - 86400 * 2  # 2 days
    os.utime(f, (very_old, very_old))
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "[FAIL]" in result.stdout


def test_doctor_conflict_file_detected(home, state_root):
    """Loop G. Synthetic conflict file. Reports FAIL, exit 1."""
    conflict = state_root / "vicar" / "ownership.sync-conflict-20260430-100000-XYZ.json"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("{}")
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "[FAIL]" in result.stdout
    assert "sync-conflict" in result.stdout


def test_doctor_outclaim_detected(home, state_root):
    """Loop G. Two hosts assert ownership of same sid with same timestamp."""
    sid = "tied-sid"
    ts = "2026-04-30T10:00:00+00:00"
    for hostname in ("stormtree", "vicar"):
        peer = state_root / hostname
        peer.mkdir(parents=True)
        (peer / "ownership.json").write_text(
            f'{{"{sid}": {{"owner": "{hostname}", "asserted_at": "{ts}", "action": "create", "cwd_normalized": "~/foo"}}}}'
        )
        (peer / "lineage.json").write_text("{}")
        (peer / "host-cache.json").write_text("{}")
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(app, ["doctor"])
    assert "[WARN]" in result.stdout
    assert sid in result.stdout


def test_format_results_aligns_columns():
    """Pure unit test of the formatter."""
    results = [
        DiagnosticResult(name="config", level="OK", reason="present"),
        DiagnosticResult(name="hosts.vicar", level="WARN", reason="unreachable"),
    ]
    out = _format_results(results, started_at=datetime(2026, 4, 30, 14, 30, tzinfo=timezone.utc))
    assert "[OK]" in out
    assert "[WARN]" in out
    # alignment: [OK] and [WARN] occur at the same column? brackets must align
```

Tests MUST NOT call the real `ssh`, `tmux`, `claude` binaries. The `ssh_shim` fixture handles ssh; for `check_external_tools`, use `monkeypatch` on `shutil.which` or on `croam.proc.run` to inject canned tool versions. Do NOT shell out to the real toolset during pytest.

---

## Functional QA

The five checks below cover Surface 1 (CLI verbs) for the doctor verb, drawn from User Loop A (first-run sanity) and User Loop G (doctor diagnoses). Each is a concrete `runner.invoke(app, [...])` invocation against synthetic fixtures, with a concrete observable.

- [ ] (CLI surface, Loop A) `runner.invoke(app, ["doctor"])` against a synthetic clean fixture (HOME redirected to `tmp_path`, valid `~/.config/croam/config.toml` with one self-only host, empty state_root subdir present, `ssh_shim` returning success for any probe, `shutil.which` patched to return paths for fzf/tmux/ssh/claude) exits with `result.exit_code == 0`. `result.stdout` contains an `[OK]` token for each of: `config`, `state_root`, `hosts:`, `external tools:`, `conflict files:`. The final line matches `Summary: 0 warnings, 0 failures`. Capture full `result.stdout` and paste into the phase summary.
- [ ] (CLI surface, Loop G) `runner.invoke(app, ["doctor"])` with two configured hosts where the `ssh_shim` is rigged to fail probes for `vicar` exits with `result.exit_code == 0` (offline peer is WARN, not FAIL). `result.stdout` contains a line matching the regex `vicar\s+\[WARN\]` and the summary line indicates `1 warning`. Capture full stdout.
- [ ] (CLI surface, Loop G) `runner.invoke(app, ["doctor"])` with a synthetic `state_root/vicar/ownership.sync-conflict-20260430-100000-XYZ.json` file present exits with `result.exit_code == 1`. `result.stdout` contains `[FAIL]` and the literal substring `sync-conflict`. The path of the conflict file appears in the indented detail block. Capture full stdout.
- [ ] (CLI surface, Loop G) `runner.invoke(app, ["doctor"])` with a peer subdir whose newest file mtime is 2 hours ago (set via `os.utime`) exits 0 and `result.stdout` contains `[WARN]` for the `syncthing:` group entry of that peer. With the same file aged to 25 hours via `os.utime`, the same invocation exits 1 and reports `[FAIL]` for that peer. Capture both stdouts.
- [ ] (CLI surface, Loop A) `runner.invoke(app, ["doctor"])` against a HOME with no `~/.config/croam/config.toml` exits without raising (no unhandled exception in `result.exception`). After the call, `(home / ".config" / "croam" / "config.toml").exists()` is True, the file parses as valid TOML, and `result.stdout` contains the substring `bootstrapped`. Capture stdout and the bootstrapped file contents.

Anti-patterns to watch for in this phase (from FUNCTIONAL_QA_STRATEGY.md):

- **A. Tests that don't redirect HOME**: every doctor test takes the `home` fixture. Never call `Path.home()` or `os.path.expanduser("~")` inside `tests/test_doctor.py` -- those will fail under the conftest guard if HOME is somehow not redirected, but it is faster to just always use the fixture path explicitly.
- **B. Mocking SSH bypasses argv assembly**: `check_hosts` calls `hosts.probe_reachability` which spawns the real `ssh` binary. Tests must use `ssh_shim` (a real binary on PATH), never `monkeypatch.setattr(croam.hosts, "subprocess.run", ...)`. Otherwise wrong flag bugs slip through.
- **E. Timezone-naive datetimes**: `mirror_freshness` returns `timedelta`. The reporter formats it via `format_age(td)` (e.g., `"4h ago"`). All datetime arithmetic uses `datetime.now(timezone.utc)` -- never `datetime.now()`. Tests that monkeypatch the clock must also use UTC-aware datetimes.

---

## Helpers Required

This phase has no mechanical dependencies that helpers cover. All actions (file reads, JSON parsing, subprocess calls via `croam.proc.run`) are direct stdlib/Phase-1-wrapper operations.

---

## External Interfaces Consumed

This phase consumes two well-documented interfaces. Capture them once at phase start; do not block on them if capture fails locally (well-documented stdlib + filesystem convention).

- **Filesystem mtime via `os.path.getmtime` / `pathlib.Path.stat().st_mtime`**
  - **Consumed by**: `src/croam/sync.py:mirror_freshness`.
  - **How to capture**: `python -c "import os, time; p='/tmp'; print('mtime:', os.path.getmtime(p)); print('age:', time.time() - os.path.getmtime(p), 's')"`.
  - **If not observable**: stdlib; defer to Python docs at https://docs.python.org/3/library/os.path.html#os.path.getmtime. Mtime is a float of seconds since epoch in local-clock terms (but `time.time()` and `os.path.getmtime` use the same epoch, so subtraction yields seconds-of-real-time on Linux). Paste the captured numbers into the phase summary's "Evidence Captured" section.

- **syncthing conflict-file naming convention**
  - **Consumed by**: `src/croam/sync.py:detect_conflict_files`.
  - **How to capture**: `find ~/Sync -name '*.sync-conflict-*' 2>/dev/null | head -3` -- if the user's syncthing has ever produced a conflict file, this prints real examples. Otherwise reference the docs at https://docs.syncthing.net/users/syncing.html#conflicting-changes which specify the pattern as `*.sync-conflict-<DATE>-<TIME>-<DEVICE_ID>.<EXT>`. Our glob `*.sync-conflict-*` is permissive enough to match any variant.
  - **If not observable**: paste the documented pattern into the phase summary along with at least one synthetic example built from the spec, e.g. `ownership.sync-conflict-20260430-100000-AAAAAAA.json`.

---

## Notes

- Doctor is the project's smoke test. Every other phase relies on `croam doctor` being green to certify a host. If a check is flaky (e.g., RTT measurement gives bogus results when the local SSH agent is unhealthy), prefer reporting `WARN` with a clear reason over `FAIL` -- exit code 1 is reserved for things that genuinely block use of croam.
- The `external tools` section may grow in Phase 11 (e.g., to verify the user installed the claude shim alias correctly). Keep the per-tool result a `DiagnosticResult` so adding tools is a one-line addition.
- The output format above is the contract Phase 11's README documents to users. Do not change column widths, the `Summary:` line, or the section ordering without coordinating with Phase 11.
- `src/croam/cli.py` lives in another phase's logical territory (Phase 6). The single-line `@app.command("doctor")` registration is the ONLY edit permitted. Do not refactor imports, change the typer instantiation, add global flags, or touch any other command. If the existing `cli.py` does not have an `app` instance yet (Phase 6 not done), STOP and surface the issue -- do not invent the typer scaffolding here.
- Tests for the formatter (`_format_results`) are pure unit tests with hand-built `DiagnosticResult` lists -- the cheapest way to lock down the column-alignment contract. Make those tests strict on whitespace.
