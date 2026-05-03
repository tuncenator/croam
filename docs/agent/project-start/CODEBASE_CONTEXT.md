# Codebase Context

> **Living document** -- each phase updates this with new discoveries and changes.
> Read this before exploring the codebase. It may already have what you need.
>
> Last updated by: Checkpoint 5 - Phase 7 merged (2026-05-04)

---

## Architecture Overview

croam is a Python 3.11+ CLI built around three orthogonal concerns:

- **Data layer**: per-host JSON state files (`ownership.json`, `lineage.json`, `host-cache.json`) under `<state_root>/<HOSTNAME>/`, plus claude-code's native session metadata (`~/.claude/sessions/<PID>.json`) and conversation transcripts (`~/.claude/projects/<encoded-cwd>/<sid>.jsonl`).
- **Discovery layer**: SSH probes (parallel, 2s timeout, BatchMode), syncthing mirror reads (filesystem-only -- no syncthing API), or both (hybrid mode).
- **Presentation layer**: typer-based verb dispatcher, fzf-based interactive picker, tmux subprocess control for session attach/peek.

The shim is a separate concern: a thin wrapper around `claude` invoked as `croam launch` (or via the user's `claude` alias) that decides whether to launch inside a tmux session named `claude-<sid>`.

The full design lives at `docs/specs/2026-04-30-croam-design.md`. Phase 1 established the project skeleton (pyproject.toml, src/croam/ tree, test harness, logging). The project is now a runnable Python package with `uv sync` and `uv run croam --help`.

---

## Key Files & Modules

> Will be populated as phases create them. Phase 1 adds `pyproject.toml`, `src/croam/`, `tests/conftest.py`. Subsequent phases add module files.

| File Path | Purpose | Notes |
|-----------|---------|-------|
| `docs/specs/2026-04-30-croam-design.md` | Original design spec, sections 1-16 | Read for big-picture intent. Do NOT modify. |
| `docs/agent/project-start/PROJECT_PLAN.md` | Phase overview, architecture, cross-cutting concerns | Read once at the start of a phase. |
| `docs/agent/project-start/FUNCTIONAL_QA_STRATEGY.md` | Surfaces, user loops, anti-patterns, harness deliverables | Read in full when planning Functional QA checks. |
| `pyproject.toml` | Project metadata, deps (typer, loguru), console script `croam = "croam.cli:main"`, tool configs (ruff, pyright, pytest) | Phase 1; entry point updated by Phase 6 from `croam.cli:app` to `croam.cli:main`. |
| `src/croam/__init__.py` | Package marker (empty) | Phase 1. |
| `src/croam/cli.py` | Full typer app: 7 public verbs (ls, attach, peek, claim, fork, launch, doctor) + hidden emit-state, global callback with --debug/--json/--all/-p/--host/--last/--orphans, no-verb picker dispatch, `main()` CroamError->SystemExit(2) handler. Phase 7 filled cmd_ls, cmd_attach (+ --no-exec), cmd_peek (+ --here-on-owner, --no-exec). | Phase 6 (structure), Phase 7 (verb bodies). |
| `src/croam/log.py` | `configure(level, log_file, debug)` for loguru; uses FilterDict-typed filter_map for pyright compat | Phase 1. |
| `src/croam/errors.py` | `CroamError(Exception)` base + 7 subclasses: ConfigError, SshError, OwnershipConflict, TmuxError, SessionNotFound, OrphanRefused, TimeoutError | Phase 1. |
| `src/croam/proc.py` | `run(argv, *, timeout, check, capture, env, cwd)` subprocess wrapper with DEBUG logging and TimeoutError translation | Phase 1. |
| `src/croam/config.py` | TOML config loader, 7 frozen dataclasses (`HostEntry`, `StorageConfig`, `DiscoveryConfig`, `OwnershipConfig`, `PickerConfig`, `ShimConfig`, `Config`), `load_config`, `bootstrap_config` | Phase 2. 100% coverage. |
| `src/croam/paths.py` | `encode_cwd`, `decode_cwd` (lossy, fs-probe), `normalize_cwd`, `denormalize_cwd` | Phase 2. 100% coverage. |
| `tests/test_paths.py` | 29 tests (28 Tier 1 + 1 Tier 2 e2e), includes `synth_jsonl._encode_cwd` cross-verification | Phase 2. |
| `tests/test_config.py` | 14 tests covering all validation paths and bootstrap skeleton | Phase 2. |
| `src/croam/sessions.py` | `ClaudeSession` dataclass, `discover_local_sessions`, `tmux_attached`; joins `~/.claude/projects/` transcripts with `~/.claude/sessions/` metadata | Phase 3. 91% coverage. |
| `src/croam/hosts.py` | `HostStatus`, `probe_reachability` (parallel SSH), `emit_state` (wire format), `fetch_remote_state` | Phase 3. 100% coverage. |
| `src/croam/commands/__init__.py` | Package marker for command modules (one module per verb) | Phase 3. |
| `src/croam/commands/emit_state.py` | `emit_state_cmd(home, state_root, hostname) -> int`; Phase 6 wires into typer | Phase 3. |
| `src/croam/ownership.py` | `Assertion`, `LineageEntry` dataclasses; read/write/merge/flatten/detect_outclaim + lineage; atomic writes via `os.replace` | Phase 4. 100% coverage. |
| `src/croam/tmux.py` | Five argv-builders + five side-effecting wrappers (has_session, new_session_detached, attach, kill_session, list_sessions) | Phase 5. 89% coverage. |
| `src/croam/shim.py` | Pure decision functions: `should_wrap`, `derive_sid`, `strip_no_tmux`, `find_claude_real`, `is_in_tmux` | Phase 5. 100% coverage. |
| `src/croam/commands/launch.py` | `LaunchPlan` dataclass, `build_launch_plan` (pure), `launch_cmd` orchestrator with `--no-exec` mode and assertion-before-side-effect contract | Phase 5. 95% coverage. |
| `src/croam/picker.py` | `PickerRow` dataclass, `format_last_column`, `compute_glyph`, `compute_status_word`, `render_rows`, `format_input_lines`, `build_fzf_argv`, `launch_picker`, `compute_action_intersection` | Phase 6. 91% coverage. |
| `src/croam/commands/default.py` | `run_picker` orchestrator: discover -> filter -> render -> launch -> dispatch. `_dispatch` routes enter->attach, p->peek, ctrl-r->re-run, c/C/f/F->NotImplementedError("Phase 8"), multi-row with action intersection. | Phase 6 (structure), Phase 7 (full dispatch). |
| `src/croam/transcript.py` | `render_static_transcript(jsonl_path, *, fp=sys.stdout) -> int`; `_extract_text(message_field) -> str` handles string/dict/list-block shapes | Phase 7. 100% coverage. |
| `src/croam/commands/ls.py` | `run(ctx_obj, config, home) -> int`; JSON/text listing with --all, --host, --last, --orphans, PWD filter | Phase 7. 96% coverage. |
| `src/croam/commands/peek.py` | `run(sid, ctx_obj, config, home, *, here_on_owner, no_exec) -> int`; local tmux/archived/remote reachable/unreachable mirror dispatch | Phase 7. 90% coverage. |
| `src/croam/commands/attach.py` | `run(sid, ctx_obj, config, home, *, here_on_owner, no_exec) -> int`; recursion guard, tmux-attach/new-and-attach/ssh-recurse/SshError | Phase 7. 93% coverage. |
| `src/croam/sync.py` | syncthing mirror access (read-only filesystem); conflict file detection | Created in Phase 9. |
| `src/croam/doctor.py` | Diagnostics: config + SSH + syncthing + ownership consistency | Created in Phase 9. |
| `tests/conftest.py` | 5 fixtures (home, tmux_socket, ssh_shim, state_root, e2e_dummy) + `pytest_runtest_call` hookwrapper safety guard | Phase 1. |
| `tests/_helpers/synth_jsonl.py` | `build_jsonl(home, sid, cwd)` with inlined `_encode_cwd` (standalone, no src/ deps) | Phase 1. |
| `tests/_helpers/synth_session.py` | `build_session_metadata(home, pid, sid, cwd)` | Phase 1. |
| `tests/_helpers/synth_assertions.py` | `build_assertion(sid, owner, asserted_at, ...)` and `write_assertions_file(state_root, hostname, assertions)` for test seeding | Phase 4. |
| `tests/_helpers/fake_fzf.py` | `make_fake_fzf(tmp_path, output, exit_code)` generates executable shell scripts for deterministic fzf subprocess testing | Phase 6. |
| `tests/_helpers/fake_ssh.py` | `SSH_SHIM_SCRIPT` + `fixture_path_for()` for argv-hashed fixture lookup | Phase 1. |
| `tests/test_smoke.py` | 14 smoke tests covering all fixtures, log, errors, proc, safety guard | Phase 1. |
| `tests/test_sessions.py` | 19 Tier-1 + 1 Tier-2 tests for session discovery and tmux_attached | Phase 3. |
| `tests/test_hosts.py` | 15 tests for SSH probes, emit_state, fetch_remote_state, emit_state_cmd | Phase 3. |
| `tests/test_ownership.py` | 43 tests covering all read/write/merge/flatten/lineage paths + atomic write fault injection | Phase 4. |
| `tests/test_tmux.py` | 13 tests (argv builders + real tmux integration via tmux_socket) | Phase 5. |
| `tests/test_shim.py` | 24 pure-function tests covering all branches of all five shim functions | Phase 5. |
| `tests/test_launch.py` | 8 integration tests for build_launch_plan and launch_cmd (uses --no-exec and real tmux) | Phase 5. |
| `tests/test_cli.py` | 6 tests for CLI surface: help verbs, hidden emit-state, emit-state wiring, debug flag, CroamError handler, cmd_launch config | Phase 6, updated Phase 7. |
| `tests/test_picker.py` | 24 tests (10 parametrized format_last_column + 14 others) for picker pure functions and launch_picker subprocess | Phase 6. |
| `tests/test_transcript.py` | 20 tests for transcript rendering (_extract_text shapes, file errors, message types) | Phase 7. |
| `tests/test_ls.py` | 10 tests for ls command (empty, JSON, text, PWD filter, --all, --host, orphans, --last) | Phase 7. |
| `tests/test_peek.py` | 12 tests for peek command (local live/archived, remote reachable/unreachable, mirror, here_on_owner) | Phase 7. |
| `tests/test_attach.py` | 10 tests for attach command (local running/archived, remote reachable/unreachable, recursion guard, picker fallback) | Phase 7. |
| `tests/test_default_dispatch.py` | 11 tests for _dispatch routing (enter, p, ctrl-r, c/C/f/F phase 8 stubs, multi-row) | Phase 7. |
| `tests/fixtures/` | Synthetic session JSONLs, ownership.json snapshots, sample TOML configs | Created across Phase 4, 7. |

---

## Important APIs & Interfaces

> Will be populated as phases ship them. Documenting key signatures here saves future agents from re-reading source files.

### Phase 1 deliverables (finalized)

```python
# src/croam/log.py
def configure(level: str = "INFO", log_file: Path | None = None, debug: bool = False) -> None: ...

# src/croam/errors.py
class CroamError(Exception): ...
class ConfigError(CroamError): ...   # field: str | None, reason: str | None
class SshError(CroamError): ...
class OwnershipConflict(CroamError): ...
class TmuxError(CroamError): ...
class SessionNotFound(CroamError): ...
class OrphanRefused(CroamError): ...
class TimeoutError(CroamError): ...  # argv: list[str] | None, timeout_s: float | None

# src/croam/proc.py
def run(argv: list[str], *, timeout: float | None = None, check: bool = False,
        capture: bool = True, env: dict[str, str] | None = None,
        cwd: Path | str | None = None) -> subprocess.CompletedProcess[str]: ...
```

### Phase 2 (paths and config) -- FINALIZED

```python
# src/croam/paths.py
def encode_cwd(cwd: Path | str) -> str:
    """Encode an absolute path to claude's encoded-cwd format.
    Each `/` separator and each leading `.` in a path component becomes `-`.
    Raises ValueError for relative paths.
    """

def decode_cwd(encoded: str, host_home: Path | None = None, fs_probe: bool = True) -> Path:
    """Best-effort decode. With fs_probe=True probes the filesystem; uses known-prefix
    shortcut when host_home is provided (handles paths with many literal dashes).
    Raises ConfigError(field='encoded_cwd') for missing leading '-' or no match found.
    """

def normalize_cwd(cwd: Path, host_home: Path) -> str:
    """Return ~/relative if cwd is under host_home, else absolute string.
    Returns '~' (no trailing slash) when cwd == host_home.
    Raises ValueError for relative cwd.
    """

def denormalize_cwd(normalized: str, host_home: Path) -> Path:
    """Inverse of normalize_cwd. '~' or '~/...' -> host_home/rest. Absolute as-is.
    Raises ValueError for ~user/... paths.
    """

# src/croam/config.py -- seven frozen dataclasses
@dataclass(frozen=True)
class HostEntry:
    name: str; ssh: str; home: Path | None = None; sync: bool = True

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
    hosts: dict[str, HostEntry]   # treat as read-only; mutable by language but convention is immutable
    storage: StorageConfig
    discovery: DiscoveryConfig
    ownership: OwnershipConfig
    picker: PickerConfig
    shim: ShimConfig

def load_config(path: Path | None = None) -> Config:
    """Load from path (default ~/.config/croam/config.toml via os.path.expanduser).
    Raises ConfigError(field=...) for missing file or schema violations.
    """

def bootstrap_config(path: Path) -> Config:
    """Write skeleton TOML (nodename from os.uname()), mode 0o600, atomic via tmp->replace.
    Returns load_config(path).
    """
```

### Phase 3 (sessions and host probes) -- FINALIZED

```python
# src/croam/sessions.py
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

def discover_local_sessions(home: Path) -> list[ClaudeSession]:
    """Scan ~/.claude/projects/* for transcripts, join with ~/.claude/sessions/*.json by sid.
    Returns sorted by updated_at_ms desc (nulls last), sid asc tiebreak."""

def tmux_attached(sid: str, sock: Path | None = None) -> tuple[bool, bool]:
    """Returns (has_session, attached). Uses proc.run against tmux."""

# src/croam/hosts.py
@dataclass(frozen=True)
class HostStatus:
    name: str
    reachable: bool
    last_probed: datetime  # tz-aware UTC
    error: str | None      # None when reachable; populated otherwise

def probe_reachability(hosts: list[str], timeout_s: float = 2.0) -> dict[str, HostStatus]:
    """Parallel SSH probes via ThreadPoolExecutor (max 8 workers)."""

def emit_state(home: Path, state_root: Path, hostname: str) -> dict:
    """Build the JSON wire format for `croam emit-state`. Returns raw dict (no datetimes/Paths).
    Keys: hostname, ownership, lineage, host_cache, sessions."""

def fetch_remote_state(host: str, ssh_alias: str, timeout_s: float = 5.0) -> dict | None:
    """SSH to peer and run `croam emit-state --json`. Returns parsed dict or None on failure."""

# src/croam/commands/emit_state.py
def emit_state_cmd(home: Path, state_root: Path, hostname: str) -> int:
    """Print per-host state JSON to stdout. Returns 0 on success."""
```

### Phase 4 (ownership) -- FINALIZED

```python
# src/croam/ownership.py
@dataclass(frozen=True)
class Assertion:
    sid: str
    owner: str
    asserted_at: datetime  # MUST be tz-aware; __post_init__ enforces
    action: Literal["create", "claim", "release"]
    cwd_normalized: str
    previous_owner: str | None = None  # required for claim, forbidden for non-claim

@dataclass(frozen=True)
class LineageEntry:
    fork_sid: str
    parent_sid: str
    fork_n: int

def read_local_assertions(state_root: Path, hostname: str) -> dict[str, Assertion]:
    """Read <state_root>/<hostname>/ownership.json. Returns {} if absent."""

def read_all_assertions(
    state_root: Path, peer_states: dict[str, dict] | None = None
) -> dict[str, dict[str, Assertion]]:
    """Read all hosts' ownership.json. peer_states overrides on-disk for those peers."""

def merge_assertions(per_host: dict[str, dict[str, Assertion]]) -> dict[str, Assertion]:
    """Most-recent-asserted_at wins per sid. Tiebreaker: alphabetical-by-owner (smaller wins)."""

def write_local_assertions(
    state_root: Path, hostname: str, assertions: dict[str, Assertion]
) -> None:
    """Atomic write of <state_root>/<hostname>/ownership.json via tempfile + fsync + os.replace."""

def write_local_assertion(state_root: Path, hostname: str, assertion: Assertion) -> None:
    """Singular convenience wrapper: reads existing file, inserts one assertion, rewrites atomically."""

def flatten_local(state_root: Path, hostname: str, merged: dict[str, Assertion]) -> None:
    """Rewrite our own ownership.json keeping only entries we currently own per merged view."""

def detect_outclaim(
    state_root: Path, hostname: str, merged: dict[str, Assertion]
) -> list[str]:
    """Returns sorted sids where local has an assertion but merged[sid].owner != hostname."""

def read_lineage(state_root: Path, hostname: str) -> dict[str, LineageEntry]: ...
def write_lineage(state_root: Path, hostname: str, lineage: dict[str, LineageEntry]) -> None: ...
def add_lineage(state_root: Path, hostname: str, fork_sid: str, parent_sid: str) -> int:
    """Append lineage entry; compute fork_n = max existing for parent + 1. First fork yields 1."""
```

On-disk JSON schema (frozen by Phase 4):
- `asserted_at` uses `+00:00` suffix (Python `datetime.isoformat()`), not `Z`. Reader accepts both via `_parse_iso_utc`.
- `previous_owner` key is ALWAYS present (null for non-claim).
- `sort_keys=True` + `sorted(assertions.items())` produce stable byte-identical output.
- Tempfile pattern: `.{name}.tmp.{pid}.{hex4}` with fsync before `os.replace`.

### Phase 5 (tmux, shim, launch) -- FINALIZED

```python
# src/croam/tmux.py -- argv builders (pure, public)
def build_has_session_argv(name: str, sock: Path | None) -> list[str]: ...
def build_new_session_argv(name: str, command: list[str], sock: Path | None) -> list[str]: ...
def build_attach_argv(name: str, sock: Path | None, read_only: bool) -> list[str]: ...
def build_kill_session_argv(name: str, sock: Path | None) -> list[str]: ...
def build_list_sessions_argv(sock: Path | None) -> list[str]: ...

# src/croam/tmux.py -- side-effecting wrappers
def has_session(name: str, sock: Path | None = None) -> bool: ...
def new_session_detached(name: str, command: list[str], *, sock: Path | None = None,
                         env: dict[str, str] | None = None) -> None: ...
def attach(name: str, *, sock: Path | None = None, read_only: bool = False) -> NoReturn: ...
def kill_session(name: str, sock: Path | None = None) -> None:
    """Idempotent: handles can't-find-session, no-server-running, error-connecting-to,
    server-exited-unexpectedly, no-current-target."""
def list_sessions(sock: Path | None = None) -> list[tuple[str, bool]]:
    """Returns [(name, attached), ...]. Empty list if server not running."""

# src/croam/shim.py -- pure decision functions
def should_wrap(argv: list[str], env: dict[str, str], stdin_isatty: bool,
                in_tmux: bool, opt_out_env_name: str = "CROAM_NO_TMUX") -> bool:
    """False if: not tty, in tmux, opt-out env set, --no-tmux, --print, --help/-h."""
def derive_sid(argv: list[str], env: dict[str, str]) -> str:
    """Resume sid if --resume <sid> or --resume=<sid> in argv; else uuid4."""
def strip_no_tmux(argv: list[str]) -> list[str]: ...
def find_claude_real() -> Path:
    """Prefers claude-real, falls back to claude. Raises CroamError if neither found."""
def is_in_tmux(env: dict[str, str]) -> bool: ...

# src/croam/commands/launch.py
@dataclass(frozen=True)
class LaunchPlan:
    mode: Literal["wrap", "passthrough"]
    sid: str
    claude_argv: list[str]
    cwd_normalized: str
    tmux_session_name: str | None = None
    tmux_new_argv: list[str] | None = None
    tmux_attach_argv: list[str] | None = None
    passthrough_argv: list[str] | None = None

def build_launch_plan(argv: list[str], env: dict[str, str], stdin_isatty: bool,
                      cwd: Path, home: Path, config: Config,
                      sock: Path | None = None) -> LaunchPlan:
    """Pure function. Decides wrap-vs-passthrough, derives sid, builds all argvs."""

def launch_cmd(argv: list[str], config: Config, home: Path, *, cwd: Path | None = None,
               env: dict[str, str] | None = None, stdin_isatty: bool | None = None,
               sock: Path | None = None, no_exec: bool = False) -> int:
    """Writes assertion BEFORE side effects. --no-exec prints plan as JSON."""
```

Key design notes:
- `should_wrap` receives the ORIGINAL argv (before strip_no_tmux) so `--no-tmux` detection works.
- `kill_session` idempotency covers five distinct tmux stderr substrings.
- `launch_cmd` writes ownership assertion before tmux/exec (assertion-before-side-effect contract).
- `attach` is `NoReturn` (calls `os.execvp`). The `test_launch_cmd_real_tmux` test patches it.

### Phase 6 (picker & CLI dispatcher) -- FINALIZED

```python
# src/croam/cli.py
# Entry point: croam = "croam.cli:main" (pyproject.toml)
import typer
app = typer.Typer(name="croam", no_args_is_help=False, pretty_exceptions_enable=False,
                  add_completion=False, invoke_without_command=True)

# Global callback wires: --debug, --json, --all/-A, -p, --host, --last, --orphans
# No-verb path -> commands.default.run_picker (via load_config + dispatch)
# main() catches CroamError -> SystemExit(2) with "croam: <msg>" on stderr
# Note: SystemExit(2), NOT typer.Exit(2) -- typer.Exit outside click context yields exit code 1

# 7 public verbs: ls, attach, peek, claim, fork, launch, doctor
# 1 hidden verb: emit-state
# Stubs raise NotImplementedError("Phase N") until filled by later phases

# src/croam/picker.py
@dataclass(frozen=True)
class PickerRow:
    sid: str            # column 1 (hidden filter)
    glyph: str          # column 2 (displayed) -- "o" reachable, "O" unreachable
    status_word: str    # column 3 (hidden filter) -- "running-idle"|"running-busy"|"archived"|"unreachable"
    reach_word: str     # column 4 (hidden filter) -- "reachable"|"unreachable"
    cwd_word: str       # column 5 (hidden filter) -- "present"|"missing-cwd"
    host: str           # column 6 (displayed)
    last: str           # column 7 (displayed) -- "Nm"|"Nh"|"ND"|"NM"|"-"
    cwd_display: str    # column 8 (displayed) -- "~/Programs/foo" (untruncated; fish-style TODO phase-11)
    name: str           # column 9 (displayed) -- session name + lineage tag if forked

def format_last_column(updated_at_ms: int | None, now: datetime) -> str: ...
def compute_glyph(host_status: HostStatus | None) -> str: ...
def compute_status_word(session: ClaudeSession, host_status: HostStatus | None) -> str: ...
def render_rows(sessions: list[ClaudeSession], assertions: dict[str, Assertion],
                host_statuses: dict[str, HostStatus], pwd: Path | None,
                lineage: dict[str, LineageEntry], *, now: datetime | None = None,
                host_homes: dict[str, Path] | None = None) -> list[PickerRow]: ...
def format_input_lines(rows: list[PickerRow]) -> str: ...
def build_fzf_argv(filter_pwd: Path | None) -> list[str]: ...
def launch_picker(rows: list[PickerRow], filter_pwd: Path | None, *,
                  fzf_binary: str = "fzf",
                  env_overrides: dict[str, str] | None = None) -> tuple[str, list[PickerRow]]:
    """Returns (expect-key, selected rows). Empty key means plain Enter.
    Empty rows -> ("", []) without launching fzf."""
def compute_action_intersection(selected: list[PickerRow], *, self_hostname: str) -> set[str]:
    """Universe: {"attach","peek","claim","fork","claim-here","fork-here"}.
    Returns intersection of safe actions across all selected rows."""

# src/croam/commands/default.py
def run_picker(*, config: Config, home: Path, ctx_obj: dict) -> int:
    """Orchestrate: discover -> filter -> render -> launch -> dispatch."""
```

### Phase 7 (attach, peek, ls, transcript, dispatch) -- FINALIZED

```python
# src/croam/transcript.py
def render_static_transcript(jsonl_path: Path, *, fp: TextIO = sys.stdout) -> int:
    """Render JSONL transcript to fp. Returns 0 on success, 1 if file missing/unreadable.
    Handles user/assistant message types; skips metadata lines."""

def _extract_text(message_field: str | dict | list) -> str:
    """Extract text from message field: plain string, dict with string/list content,
    or list of content blocks. Falls back to json.dumps for unknown shapes."""

# src/croam/commands/ls.py
def run(ctx_obj: dict, config: Config, home: Path) -> int:
    """List sessions as JSON or text. Respects ctx_obj flags: json_mode, all_mode,
    host_filter, last_days, orphans_only. PWD filter applies when none of
    all_mode/host_filter/orphans_only are set."""

# src/croam/commands/attach.py
def run(sid: str, ctx_obj: dict, config: Config, home: Path, *,
        here_on_owner: bool = False, no_exec: bool = False) -> int:
    """Attach to session. Local: tmux-attach (running) or tmux-new-and-attach (archived).
    Remote reachable: ssh-recurse with --here-on-owner. Remote unreachable: SshError.
    --no-exec: print plan as JSON instead of exec'ing. Raises SessionNotFound, SshError."""

# src/croam/commands/peek.py
def run(sid: str, ctx_obj: dict, config: Config, home: Path, *,
        here_on_owner: bool = False, no_exec: bool = False) -> int:
    """Peek at session (read-only). Local live: tmux-peek (read-only attach).
    Local archived: render_static_transcript. Remote reachable: ssh-recurse.
    Remote unreachable: mirror JSONL if available, else SshError."""

# src/croam/commands/default.py
def _dispatch(expect_key: str, selected: list[PickerRow], ctx_obj: dict,
              config: Config, home: Path) -> int:
    """Route picker selection to verb. enter->attach, p->peek, ctrl-r->re-run picker,
    c/C/f/F->NotImplementedError('Phase 8'). Multi-row: iterates with action intersection check."""
```

Key design notes (Phase 7):
- `--no-exec` is the test seam: outputs `{"action": "...", "argv": [...]}` JSON, exit 0.
- `CROAM_NO_EXEC=1` env var also triggers no-exec mode.
- `CROAM_TMUX_SOCK` env var overrides tmux socket path in attach/peek. Tests set via monkeypatch.
- `render_static_transcript` must be called with explicit `fp=sys.stdout` at call sites (not relying on default arg) for CliRunner compatibility.
- Error-exit tests (SessionNotFound, SshError -> exit 2) use subprocess invoking main(), not CliRunner, because CliRunner bypasses main()'s CroamError handler.
- `_dispatch` signature: `(expect_key, selected, ctx_obj, config, home)`. Phase 8 extends c/C/f/F branches.

Wire-format invariant: `<sid>\t<glyph>\t<status_word>\t<reach_word>\t<cwd_word>\t<host>\t<last>\t<cwd_display>\t<name>\n`.
fzf uses `--with-nth=2,6,7,8,9` (columns 1,3,4,5 hidden but searchable). `{1}` references sid in preview/binds.
`$FZF_SELECT_COUNT` (NOT `FZF_SELECTED_COUNT`).
`FZF_DEFAULT_OPTS=""` always set in launch_picker env to prevent user shell defaults from poisoning flags.

Key design notes:
- `main()` uses `SystemExit(2)` not `typer.Exit(2)` for CroamError translation (typer.Exit outside click context yields exit code 1)
- `CliRunner()` in typer does not support `mix_stderr=False` (that's click-only)
- `launch_picker` uses `stderr=None` (never `subprocess.PIPE`): fzf draws on /dev/tty
- `_resolve_cwd` in render_rows uses `Path.home()` (redirected by tests via HOME env) unless host_homes dict provided

---

## Patterns & Conventions

### Module boundaries

Each `src/croam/<module>.py` exposes a small, well-typed public API. Internal helpers stay underscored. Cross-module imports go through public interfaces -- never reach into another module's internals.

### Error handling

- Domain errors raise `CroamError` subclasses. `cli.py` catches them at the top level, prints a one-liner to stderr, exits non-zero.
- Subprocess failures (`subprocess.run` returncode != 0) translate to `CroamError` with the captured stderr.
- SSH timeouts are NOT errors -- they are reachability=False signals. Catch `subprocess.TimeoutExpired`, set `reachable=False`, continue.
- Use `os.replace()` for atomic file writes. Never write directly with `open(..., 'w')` for state files (`ownership.json`, etc.) because syncthing or another croam process may read mid-write.
- Always validate config at load time and raise `ConfigError` with a clear field-naming message.

### Safety guard

The conftest safety guard is a `pytest_runtest_call` hookwrapper (not an autouse fixture). It fires after all fixture setup completes, so by the time it checks HOME, the `home` fixture has already redirected it via monkeypatch. The guard logic is extracted into `_check_home_redirected(home, e2e)` for testability. Tests that don't use `home` must still be aware the guard will fire and reject them if HOME isn't redirected.

### Dependency injection

Pure functions over implicit globals. State files are passed as `state_root: Path`, hostnames as `hostname: str`, etc. The CLI layer is the only place that resolves "what is HOME, what is the config path, what is `state_root`" -- everything else takes those as parameters. This makes the test fixtures trivial: redirect HOME, point at a tmp_path state_root, done.

### Subprocess invariants

- All subprocess calls go through a thin `croam.proc.run(...)` helper (Phase 1 deliverable) that:
  - Uses `subprocess.run(..., check=False, capture_output=True, text=True)` by default
  - Logs the argv at DEBUG level
  - Honors a `timeout` kwarg (default None)
  - Translates `TimeoutExpired` into our own typed exception
- For SSH calls: always include `-o ConnectTimeout=2 -o BatchMode=yes -o StrictHostKeyChecking=no` to prevent password/host-key prompts from hanging the process.
- For tmux calls: support an optional socket path via `-S <path>` so tests can use a private socket.

### End-to-end flow example: `croam attach <sid>` for a remote-owned session

1. `cli.py:cmd_attach(target=sid)` -> dispatches to `croam.commands.attach.run(sid)`.
2. `attach.run` calls `ownership.merged_view()` to determine the current owner of `sid`.
3. If owner != self_hostname AND owner is reachable: SSH to owner with `croam attach <sid> --here-on-owner` (recursion guard).
4. Owner-side `attach` resolves locally: checks `tmux has-session -t claude-<sid>`. If yes, `exec tmux attach -t claude-<sid>`. If no, `tmux new-session -d -s claude-<sid> claude --resume <sid>` then `exec tmux attach`.
5. Local terminal is now attached to the remote tmux session.

If owner is unreachable: error out with `SshError("origin <name> unreachable; try 'croam peek' for read-only static transcript")`.

---

## Data Models

### Per-host state (croam-managed)

`<state_root>/<HOSTNAME>/ownership.json`:
```json
{
  "<sid>": {
    "owner": "<HOSTNAME>",
    "asserted_at": "<ISO8601 UTC>",
    "action": "create|claim|release",
    "cwd_normalized": "~/Programs/foo or /abs/path",
    "previous_owner": "<HOSTNAME> or null"
  }
}
```

`<state_root>/<HOSTNAME>/lineage.json`:
```json
{
  "<fork-sid>": {"parent_sid": "<sid>", "fork_n": 1}
}
```

`<state_root>/<HOSTNAME>/host-cache.json`:
```json
{
  "<peer>": {"last_reachable": "<ISO8601 UTC>", "last_sync": "<ISO8601 UTC>"}
}
```

### Claude-native (read-only from croam)

#### `~/.claude/sessions/<PID>.json`

**Keyed by PID, not sid.** Schema observed (claude version 2.1.123, 2026-04):

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
  "updatedAt": 1777532759343,
  "name": "2026-04-30_1745_ai-agent-setup"
}
```

Observed `status` values: `"idle"`, `"busy"`. Other values may exist; treat unknown values as `"idle"` for picker color decisions.

`name` is optional -- only present when the user ran `/rename` or claude auto-named the session.

**Sessions metadata is absent for exited sessions.** Discovery rule: session is "running" iff there exists a sessions/*.json with `sessionId == sid`. Otherwise "archived" (transcript exists in `~/.claude/projects/...` but no live process).

#### `~/.claude/projects/<encoded-cwd>/<sid>.jsonl`

Conversation transcript. Line types observed (claude 2.1.123):
- `last-prompt`: `{type, leafUuid, sessionId}` -- typically line 1
- `permission-mode`: `{type, permissionMode, sessionId}` -- typically line 2
- `attachment`: `{parentUuid, isSidechain, attachment, type, uuid, timestamp, userType, entrypoint, cwd, sessionId, version, gitBranch}` -- hook/MCP attachments
- `file-history-snapshot`: `{type, messageId, snapshot, isSnapshotUpdate}` -- file edit checkpoints
- `user`: `{parentUuid, isSidechain, promptId, type, message, uuid, timestamp, permissionMode, userType, entrypoint, cwd, sessionId, version, gitBranch}` -- user prompts
- `assistant` (not observed in the dummy but well-known): assistant responses
- `tool_use` / `tool_result` (not observed): tool invocations

Conversation entries (user, attachment, etc.) carry `cwd` (absolute, original origin), `sessionId`, `version`, `gitBranch`. When `--here` rebases, croam may need to surgically rewrite the `cwd` field on these lines OR (per spec section 11) just let claude resume from the new location with stale historical references. Phase 8 verifies which behavior claude actually enforces; default assumption is no enforcement.

Header line (top of file) is one of the metadata records (`last-prompt` or `permission-mode`), not a system record with `cwd`. The `cwd` field appears on conversation entries themselves. So `--here` rewrite, if needed, would target every conversation line -- a heavier operation than the spec assumed. Phase 8 will measure this against the dummy session.

### Encoded-cwd convention

**Format**: each `/` and each leading `.` in a path component becomes `-`. Concretely:

- `/home/tunc/Programs/croam` -> `-home-tunc-Programs-croam`
- `/tmp/croam-e2e` -> `-tmp-croam-e2e` (existing `-` in `croam-e2e` stays as-is)
- `/home/tunc/.claude` -> `-home-tunc--claude` (the leading `.` of `.claude` becomes `-`, and the `/` before it also becomes `-`, hence `--`)
- `/home/tunc/.claude/commands` -> `-home-tunc--claude-commands`

**Decoding is lossy** when the original path contains `-`. E.g., `-home-tunc-foo-bar` could decode to `/home/tunc/foo/bar` OR `/home/tunc/foo-bar` OR `/home/tunc-foo-bar` etc. The decoder MUST probe the filesystem to disambiguate -- generate candidate parses, accept the one that exists. If multiple exist, prefer the longer match (longest-prefix wins) or escalate to user prompt.

Phase 2's `decode_cwd()` implements this via filesystem probe with the host's home as a hint (we know `/home/tunc/...` is more likely than `/home-tunc/...` in practice).

This is a critical correction to the spec section 11 which said "slashes to dashes; verify exact escape rules from claude source during implementation." The empirical answer is: dots also become dashes, and decoding is lossy.

---

## Dependencies & Integration Points

### Within-project dependencies

- `cli.py` <- everything (it imports each command module)
- `picker.py` -> `sessions.py`, `ownership.py`, `paths.py`, `hosts.py`
- `commands/attach.py` -> `sessions.py`, `tmux.py`, `ownership.py`, `hosts.py`
- `commands/claim.py` -> `ownership.py`, `hosts.py`, `paths.py`
- `commands/fork.py` -> `ownership.py`, `paths.py`, `sessions.py`
- `doctor.py` -> almost everything (it's the cross-cutting integration test)
- `log.py` <- imported by every module that logs
- `errors.py` <- imported anywhere errors are raised
- `config.py` <- imported by `cli.py` and any module that needs config (but only via parameters, not direct import)

### External tool dependencies (must be on PATH at runtime)

- `fzf` (>= 0.55.0 for `transform-header`, `become`, `select`/`deselect` events)
- `tmux` (>= 3.0)
- `ssh` (any reasonable OpenSSH; uses `~/.ssh/config`)
- `claude` (the wrapped CLI; renamed to `claude-real` during shim install per spec section 8)

### Python dependencies

- `typer >= 0.21.0` (CLI framework)
- `loguru >= 0.7.3` (logging)
- Stdlib: `tomllib` (config), `json` (state files), `subprocess`, `pathlib`, `concurrent.futures`, `uuid`, `datetime`, `enum`

### Dev dependencies (under `[dependency-groups].dev`)

- `pytest >= 8.0`
- `pytest-cov` (coverage)
- `ruff >= 0.6` (linting + formatting)
- `pyright >= 1.1.380` (static type checking)

---

## Environment & Configuration

### Build / install

- `uv sync` -- installs from `uv.lock` into `.venv`
- `uv add <pkg>` -- add runtime dep
- `uv add --dev <pkg>` -- add dev dep
- `uv run <cmd>` -- run inside venv without activating
- `uv tool install --editable .` -- global install of `croam` from source (preferred over `pipx`)
- `pipx install -e .` -- alternate global install (also works)

### Runtime config

`~/.config/croam/config.toml`. Schema documented in `docs/specs/2026-04-30-croam-design.md` section 10. Phase 2 implements the loader. First-run bootstrap by `croam doctor`.

### Test environment

- pytest discovers tests under `tests/`
- `tests/conftest.py` (Phase 1) sets up:
  - `home` fixture: `tmp_path / "home"` with fake `~/.claude/projects/`, `~/.claude/sessions/`, `~/.config/croam/`, `~/.local/share/croam/`, `~/.local/state/croam/`
  - `tmux_socket` fixture: `tmp_path / "tmux.sock"` (private to the test)
  - `ssh_shim` fixture: temp dir prepended to `PATH` containing a fake `ssh` script that emits canned output keyed off argv
  - `e2e_dummy` fixture: gated on `CROAM_E2E=1` env var; provides the path to the real dummy session at `/tmp/croam-e2e/` and the captured sid `[DUMMY_SID]`
  - **Conftest guard**: a `pytest_runtest_call` hookwrapper that checks `os.environ["HOME"]` starts with `/tmp/` (i.e., HOME has been redirected) UNLESS `CROAM_E2E=1` is set. Fires after all fixture setup, so the `home` fixture redirects before the guard checks. Prevents accidental contamination of the user's real `~/.claude` if a test forgets to use the `home` fixture.

### Logging

- `loguru` configured by `src/croam/log.py:configure(level, log_file)`
- Default: WARNING+ to stderr, no file
- `--debug` flag at CLI level: DEBUG+ to stderr, JSON-serialized DEBUG+ to `~/.local/state/croam/croam.log` (rotated at 10MB, retain 5)
- Tests redirect the log_file to `tmp_path` via the `home` fixture

---

## External Services & APIs

croam itself does not consume any external HTTP APIs. All "external" interactions are with local CLI tools and the filesystem:

- **claude-code** (https://docs.anthropic.com/en/docs/claude-code) -- the wrapped CLI. We read its data layout (`~/.claude/projects/`, `~/.claude/sessions/`) but never make API calls. The data layout was empirically captured from the dummy session at `/tmp/croam-e2e/` (sid `[DUMMY_SID]`) on 2026-04-30 against claude 2.1.123. See "Data Models" above.
- **tmux** (subprocess) -- ancient and stable; commands `new-session -d -s <name>`, `attach -t <name>`, `attach -r -t <name>`, `has-session -t <name>`, `kill-session -t <name>`, `ls -F <fmt>`. Used in Phase 5.
- **ssh** (subprocess) -- OpenSSH client; flags `-o ConnectTimeout=N -o BatchMode=yes -o StrictHostKeyChecking=no`. Honors `~/.ssh/config`. Used in Phase 3 (probes), Phase 7 (recursion to remote attach), Phase 8 (claim handshake), Phase 9 (`--emit-state` fanout).
- **fzf** (subprocess) -- interactive picker. Phase 6 wraps it. See research notes in Phase 6 plan for exact flags and version requirements.
- **syncthing** -- not directly used. We only read the filesystem under the user-configured `state_root`. Conflict files (`*.sync-conflict-*`) are detected by Phase 9.

For full research notes on `typer`, `loguru`, `uv`, and `fzf`, see the "Technical Reference" section of the relevant phase plans (Phase 1: uv + loguru; Phase 6: typer + fzf).

---

## Testing Tier Strategy

Two tiers, gated by `CROAM_E2E` env var:

### Tier 1 (default): synthetic fixtures, never touch real services

- Pytest fixture redirects HOME to `tmp_path`; populates fake `~/.claude/projects/`, `~/.claude/sessions/`, fake syncthing share, fake `~/.config/croam/config.toml`.
- Tmux tests use `tmux -S <tmp_path>/tmux.sock` -- a private socket; the real tmux server is invisible.
- SSH tests use a subprocess shim on PATH that emits canned output keyed off argv. The real `ssh` is never invoked.
- `subprocess` calls go through the `croam.proc.run()` wrapper (Phase 1) which can be monkeypatched per-test if needed.
- The autouse conftest guard refuses to run if HOME is the user's real home dir, unless `CROAM_E2E=1` is set.
- Goal: hundreds of tests, fully deterministic, runs in seconds.

### Tier 2 (`CROAM_E2E=1`): one real disposable claude session

- Path: `/tmp/croam-e2e/`
- sid: `[DUMMY_SID]` (captured 2026-04-30, claude 2.1.123)
- Read-only by default. Tests that need to mutate the dummy copy it to a `tmp_path`-rooted clone first.
- Used to verify:
  - Real encoded-cwd format matches what `paths.encode_cwd` produces
  - Real `~/.claude/sessions/*.json` schema matches our `ClaudeSession` dataclass
  - `claude --resume <sid>` actually resumes (not strict on cwd, per spec assumption)
  - `--here` cwd-rebase works against a real `claude --resume`
- Tier 2 tests run only in CI or on explicit opt-in. Pre-commit hooks run only Tier 1.

---

## Notes for Future Phases

- **Phase 1**: must establish the conftest guard. If you forget it, every subsequent phase risks corrupting the user's real `~/.claude`.
- **Phase 2**: when implementing `decode_cwd`, don't try to invert `encode_cwd` algebraically -- it is lossy. Probe the filesystem. Also: `tests/_helpers/synth_jsonl.py` has a standalone `_encode_cwd` copy. Phase 2's `test_paths.py` should verify `paths.encode_cwd` matches `synth_jsonl._encode_cwd` for representative paths. Do NOT replace synth_jsonl's copy with an import from `src/croam/paths.py` -- the helper stays dependency-free.
- **Phase 3**: the join between `~/.claude/projects/<encoded>/<sid>.jsonl` and `~/.claude/sessions/<PID>.json` is by `sessionId`. Multiple PIDs can share a sessionId (rare; multiple resumes). Pick the one with the highest `updatedAt`.
- **Phase 5**: tests must always pass an explicit socket via `-S` to keep tmux operations isolated.
- **Phase 6**: picker rows have hidden filter columns (1, 3, 4, 5) that `--with-nth=2,6,7,8,9` excludes from display but fzf still searches. Use `$FZF_SELECT_COUNT` (NOT `FZF_SELECTED_COUNT` -- the manpage spells it without the ED) for the multi-select header transform.
- **Phase 7**: recursion guard: when `croam attach <sid>` SSHes to the owner, it invokes `croam attach <sid> --here-on-owner`. The remote side honors `--here-on-owner` by NEVER recursing further (treats the session as local to itself). Without the guard, two unreachable hosts could ping-pong forever.
- **Phase 8**: ssh-strict claim verification: before writing the assertion, SSH to every reachable peer with `croam --emit-state`, merge with local view, proceed only if the merge agrees the transition is legal. Race window is the gap between "merge agrees" and "we wrote the assertion + syncthing replicated it." Acknowledged in the spec.
- **Phase 9**: syncthing conflict file detection -- glob for `*.sync-conflict-*` under `state_root` and surface as orphans.
- **Phase 10**: integration tests use a synthetic two-host fixture (just two `tmp_path`-rooted state_roots and an SSH shim that pretends to be the peer). Avoid spinning up real second-host VMs.
