# Codebase Context

> **Living document** -- each phase updates this with new discoveries and changes.
> Read this before exploring the codebase. It may already have what you need.
>
> Last updated by: Phase 0 - Initial Setup (2026-04-30)

---

## Architecture Overview

croam is a Python 3.11+ CLI built around three orthogonal concerns:

- **Data layer**: per-host JSON state files (`ownership.json`, `lineage.json`, `host-cache.json`) under `<state_root>/<HOSTNAME>/`, plus claude-code's native session metadata (`~/.claude/sessions/<PID>.json`) and conversation transcripts (`~/.claude/projects/<encoded-cwd>/<sid>.jsonl`).
- **Discovery layer**: SSH probes (parallel, 2s timeout, BatchMode), syncthing mirror reads (filesystem-only -- no syncthing API), or both (hybrid mode).
- **Presentation layer**: typer-based verb dispatcher, fzf-based interactive picker, tmux subprocess control for session attach/peek.

The shim is a separate concern: a thin wrapper around `claude` invoked as `croam launch` (or via the user's `claude` alias) that decides whether to launch inside a tmux session named `claude-<sid>`.

This is a greenfield project. The full design lives at `docs/specs/2026-04-30-croam-design.md`. As of this writing, no Python code exists -- only the spec and these agent docs. Phase 1 establishes the project skeleton (pyproject.toml, src/croam/ tree, test harness, logging).

---

## Key Files & Modules

> Will be populated as phases create them. Phase 1 adds `pyproject.toml`, `src/croam/`, `tests/conftest.py`. Subsequent phases add module files.

| File Path | Purpose | Notes |
|-----------|---------|-------|
| `docs/specs/2026-04-30-croam-design.md` | Original design spec, sections 1-16 | Read for big-picture intent. Do NOT modify. |
| `docs/agent/project-start/PROJECT_PLAN.md` | Phase overview, architecture, cross-cutting concerns | Read once at the start of a phase. |
| `docs/agent/project-start/FUNCTIONAL_QA_STRATEGY.md` | Surfaces, user loops, anti-patterns, harness deliverables | Read in full when planning Functional QA checks. |
| `pyproject.toml` | Project metadata, dependencies, console-script entry | Created in Phase 1. |
| `src/croam/__init__.py` | Package marker | Created in Phase 1. |
| `src/croam/cli.py` | typer entry point (`app`); `croam.cli:app` is the console script | Created in Phase 6. |
| `src/croam/log.py` | `configure(level, log_file)` for loguru | Created in Phase 1. |
| `src/croam/config.py` | TOML config loader, `Config` dataclass | Created in Phase 2. |
| `src/croam/paths.py` | cwd normalization, encoded-cwd encode/decode | Created in Phase 2. |
| `src/croam/sessions.py` | Discover claude's `~/.claude/{projects,sessions}` and join with tmux | Created in Phase 3. |
| `src/croam/hosts.py` | SSH reachability fanout, `--emit-state` over SSH | Created in Phase 3. |
| `src/croam/ownership.py` | per-host assertion read/write/merge/flatten + lineage | Created in Phase 4. |
| `src/croam/tmux.py` | tmux subprocess wrappers (new-session, attach, has-session, kill-session) | Created in Phase 5. |
| `src/croam/shim.py` | Decide whether to wrap `claude` in tmux | Created in Phase 5. |
| `src/croam/picker.py` | fzf orchestration, row layout, multi-select intersection | Created in Phase 6. |
| `src/croam/sync.py` | syncthing mirror access (read-only filesystem); conflict file detection | Created in Phase 9. |
| `src/croam/doctor.py` | Diagnostics: config + SSH + syncthing + ownership consistency | Created in Phase 9. |
| `src/croam/errors.py` | `CroamError` + subclasses | Created in Phase 1. |
| `tests/conftest.py` | HOME redirect, fake `~/.claude`, private tmux socket, SSH shim, dummy session loader | Created in Phase 1. |
| `tests/fixtures/` | Synthetic session JSONLs, ownership.json snapshots, sample TOML configs | Created across Phase 1, 4, 7. |

---

## Important APIs & Interfaces

> Will be populated as phases ship them. Documenting key signatures here saves future agents from re-reading source files.

### Phase 1 deliverables (placeholder signatures, finalized in Phase 1)

```python
# src/croam/log.py
def configure(level: str = "INFO", log_file: Path | None = None, debug: bool = False) -> None: ...

# src/croam/errors.py
class CroamError(Exception): ...
class ConfigError(CroamError): ...
class SshError(CroamError): ...
class OwnershipConflict(CroamError): ...
class TmuxError(CroamError): ...
class SessionNotFound(CroamError): ...
class OrphanRefused(CroamError): ...
```

### Phase 2 (paths and config)

```python
# src/croam/paths.py
def encode_cwd(absolute_cwd: str | Path) -> str:
    """Convert /tmp/croam-e2e -> -tmp-croam-e2e (each / and . -> -, applied per-segment).
    See 'Encoded-cwd convention' below for the exact rules and the lossy-decode caveat.
    """

def decode_cwd(encoded: str, host_home: Path | None = None) -> Path:
    """Best-effort decode. Probes the filesystem when ambiguous (paths containing '-')."""

def normalize_cwd(absolute_cwd: Path, host_home: Path) -> str:
    """Return ~/Programs/foo if cwd is under host_home; absolute string otherwise."""

# src/croam/config.py
@dataclass(frozen=True)
class Config:
    self_hostname: str
    hosts: dict[str, HostEntry]
    state_root: Path
    discovery_mode: Literal["syncthing", "ssh", "hybrid"]
    claim_verify: Literal["local", "ssh-strict"]
    picker_default_filter: Literal["exact-pwd", "project-root"]
    picker_last_window_days: int
    shim_enabled: bool
    shim_opt_out_env: str

def load_config(path: Path = Path("~/.config/croam/config.toml").expanduser()) -> Config: ...
```

### Phase 3 (sessions and host probes)

```python
# src/croam/sessions.py
@dataclass(frozen=True)
class ClaudeSession:
    sid: str
    cwd: Path
    transcript_path: Path
    pid: int | None      # None if not currently running on this host
    status: Literal["idle", "busy"] | None  # None if not currently running
    started_at: int | None  # ms-epoch
    updated_at: int | None  # ms-epoch
    name: str | None      # claude's autoname or user /rename
    version: str | None   # e.g. "2.1.123"

def discover_local_sessions(home: Path) -> list[ClaudeSession]:
    """Scan ~/.claude/projects/* for transcripts, join with ~/.claude/sessions/*.json by sid."""

# src/croam/hosts.py
@dataclass(frozen=True)
class HostStatus:
    name: str
    reachable: bool
    last_probed: datetime
    error: str | None  # populated when not reachable

def probe_reachability(hosts: list[str], timeout_s: float = 2.0) -> dict[str, HostStatus]:
    """Parallel SSH probes via ThreadPoolExecutor."""

def emit_state(home: Path, state_root: Path) -> dict:
    """Build the JSON payload for `croam --emit-state` (hidden subcommand)."""
```

### Phase 4 (ownership)

```python
# src/croam/ownership.py
@dataclass(frozen=True)
class Assertion:
    sid: str
    owner: str
    asserted_at: datetime
    action: Literal["create", "claim", "release"]
    cwd_normalized: str
    previous_owner: str | None  # for claim only

def read_local_assertions(state_root: Path, hostname: str) -> dict[str, Assertion]: ...
def merge_assertions(per_host: dict[str, dict[str, Assertion]]) -> dict[str, Assertion]:
    """Most-recent-asserted_at wins per sid."""
def flatten_local(state_root: Path, hostname: str, merged: dict[str, Assertion]) -> None:
    """Rewrite our own ownership.json to keep only entries we currently own."""
```

### Phase 5 (tmux & shim)

```python
# src/croam/tmux.py
def has_session(sock: Path | None, name: str) -> bool: ...
def new_session_detached(sock: Path | None, name: str, command: list[str], env: dict[str, str] | None = None) -> None: ...
def attach(sock: Path | None, name: str, read_only: bool = False) -> int: ...  # exec, returns exit code
def kill_session(sock: Path | None, name: str) -> None: ...
def list_sessions(sock: Path | None) -> list[str]: ...

# src/croam/shim.py
def should_wrap(argv: list[str], env: dict[str, str], stdin_isatty: bool) -> bool: ...
def derive_sid(argv: list[str], env: dict[str, str]) -> str:
    """Resume sid if --resume <sid> is in argv; else generate a new uuid4."""
```

### Phase 6 (picker & CLI dispatcher)

```python
# src/croam/cli.py
import typer
app = typer.Typer(name="croam", no_args_is_help=False, pretty_exceptions_enable=False, add_completion=False)

# src/croam/picker.py
@dataclass(frozen=True)
class PickerRow:
    sid: str
    glyph: str           # "o" or "O"
    status_word: str
    reach_word: str
    cwd_word: str        # "missing-cwd" or "present"
    host: str
    last: str
    cwd_display: str
    name: str

def render_rows(sessions: list[ClaudeSession], assertions: dict[str, Assertion], host_status: dict[str, HostStatus], pwd: Path) -> list[PickerRow]: ...
def launch_picker(rows: list[PickerRow], filter_pwd: Path | None) -> tuple[str | None, list[PickerRow]]:
    """Returns (expect-key or None, selected rows). Empty key means plain Enter."""
```

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
  - **Conftest guard**: an autouse fixture that asserts `os.environ["HOME"] != Path.home()` (i.e., HOME has been redirected) UNLESS `CROAM_E2E=1` is set. This prevents accidental contamination of the user's real `~/.claude` if a test forgets to use the `home` fixture.

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
- **Phase 2**: when implementing `decode_cwd`, don't try to invert `encode_cwd` algebraically -- it is lossy. Probe the filesystem.
- **Phase 3**: the join between `~/.claude/projects/<encoded>/<sid>.jsonl` and `~/.claude/sessions/<PID>.json` is by `sessionId`. Multiple PIDs can share a sessionId (rare; multiple resumes). Pick the one with the highest `updatedAt`.
- **Phase 5**: tests must always pass an explicit socket via `-S` to keep tmux operations isolated.
- **Phase 6**: picker rows have hidden filter columns (1, 3, 4, 5) that `--with-nth=2,6,7,8,9` excludes from display but fzf still searches. Use `$FZF_SELECT_COUNT` (NOT `FZF_SELECTED_COUNT` -- the manpage spells it without the ED) for the multi-select header transform.
- **Phase 7**: recursion guard: when `croam attach <sid>` SSHes to the owner, it invokes `croam attach <sid> --here-on-owner`. The remote side honors `--here-on-owner` by NEVER recursing further (treats the session as local to itself). Without the guard, two unreachable hosts could ping-pong forever.
- **Phase 8**: ssh-strict claim verification: before writing the assertion, SSH to every reachable peer with `croam --emit-state`, merge with local view, proceed only if the merge agrees the transition is legal. Race window is the gap between "merge agrees" and "we wrote the assertion + syncthing replicated it." Acknowledged in the spec.
- **Phase 9**: syncthing conflict file detection -- glob for `*.sync-conflict-*` under `state_root` and surface as orphans.
- **Phase 10**: integration tests use a synthetic two-host fixture (just two `tmp_path`-rooted state_roots and an SSH shim that pretends to be the peer). Avoid spinning up real second-host VMs.
