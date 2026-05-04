# croam - Project Plan

**Feature/Initiative**: project-start
**Type**: New Project (greenfield)
**Created**: 2026-04-30
**Estimated Total Phases**: 11

---

## Project Location

**IMPORTANT: All paths in this document are relative to the project root.**

- **Project Root**: `/home/tunc/Sync/Programs/croam`
- **Verify with**: `pwd` -> should output `/home/tunc/Sync/Programs/croam`

When you see a path like `src/croam/cli.py`, it means `/home/tunc/Sync/Programs/croam/src/croam/cli.py`

---

## Project Overview

### Purpose

croam unifies claude-code session discovery, attachment, ownership transfer, and branching across all of a user's hosts (e.g., STORMTREE at home, VICAR at work, CORPSEFIRE on phone). It uses SSH for live remote access and optional syncthing for offline-capable mirroring. It also obsoletes `cctakeover` by making every claude session run inside a tmux session named for its UUID.

The full design lives at `docs/specs/2026-04-30-croam-design.md`.

### Scope

**In Scope (v1)**:

- `croam`, `croam ls`, `croam attach`, `croam peek`, `croam claim`, `croam fork`, `croam launch`, `croam doctor` verbs
- fzf-based interactive picker scoped to `$PWD` by default, with multi-select and adaptive action keybindings
- Always-tmux claude shim with a predictable `claude-<sid>` session name
- Per-host ownership assertions with read-time merge (most-recent-`asserted_at` wins) and flatten-on-write
- Cross-host SSH fanout with reachability probes (ConnectTimeout=2, BatchMode=yes)
- Three discovery modes: `syncthing`, `ssh`, `hybrid` -- selectable via `~/.config/croam/config.toml`
- Conflict reconciliation (fork-or-discard) when local has unsynced post-claim writes
- `--here` override for cwd-mismatched claim/fork, with surgical JSONL header rewrite if claude enforces recorded cwd
- Path normalization (home-rooted `~/...` form) and cross-host translation
- Orphan handling (JSONL with no backing assertion: hidden by default, `--orphans` filter, fork-only)
- Conflict file detection (`*.sync-conflict-*` from syncthing)
- Comprehensive test suite (pytest) with synthetic fixtures and opt-in real-claude E2E tests

**Out of Scope (v1)**:

- Live status updates in picker (Ctrl-R only; manual refresh)
- Auto-clone / auto-mkdir of missing project dirs
- Full-text search over JSONL (basic substring only)
- Remote autoname propagation
- Web UI / HTTP API
- Mobile (CORPSEFIRE) host integration -- desktop-first, phone visible only if it runs croam
- ccswap unification (separate tool, revisit later)

### Success Criteria

- [ ] Single-host: `croam` shows local sessions in `$PWD` via fzf with documented keybindings
- [ ] Claude shim launches new sessions inside tmux with predictable names; existing sessions reachable via tmux name
- [ ] Two-host: `croam --all` lists sessions from both via SSH; `croam attach <sid>` for remote SSHes and attaches
- [ ] `croam claim` transfers ownership with both hosts' `ownership.json` correct
- [ ] `croam fork` creates branched session with lineage visible in picker
- [ ] Forced claim with origin offline produces correct ownership state on origin's return
- [ ] `croam doctor` reports config sanity, SSH reachability, syncthing health, ownership inconsistencies
- [ ] Test suite covers: ownership merge, path normalization, conflict reconciliation, shim launch decisions, multi-select action filtering
- [ ] Local install via `pipx install -e [PROJECT_ROOT]` works on STORMTREE and VICAR

---

## Architecture Overview

croam is a Python CLI built around three orthogonal concerns: data (per-host JSON state files + claude's native JSONL transcripts), discovery (SSH probes, syncthing mirror reads, or both), and presentation (fzf picker + verb dispatcher). The shim is a separate concern -- a thin wrapper around `claude` that decides whether to launch inside tmux.

### Key Components

1. **CLI dispatcher (`cli.py`)**: typer entry point. Routes verbs to handler modules. Handles global flags (`--all`, `--host`, `--last`, `--orphans`, `--json`).
2. **Picker (`picker.py`)**: fzf orchestration. Builds rows from session+ownership state, manages keybindings via `--bind`/`--expect`, transforms header on multi-select to show action intersection.
3. **Ownership (`ownership.py`)**: per-host assertion read/write/merge. Implements most-recent-`asserted_at`-wins merge and flatten-on-every-run.
4. **Sessions (`sessions.py`)**: discovers claude's native session metadata (`~/.claude/sessions/*.json` keyed by PID) and conversation transcripts (`~/.claude/projects/<encoded-cwd>/<sid>.jsonl`). Joins them by `sessionId` to compute live status and tmux state.
5. **Hosts (`hosts.py`)**: parallel SSH reachability probes (ThreadPoolExecutor), `croam --emit-state` remote invocation, host config parsing.
6. **Sync (`sync.py`)**: read-only access to the syncthing-replicated `state_root`. Detects `*.sync-conflict-*` files. Does NOT manage syncthing itself.
7. **Paths (`paths.py`)**: cwd normalization (home-rooted `~/...` when under origin's `$HOME`, absolute otherwise), encoded-cwd computation (claude's `slash-to-dash` convention), per-host home resolution.
8. **Tmux (`tmux.py`)**: subprocess wrapping `tmux` for `new-session -d -s claude-<sid>`, `attach`, `attach -r` (read-only peek), `has-session`, `kill-session`.
9. **Doctor (`doctor.py`)**: validates config, probes SSH reachability for each configured host, checks syncthing health (mtime freshness on peer subdirs), surfaces ownership inconsistencies.
10. **Shim (`shim.py`)**: detects TTY, in-tmux, and opt-out. Decides whether to `exec_tmux_new(claude-<sid>, ["claude-real", *args])` or pass through.
11. **Config (`config.py`)**: TOML loader. Single read at startup, immutable thereafter.

### Data Flow

```
User runs `croam` in a directory
       |
       v
config.py loads ~/.config/croam/config.toml
       |
       v
hosts.py probes SSH reachability for all configured hosts (parallel)
       |
       v
ownership.py reads all hosts' ownership.json (via syncthing mirror or SSH fanout)
       |
       v
sessions.py reads local ~/.claude/projects + ~/.claude/sessions + tmux ls
       |
       v
ownership.py merges assertions (most-recent-asserted_at wins)
       |
       v
picker.py builds fzf rows (filtered by $PWD by default)
       |
       v
User selects + key -> dispatch to attach/peek/claim/fork
       |
       v
Verb handler runs (may SSH back to owner, claim ownership, copy JSONL, etc.)
```

### Technology Stack

- **Language**: Python 3.11+
- **CLI library**: typer (modern, type-hinted, good UX)
- **Concurrency**: `concurrent.futures.ThreadPoolExecutor` for SSH fanout
- **fzf**: `subprocess.Popen` with `--bind`, `--expect`, `--with-nth`, `--delimiter`
- **SSH**: `subprocess.run` with `~/.ssh/config` (no paramiko -- shell out)
- **Tmux**: `subprocess.run` with the `tmux` binary
- **Syncthing**: read-only filesystem access; no API calls
- **Config**: TOML via stdlib `tomllib`
- **State files**: JSON via stdlib `json`
- **Logging**: `loguru` (stdout for interactive, optional file at `~/.local/state/croam/croam.log`)
- **Testing**: pytest with synthetic fixtures + opt-in real-claude E2E tests
- **Packaging**: pyproject.toml + uv for dev; `pipx install -e [PROJECT_ROOT]` for install

---

## Phase Overview

> **Detailed phase plans are in `phase_plans/PHASE_XX.md`.**
> Only read the plan file for your assigned phase to save context.

| Phase | Name | Objective (one line) | Dependencies |
|-------|------|---------------------|--------------|
| 1 | Foundation: project skeleton, logging, test harness | pyproject + uv + loguru + pytest scaffold + safety guards + dummy-session fixture loader | None |
| 2 | Config & paths | TOML loader, host/storage/discovery/ownership config dataclasses, cwd normalization, encoded-cwd | Phase 1 |
| 3 | Sessions & host probes | `~/.claude/{projects,sessions}` discovery, SSH reachability fanout, host-cache | Phase 1, 2 |
| 4 | Ownership state | per-host `ownership.json` read/write/merge/flatten + lineage.json | Phase 1, 2 |
| 5 | Tmux integration & claude shim | tmux subprocess wrapper, shim detection logic, `croam launch` | Phase 1, 2 |
| 6 | Picker & CLI dispatcher | typer entry, fzf orchestration, row layout, keybindings, multi-select intersection | Phase 1, 2, 3, 4 |
| 7 | Verbs: attach, peek, ls | local + recursive-via-SSH attach, peek live/static, scriptable ls --json | Phase 3, 4, 5, 6 |
| 8 | Verbs: claim, fork (incl. ssh-strict, --here, conflict reconciliation) | claim handshake, fork lineage, ssh-strict verify, --here cwd rebase, fork-or-discard prompt | Phase 4, 7 |
| 9 | Sync mode & doctor | syncthing mirror reading, conflict file detection, doctor diagnostics | Phase 2, 3, 4 |
| 10 | Integration tests round 1 | end-to-end against synthetic two-host fixtures + opt-in real-claude session | Phase 7, 8, 9 |
| 11 | Polish, install, README | pipx install path, README, claude shim alias install, retire cctakeover | Phase 10 |

---

## Phase Dependencies Graph

```
Phase 1 (Foundation)
   |
   +--> Phase 2 (Config & paths)
   |       |
   |       +--> Phase 3 (Sessions & host probes)
   |       |
   |       +--> Phase 4 (Ownership state)
   |       |
   |       +--> Phase 5 (Tmux & shim)
   |
   v
Phase 6 (Picker & CLI dispatcher) <- needs 1, 2, 3, 4
   |
   v
Phase 7 (attach/peek/ls)          <- needs 3, 4, 5, 6
   |
   v
Phase 8 (claim/fork/--here)       <- needs 4, 7
   |
   v
Phase 9 (Sync mode & doctor)      <- needs 2, 3, 4 (independent of 6,7,8 in scope)
   |
   v
Phase 10 (Integration tests)      <- needs 7, 8, 9
   |
   v
Phase 11 (Polish, install, README) <- needs 10
```

Phases 3, 4, 5 depend only on 1+2 and have NO mutual dependencies; they can run in parallel.
Phases 6 and 9 are partially independent: 6 needs the picker layer; 9 needs the discovery layer. But both consume Phase 4's ownership module. They are kept sequential to avoid file contention on shared logging or config code that is still settling.

---

## Cross-Cutting Concerns

### Code Style

- Python 3.11+ syntax (`match`, `|` types, etc. are fine)
- Type hints everywhere; `from __future__ import annotations` at top of every module
- Use `loguru` for logging, never `print()` (except inside fzf row formatting where stdout IS the protocol with fzf)
- Maximum line length: 100 chars
- Public functions get a one-line docstring; complex internals stay uncommented
- Modules under `src/croam/`; tests under `tests/` mirror module names

### Error Handling

- `CroamError(Exception)` base class in `src/croam/errors.py`. Subclasses: `ConfigError`, `SshError`, `OwnershipConflict`, `TmuxError`, `SessionNotFound`, `OrphanRefused`.
- Top-level CLI catches `CroamError`, prints a clean one-liner to stderr, exits non-zero. Unhandled exceptions go through loguru and a backtrace ONLY in `--debug`.
- SSH timeouts are NOT errors -- they are reachability=False signals. `subprocess.run(timeout=...)` + `TimeoutExpired` -> reachability=False.
- Race conditions (e.g., write-vs-flatten on `ownership.json`) handled via `os.replace` atomic rename, never `with open(... 'w')` directly.

### Logging (MANDATORY)

**Logging is required.** Phase 1 must set up logging infrastructure before any other work.

- **Framework**: `loguru` (single import, no boilerplate)
- **Output**: stdout by default at WARNING level; `--debug` flag bumps to DEBUG and tees to `~/.local/state/croam/croam.log`
- **Format**: loguru default `{time:HH:mm:ss} | {level} | {module}:{function} | {message}` (stdout), JSON-encoded structured records to file
- **Levels**: DEBUG for SSH command lines, full ownership merge traces, fzf input streams; INFO for verb start/end; WARNING for unreachable hosts, missing cwds; ERROR for unrecoverable failures
- **What never logs**: claude session JSONL contents (privacy); SSH passphrases (we don't handle them anyway -- BatchMode=yes prevents prompts)
- Phase 1 sets up `src/croam/log.py` with a single `configure(level: str, log_file: Path | None)` function. All other modules use `from loguru import logger`.

### Configuration

- Single TOML file at `~/.config/croam/config.toml`. Created on first run by `croam doctor` if absent.
- Loaded once at startup via `src/croam/config.py:load_config()` -> immutable `Config` dataclass
- Schema validated at load time. Missing required fields -> `ConfigError` with helpful message naming the missing field.
- Path expansions (`~/...` -> `os.path.expanduser`) happen at load time so callers receive absolute paths.

### Testing Strategy

- **Tier 1 (default, fast, safe)**: synthetic fixtures. Pytest fixture redirects `HOME` to `tmp_path`, creates fake `~/.claude/projects/<encoded>/<sid>.jsonl`, fake `~/.claude/sessions/`, fake syncthing share. Tmux tests use `tmux -S /tmp/croam-tests/sock-<pid>` (private socket). SSH tests use a subprocess shim on `PATH` that emits canned output keyed off argv. Hundreds of tests, never touch real services.
- **Tier 2 (opt-in via `CROAM_E2E=1`)**: real disposable claude session at `/tmp/croam-e2e/`. Verifies real JSONL format, real encoded-cwd convention, real `claude --resume` behavior. Read-only access to the dummy; mutation tests copy first.
- **Conftest guard**: refuses to run if `HOME` is not `tmp_path` AND `CROAM_E2E=1` is not set. Prevents accidental contamination of the user's real `~/.claude`.
- **Coverage**: aim for >80% on logic modules (ownership, paths, picker row layout). Subprocess-heavy modules (tmux, hosts, shim) covered via integration tests with the subprocess shim.
- Integration testing: Phase 10 is dedicated to end-to-end coverage across two synthetic hosts.

---

## Integration Points

### Picker <-> Sessions <-> Ownership

Picker calls `sessions.list_local()` and `ownership.merged_view()`, joins them by sid, computes status glyph (`o`/`O` based on host reachability + live process detection). Output rows go to fzf stdin; fzf's chosen sid + `--expect` key returns to the picker which dispatches to the verb handler.

### Verbs <-> Hosts (SSH fanout)

`croam attach` for a remote-owned session SSHes to owner with `croam attach <sid> --here-on-owner` (recursion guard). The remote `croam attach` resolves locally (kill+relaunch in tmux if not already, attach). `croam ls` with `--all` and SSH-only mode SSHes to each reachable peer with `croam --emit-state` to fetch their JSON state.

### Shim <-> Sessions (claude launch)

The shim is `croam launch`. It generates or resumes a sid (parsing argv for `--resume <sid>`), then `exec_tmux_new(claude-<sid>, ["claude-real", *args])`. Subsequent `croam` invocations discover the session by joining `~/.claude/projects/.../<sid>.jsonl` (transcript) with `~/.claude/sessions/<PID>.json` (live process metadata) with `tmux ls` (current attach state).

### Doctor <-> Everything

`croam doctor` exercises every layer once: config load, SSH reachability for all configured hosts, syncthing health (peer subdirs exist + recently mtimed if `sync = true`), ownership consistency (no two hosts claim the same sid with the same `asserted_at`), tmux server liveness, claude binary on `PATH`.

---

## Data Schemas

### Per-host state under `<state_root>/<HOSTNAME>/`

```
<state_root>/                # e.g., ~/Sync/croam (syncthing mode) or ~/.local/share/croam (ssh mode)
  <HOSTNAME>/
    ownership.json           # this host's assertions
    lineage.json             # this host's fork lineage
    host-cache.json          # last-known peer state for offline display
    projects/                # mirror of ~/.claude/projects/ (syncthing mode only)
      <encoded-cwd>/
        <sid>.jsonl
```

### `ownership.json` (per-host, this host's assertions only)

```json
{
  "abc12345-6789-abcd-ef01-23456789abcd": {
    "owner": "stormtree",
    "asserted_at": "2026-04-30T10:00:00Z",
    "action": "create",
    "cwd_normalized": "~/Programs/onlayer-x"
  },
  "def45678-9abc-...": {
    "owner": "stormtree",
    "asserted_at": "2026-04-29T22:30:00Z",
    "action": "claim",
    "previous_owner": "vicar",
    "cwd_normalized": "~/Programs/croam"
  }
}
```

### `lineage.json` (per-host)

```json
{
  "fork-sid-xyz": {"parent_sid": "abc12345-...", "fork_n": 1},
  "fork-sid-uvw": {"parent_sid": "abc12345-...", "fork_n": 2}
}
```

### `host-cache.json` (per-host, peer status snapshot)

```json
{
  "vicar": {"last_reachable": "2026-04-30T08:30:00Z", "last_sync": "2026-04-30T08:31:42Z"},
  "corpsefire": {"last_reachable": "2026-04-29T20:00:00Z", "last_sync": "2026-04-29T20:01:11Z"}
}
```

### `~/.config/croam/config.toml`

See section 10 of `docs/specs/2026-04-30-croam-design.md` for the full schema. Phase 2 implements the loader.

### Claude-native (read-only from croam's perspective)

- `~/.claude/projects/<encoded-cwd>/<sid>.jsonl`: conversation transcript. First few lines are `last-prompt`, `permission-mode`, then conversation entries. `<encoded-cwd>` is the absolute path with `/` replaced by `-` (verified against `/tmp/croam-e2e` -> `-tmp-croam-e2e`).
- `~/.claude/sessions/<PID>.json`: live session metadata, keyed by PID (NOT sid). Schema: `{"pid", "sessionId", "cwd", "startedAt", "procStart", "version", "kind", "entrypoint", "status", "updatedAt"}`. Absent for exited sessions -- this is how croam distinguishes "running" from "archived".

---

## Glossary

**sid**: claude session UUID (e.g., `ff7afd8a-ea17-4183-a131-566e7bcb0758`).
**Owner host**: the host whose JSONL is canonical for a given sid.
**Reachability**: whether `ssh -o ConnectTimeout=2 -o BatchMode=yes HOST true` succeeds right now.
**Living state**: a running `claude` process on a host, optionally attached to tmux.
**Persistent state**: the JSONL transcript bytes -- portable across hosts.
**Encoded-cwd**: the directory naming convention claude uses under `~/.claude/projects/`. Each `/` in the absolute cwd becomes `-`. Example: `/tmp/croam-e2e` -> `-tmp-croam-e2e`.
**state_root**: the configurable path under which croam writes its per-host state. Defaults to `~/.local/share/croam`. Set to a syncthing-replicated path (e.g., `~/Sync/croam`) to enable mirror mode.
**ssh-strict**: `claim_verify` mode that SSHes to every reachable peer before writing a claim assertion to ensure the merge agrees.
**Orphan**: a JSONL transcript with no backing ownership assertion (e.g., from interrupted operations, partial syncs, corrupted state).
**Forced claim**: a claim made when the origin is offline. Copies from local syncthing mirror, writes a "claimed away" marker.
**`--here`**: claim/fork variant that rewrites the session's `cwd_normalized` to `$PWD` and (if claude enforces it) surgically rewrites the JSONL header `cwd` field. Opt-in only.

---

## Future Enhancements

- [ ] Live status updates in picker (Ctrl-R only in v1)
- [ ] Auto-clone / auto-mkdir of missing project dirs on `--here` claim
- [ ] Full-text search over JSONL content
- [ ] Remote autoname propagation
- [ ] Web UI / HTTP API for dashboard view
- [ ] Mobile (CORPSEFIRE) host integration
- [ ] ccswap unification

---

## References

- Full design spec: `docs/specs/2026-04-30-croam-design.md`
- claude-code CLI behavior: observed via dummy session at `/tmp/croam-e2e/` (sid `[DUMMY_SID]`)
- typer docs: https://typer.tiangolo.com/
- fzf bindings: https://github.com/junegunn/fzf#advanced-topics
- loguru: https://github.com/Delgan/loguru

---

**Instructions for Agents**:
1. **First**: Run `pwd` and verify you're in `/home/tunc/Sync/Programs/croam`
2. Read your phase plan from `phase_plans/PHASE_XX.md` (NOT the entire PROJECT_PLAN.md)
3. Check the dependencies to understand what should already exist
4. Follow the detailed requirements exactly
5. Meet all completion criteria before marking phase complete
6. Create your summary in `summaries/PHASE_XX_SUMMARY.md`
7. Update `STATUS.md` when complete

**Remember**: All file paths in this plan are relative to `/home/tunc/Sync/Programs/croam`

**Context Budget Note**: Each phase targets ~120k total tokens (reading + implementation + thinking + output). Phase plans are individual files to minimize reading overhead. If a phase runs out of context, note it in your summary and suggest splitting.
