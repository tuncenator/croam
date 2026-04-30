# Phase 8: Verbs: claim, fork (incl. ssh-strict, --here, conflict reconciliation)

**Feature**: project-start
**Estimated Context Budget**: ~110k tokens

**Difficulty**: hard
**Visual**: no
**Functional**: yes

**Execution Mode**: parallel
**Batch**: 6 (parallel with Phase 9; both depend on prior batches but have no mutual file contention)

---

## Objective

Implement the two write verbs (`claim`, `fork`) and the full machinery surrounding them: the cooperative claim handshake with origin (release on owner, copy JSONL, write claim assertion), `claim_verify="ssh-strict"` cross-peer pre-check, the `--here` cwd rebase (with the surgical JSONL rewrite question resolved empirically against the dummy session), `fork` with lineage tracking, and the loss-reconciliation prompt (fork-or-discard) for sessions that have been outclaimed by a peer.

This is the most coordination-heavy phase in croam. Every other phase has been a unit; this phase wires units together across host boundaries. It also resolves spec section 11/15's open question: "does `claude --resume` enforce the recorded cwd?" -- the answer must be captured empirically and propagated back into `CODEBASE_CONTEXT.md` and `PROJECT_PLAN.md` References.

---

## Deliverables

1. `src/croam/commands/release.py` -- the receiving side of the claim handshake. Implemented FIRST because it sets the contract claim depends on.
2. `src/croam/commands/fork.py` -- self-contained; no SSH coordination.
3. `src/croam/commands/claim.py` -- depends on `release.py` and SSH-strict verification logic.
4. `src/croam/commands/reconcile.py` -- the outclaim detection + fork-or-discard prompt, called from picker startup.
5. `src/croam/snapshots.py` -- snapshot-line-count sidecar (separate `<state_root>/<self>/snapshots.json` file). NOT an extension of the `Assertion` dataclass.
6. Wiring in `src/croam/cli.py` (typer commands `claim`, `fork`) and `src/croam/commands/default.py` (`expect_key in {"c", "C", "f", "F"}` dispatch + reconcile call before picker render).
7. Tests: `tests/test_claim.py`, `tests/test_fork.py`, `tests/test_reconcile.py`, `tests/test_snapshots.py`.
8. Documentation update: `CODEBASE_CONTEXT.md` "Encoded-cwd convention" section AND `PROJECT_PLAN.md` "References"/"Open Questions" with the empirical answer to the cwd-enforcement question.

---

## Detailed Requirements

### Implementation order (mandatory)

Implement and test in this order. Each step's tests must pass before moving to the next:

1. **`src/croam/snapshots.py`** -- the simple sidecar store.
2. **`src/croam/commands/release.py`** -- receiver side. Defines what claim's caller has to invoke.
3. **`src/croam/commands/fork.py`** -- self-contained, no SSH.
4. **`src/croam/commands/claim.py`** -- the full handshake.
5. **`src/croam/commands/reconcile.py`** -- the prompt; needs `fork.run` to invoke.
6. **CLI wiring** in `cli.py` and `commands/default.py`.
7. **The empirical claude-resume test** against `e2e_dummy` (tier 2). This determines whether the surgical JSONL rewrite is actually needed.
8. **Documentation update** in `CODEBASE_CONTEXT.md` + `PROJECT_PLAN.md`.

### File: `src/croam/snapshots.py` (new)

Simple sidecar store. NOT in the `Assertion` dataclass (Phase 4 owns that file; do not edit it).

```python
from __future__ import annotations
from pathlib import Path
import json
import os
import tempfile
from loguru import logger

def _path(state_root: Path, hostname: str) -> Path:
    return state_root / hostname / "snapshots.json"

def read_snapshots(state_root: Path, hostname: str) -> dict[str, int]:
    """Return {sid: line_count} for snapshots taken when this host wrote its assertion.
    Returns {} if file missing. Returns {} and warns if file is malformed (do not raise)."""

def write_snapshot(state_root: Path, hostname: str, sid: str, line_count: int) -> None:
    """Atomic upsert of a single (sid, line_count) entry. Read-modify-write via os.replace.
    Creates the file if missing."""

def remove_snapshot(state_root: Path, hostname: str, sid: str) -> None:
    """Remove the entry for sid, idempotent. Atomic write."""

def count_jsonl_lines(jsonl_path: Path) -> int:
    """Return the number of newline-terminated lines. Returns 0 if file missing.
    Counts via `sum(1 for _ in f)` on the open file. UTF-8 errors are caught and logged;
    returns the line count of valid lines so partial corruption doesn't crash the merge."""
```

Atomic write recipe (re-use Phase 4's pattern):

```python
def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f"{path.name}.tmp.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

When to write a snapshot:

- `claim.run()` writes one for the claimed sid AT THE END (after the local JSONL has been copied into place).
- `fork.run()` writes one for the new fork_sid AT THE END.
- `commands/launch.py` (Phase 5) does NOT need to write one; on `create`, the JSONL starts empty and grows. `reconcile` only triggers when our assertion is stale, and at that point the line count delta is what matters.

### File: `src/croam/commands/release.py` (new)

The receiving side of the handshake. SSHed-to host invokes this when the claimer asks "release sid X to me."

```python
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from loguru import logger
from croam.config import Config
from croam.errors import SessionNotFound, TmuxError
from croam.ownership import (
    Assertion,
    read_local_assertions,
    write_local_assertions,
    flatten_local,
    read_all_assertions,
    merge_assertions,
)
from croam.tmux import has_session, kill_session
from croam.paths import encode_cwd
from croam import snapshots

def run(
    sid: str,
    requester_host: str,
    ctx_obj: dict,
    config: Config,
    home: Path,
    *,
    no_exec: bool = False,
) -> int:
    """Receive a claim handshake on the owner side.

    Steps:
    1. Verify we currently own `sid` (read_local_assertions; if not present, exit 0
       with a log line "release: sid <x> not owned here, no-op" -- idempotent).
    2. Kill `claude-<sid>` tmux session if it exists (use kill_session, idempotent).
    3. Remove our local JSONL at `~/.claude/projects/<encoded-cwd>/<sid>.jsonl`. If
       missing already, log warning, continue.
    4. Replace our ownership.json entry with action="release", asserted_at=now,
       previous_owner=requester_host (the host taking ownership).
    5. flatten_local against the merged view (which now will pick up the
       claim assertion once the claimer writes it; for this call we use the
       merge view EXCLUDING any incoming claim, i.e., just our own state).
    6. Remove snapshots entry for sid (we don't own it anymore).

    Returns 0 on success, non-zero on irrecoverable error.

    With no_exec=True: do NOT actually kill tmux or remove files; return 0
    immediately after logging the planned actions. Used by tests.
    """
```

Edge cases:

- Idempotent: if called twice for the same sid, second call is a no-op.
- If tmux kill fails because the server is dead: log debug, continue.
- If JSONL file is already gone: log warning, continue.
- If our own ownership.json doesn't have `sid`: log "no-op", return 0. (The claimer is asking us to release something we already don't own; harmless.)
- The `cwd_normalized` must be read from our existing assertion BEFORE we overwrite it, so we know which encoded-cwd dir to delete the JSONL from.

### File: `src/croam/commands/fork.py` (new)

Self-contained, no SSH.

```python
def run(
    sid: str,
    ctx_obj: dict,
    config: Config,
    home: Path,
    *,
    here: bool = False,
    no_exec: bool = False,
) -> int:
    """Fork session `sid` into a new sid owned by this host.

    Steps:
    1. Resolve the parent: read local merged assertions; fail with SessionNotFound
       if `sid` is not in the merged view AND we don't have a local JSONL with that
       sid (orphan path: allow fork-from-orphan if --orphans was passed via ctx_obj
       or if a local JSONL exists for sid).
    2. Generate fork_sid = str(uuid.uuid4()).
    3. Determine source path:
       - If parent is locally owned: ~/.claude/projects/<encoded-parent-cwd>/<sid>.jsonl
       - If parent is remotely owned but we have a syncthing mirror copy: read from
         <state_root>/<owner>/projects/<encoded-parent-cwd>/<sid>.jsonl
       - Else fail SessionNotFound("source JSONL not accessible")
    4. Determine destination cwd:
       - here=False: use parent's cwd_normalized resolved against our $HOME
       - here=True: use Path.cwd()
    5. Determine destination path:
       ~/.claude/projects/<encoded-dest-cwd>/<fork_sid>.jsonl
    6. Copy: read source bytes, validate every line parses as JSON (drop trailing
       partial line if it doesn't parse, per spec section 13's atomicity rule),
       write to a temp file in the same destination dir, fsync, os.replace into
       place.
    7. If here=True AND CROAM_CLAUDE_ENFORCES_CWD=1 in env (or the constant set
       at module load -- see "claude cwd enforcement" below): surgically rewrite
       the `cwd` field on every conversation entry (lines 3+) and the header
       lines if applicable. See "Surgical JSONL rewrite" below for the algorithm.
    8. add_lineage(state_root, hostname, fork_sid, sid) -> fork_n.
    9. Write a new Assertion: action="create", owner=self, asserted_at=now,
       cwd_normalized=normalize_cwd(destination_cwd, host_home),
       previous_owner=None.
    10. write_local_assertions (Phase 4 atomic).
    11. snapshots.write_snapshot(state_root, hostname, fork_sid,
        count_jsonl_lines(dest_path)).

    With no_exec=True: skip steps 6 (file write), 7, 8 (the lineage write), 9-11.
    Return a JSON-serializable plan dict via `typer.echo(json.dumps(plan))` and
    exit 0.

    Returns 0 on success.
    """
```

Edge cases:

- Parent has no local JSONL but mirror exists: fork uses mirror.
- Parent is orphan (no assertion, has JSONL): allowed only if ctx_obj.get("orphans") is True; otherwise refuse with `OrphanRefused("fork an orphan with --orphans")`.
- Destination dir doesn't exist: create it (`mkdir -p`).
- here=True but Path.cwd() does not exist: should never happen (we're running there), but if `os.getcwd()` raises (deleted dir), surface a `CroamError("cwd does not exist")`.
- Empty JSONL: still copy, still create entry. fork_n still increments.

### File: `src/croam/commands/claim.py` (new)

The most complex module in this phase. State machine:

```
S0: Determine current owner via local merged view
    |
    +--> S1: Already self-owned? -> log "already owned by self", return 0 (idempotent)
    |
    +--> S2: ssh-strict pre-verify (if claim_verify == "ssh-strict")
    |        |
    |        +--> Race: peer's later assertion shows up in fanout -> raise OwnershipConflict
    |        +--> Pass: continue to S3
    |
    +--> S3: Owner reachable?
              |
              +--> YES: cooperative handshake (S3a)
              |          1. SSH owner: croam release <sid> --requester=<self>
              |          2. Wait for completion (returncode 0)
              |          3. Copy JSONL via SSH cat (or scp); validate trailing JSON
              |          4. Continue to S4
              |
              +--> NO: forced claim (S3b)
                       1. Prompt confirmation (unless --force)
                       2. Read JSONL from <state_root>/<owner>/projects/<encoded>/<sid>.jsonl
                          (the syncthing mirror)
                       3. If mirror missing: SshError("origin unreachable and no
                          mirror present; cannot claim")
                       4. Continue to S4
    |
    +--> S4: Write OUR claim assertion to ownership.json (atomic)
             - asserted_at=now (UTC), action="claim", previous_owner=<owner>,
               cwd_normalized=normalize_cwd($PWD if here else parent.cwd_normalized, self_home)
             - WARNING: between S2's pass and S4's write there is a race window.
               This is acknowledged by spec section 7 and tested explicitly. See
               "Race window" below.
    |
    +--> S5: With here=True AND CROAM_CLAUDE_ENFORCES_CWD=1: surgical JSONL rewrite
    |
    +--> S6: flatten_local + snapshots.write_snapshot(self, sid, count(local_jsonl))
    |
    +--> Return 0
```

```python
def run(
    sid: str,
    ctx_obj: dict,
    config: Config,
    home: Path,
    *,
    here: bool = False,
    force: bool = False,
    no_exec: bool = False,
) -> int:
    """Transfer ownership of sid to this host. See state machine above.

    Args:
        force: skip the confirmation prompt for forced claim (origin unreachable).
        no_exec: emit planned argv for SSH/scp/file ops as JSON; do not modify state.

    Raises:
        OwnershipConflict: ssh-strict pre-verify rejected the transition.
        SshError: origin unreachable AND no mirror data; or scp/release SSH failed.
        SessionNotFound: sid is not in any merged view.
    """
```

#### State details

**S0: ownership lookup.** `owner_now = merged.get(sid)` from local-only `read_all_assertions`. If `owner_now is None`: `SessionNotFound`.

**S1: self-owned shortcut.** `if owner_now.owner == config.self_hostname: logger.info("claim: sid {} already owned by self, no-op", sid); return 0`.

**S2: ssh-strict pre-verify.** Only when `config.claim_verify == "ssh-strict"`.

```python
peer_states = {}  # {hostname: {"ownership": dict, "lineage": dict, ...}}
reachable = probe_reachability(list(config.hosts.keys()))
for peer_name, status in reachable.items():
    if peer_name == config.self_hostname:
        continue
    if status.reachable:
        # Live SSH
        result = proc.run(
            ["ssh", "-o", "ConnectTimeout=2", "-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=no", config.hosts[peer_name].ssh,
             "croam", "emit-state"],
            timeout=10.0,
        )
        if result.returncode == 0:
            peer_states[peer_name] = json.loads(result.stdout)
    elif config.discovery_mode in ("syncthing", "hybrid") and config.hosts[peer_name].sync:
        # Fall back to mirror
        peer_states[peer_name] = read_peer_state_from_mirror(
            config.state_root, peer_name
        )
    # else: gap; log warning
```

After fanout, re-merge:

```python
all_assertions = read_all_assertions(config.state_root, peer_states=peer_states)
re_merged = merge_assertions(all_assertions)
re_owner = re_merged.get(sid)
if re_owner is None:
    raise SessionNotFound(...)
if re_owner.owner == config.self_hostname:
    logger.info("...")
    return 0
# legality: are we transitioning from re_owner.owner to self? (any current owner -> us is legal)
# The check that fails: peer state shows OUR previous claim was already superseded
# by another host's later claim. Detect: re_owner.asserted_at > our_planned_asserted_at?
# Since our planned asserted_at is `now`, this is impossible by definition.
# What CAN fail: peer's state shows a claim DIFFERENT from local view such that
# the assumed previous_owner is wrong.
if re_owner.owner != owner_now.owner:
    raise OwnershipConflict(
        f"ssh-strict: local view says owner is {owner_now.owner}, "
        f"peer view says {re_owner.owner} (later assertion); refusing claim. "
        f"Re-run after running `croam` to refresh state."
    )
```

**S3a: cooperative handshake (owner reachable).**

```python
release_argv = [
    "ssh", "-o", "ConnectTimeout=2", "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    config.hosts[owner_now.owner].ssh,
    "croam", "release", sid, f"--requester={config.self_hostname}",
]
result = proc.run(release_argv, timeout=30.0)
if result.returncode != 0:
    raise SshError(f"release failed on {owner_now.owner}: {result.stderr}")
```

**Copy JSONL.** Use `ssh ... cat <path>` and write locally. Validate trailing JSON before atomic rename.

```python
remote_path = (
    Path(owner_home) / ".claude" / "projects" /
    encode_cwd(owner_cwd_absolute) / f"{sid}.jsonl"
)
# owner_home: from config.hosts[owner].home, default same as our home
cat_argv = [
    "ssh", "-o", "ConnectTimeout=2", "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    config.hosts[owner_now.owner].ssh,
    "cat", str(remote_path),
]
result = proc.run(cat_argv, timeout=120.0)
# Validate trailing line parses as JSON; if not, drop it (spec section 13 atomicity)
content = _trim_trailing_partial_json(result.stdout)
# Write atomically to local destination
local_dest = (
    home / ".claude" / "projects" /
    encode_cwd(target_cwd_absolute) / f"{sid}.jsonl"
)
_atomic_write_text(local_dest, content)
```

**S3b: forced claim (owner unreachable).**

```python
if not force:
    # Use input(), not typer.prompt -- so monkeypatch.setattr("builtins.input", ...) works
    response = input(
        f"Origin {owner_now.owner} is unreachable. "
        f"Forced claim copies from local syncthing mirror; if {owner_now.owner} "
        f"had unsynced writes after last sync, you may lose data. Proceed? [y/N] "
    ).strip().lower()
    if response not in ("y", "yes"):
        logger.info("claim: user declined forced claim")
        return 1

# Read from mirror
mirror_path = (
    config.state_root / owner_now.owner / "projects" /
    encode_cwd(owner_cwd_absolute) / f"{sid}.jsonl"
)
if not mirror_path.exists():
    raise SshError(
        f"origin {owner_now.owner} unreachable and no mirror at {mirror_path}; "
        f"cannot claim"
    )
content = mirror_path.read_text(encoding="utf-8", errors="replace")
content = _trim_trailing_partial_json(content)
local_dest = ...
_atomic_write_text(local_dest, content)
```

**S4: write claim assertion.**

```python
new_assertion = Assertion(
    sid=sid,
    owner=config.self_hostname,
    asserted_at=datetime.now(timezone.utc),
    action="claim",
    cwd_normalized=normalize_cwd(target_cwd, home),
    previous_owner=owner_now.owner,
)
local = read_local_assertions(config.state_root, config.self_hostname)
local[sid] = new_assertion
write_local_assertions(config.state_root, config.self_hostname, local)
```

**S5: --here surgical rewrite.** See "Surgical JSONL rewrite" below.

**S6: flatten + snapshot.**

```python
re_merged_after = merge_assertions(read_all_assertions(config.state_root))
flatten_local(config.state_root, config.self_hostname, re_merged_after)
line_count = snapshots.count_jsonl_lines(local_dest)
snapshots.write_snapshot(config.state_root, config.self_hostname, sid, line_count)
```

#### Race window (acknowledged)

Between S2's pass and S4's write, a peer could write a conflicting claim to its own ownership.json. We do NOT defend against this -- it requires a distributed lock we don't have. The race resolves on next read via fork-or-discard. Document this in `test_claim_ssh_strict_race_window_acknowledged`.

#### Surgical JSONL rewrite

Pre-Phase 8 assumption: claude does NOT enforce recorded cwd on resume. Phase 8's job is to verify this empirically. Two paths:

**Path A: claude does NOT enforce cwd (expected).** No rewrite needed. The `--here` rebase only updates `cwd_normalized` in our ownership.json and writes the JSONL into the encoded-$PWD directory. JSONL bytes are unchanged.

**Path B: claude DOES enforce cwd.** Per-line rewrite. Algorithm:

```python
def _surgical_rewrite_cwd(jsonl_path: Path, new_cwd_absolute: str) -> None:
    """Rewrite the `cwd` field on every conversation entry that has one.
    Atomic: write to .tmp then os.replace.

    Lines without a cwd field (e.g. `last-prompt`, `permission-mode`,
    `file-history-snapshot`) are passed through unchanged.
    Lines that fail to parse as JSON are passed through unchanged with a
    debug log (do not crash on partial corruption)."""
    new_lines = []
    with jsonl_path.open(encoding="utf-8") as f:
        for raw in f:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                new_lines.append(raw)
                continue
            if isinstance(obj, dict) and "cwd" in obj:
                obj["cwd"] = new_cwd_absolute
                new_lines.append(json.dumps(obj) + "\n")
            else:
                new_lines.append(raw)
    _atomic_write_text(jsonl_path, "".join(new_lines))
```

The empirical test (Tier 2) determines which path is real. Pseudocode:

```python
@pytest.mark.skipif(not os.environ.get("CROAM_E2E"), reason="needs real claude")
def test_claude_resume_enforces_cwd(e2e_dummy, tmp_path):
    """RESOLVES spec section 11/15 open question."""
    src_dir, src_sid = e2e_dummy
    # Prepare a destination cwd that does NOT match any cwd recorded in the JSONL
    dest_dir = tmp_path / "rebased-target"
    dest_dir.mkdir()
    encoded_dest = encode_cwd(dest_dir.resolve())
    # Claude looks for ~/.claude/projects/<encoded-dest>/<sid>.jsonl
    fake_home = tmp_path / "fake_home"  # NOT redirected; real claude reads ~/.claude
    # Easiest: copy JSONL into the user's REAL ~/.claude/projects/<encoded-dest>/<sid>.jsonl
    # at a uuid we own (fork-sid, so no collision); cleanup at end.
    fork_sid = str(uuid.uuid4())
    real_projects = Path.home() / ".claude" / "projects" / encoded_dest
    real_projects.mkdir(parents=True, exist_ok=True)
    src_jsonl = src_dir / f"{src_sid}.jsonl"  # adapt path to dummy's actual layout
    dest_jsonl = real_projects / f"{fork_sid}.jsonl"
    shutil.copy2(src_jsonl, dest_jsonl)
    try:
        # Run claude --resume <fork_sid> with cwd = dest_dir; observe behavior
        proc = subprocess.run(
            ["claude", "--resume", fork_sid, "--print", "exit"],
            cwd=dest_dir,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        # The question: does it complete (returncode 0, no cwd-mismatch error)?
        # OR does it fail with a "session cwd doesn't match" error?
        # Document the answer in CODEBASE_CONTEXT.md.
        if proc.returncode == 0:
            ENFORCEMENT = "no"
        else:
            ENFORCEMENT = "yes"
            # Inspect stderr for the cwd-mismatch error message
        # Write the answer to a file the rest of the test suite reads:
        (Path.home() / ".claude" / "_croam_cwd_enforcement.txt").write_text(ENFORCEMENT)
    finally:
        dest_jsonl.unlink(missing_ok=True)
```

**Critical**: this test mutates the user's REAL `~/.claude/projects/...`. It is gated on `CROAM_E2E=1` AND a clean fork_sid (uuid4 cannot collide with anything real). Cleanup in `finally`.

The result of this test propagates as `CROAM_CLAUDE_ENFORCES_CWD=1` env var (in the test harness) and as the documentation update at end of phase.

### File: `src/croam/commands/reconcile.py` (new)

Called from `commands/default.py:run_picker` BEFORE building rows.

```python
def detect_outclaim_and_prompt(
    state_root: Path,
    hostname: str,
    home: Path,
    config: Config,
    merged: dict[str, Assertion],
    *,
    input_fn = input,  # injectable for tests
) -> int:
    """For each sid where we have a local assertion (was self-owned) but the
    merged view says someone else owns it now, run reconciliation.

    For each detected outclaim:
      1. Read snapshot line count (snapshots.read_snapshots()[sid]).
         If absent, treat as 0.
      2. Find local JSONL: scan ~/.claude/projects/*/<sid>.jsonl. If multiple
         (rare; --here historic moves), pick the one whose dir matches our
         original assertion's cwd_normalized.
      3. current_lines = count_jsonl_lines(local_jsonl)
      4. If current_lines <= snapshot: auto-discard (delete local JSONL,
         remove our local assertion entry, log INFO).
      5. If current_lines > snapshot: prompt
         "Session <sid> was claimed by <new_owner> at <ts>. Your local copy
          has <delta> lines added after that claim. [F]ork these into a new
          session, or [d]iscard? "
         Use input_fn (not typer.prompt) so monkeypatching builtins.input works.
         Loop on invalid input. Accept "f"/"F"/"fork", "d"/"D"/"discard".
         Optionally accept "s"/"skip" to defer (no-op for this run).
      6. Fork branch: invoke commands.fork.run(sid, ctx_obj, config, home,
         here=False) using OUR LOCAL JSONL as the source (not the new owner's).
         The fork.run() impl reads from our local ~/.claude/projects/<encoded>/
         <sid>.jsonl which still has the new lines. After fork, also delete
         our local JSONL and remove our stale assertion entry.
      7. Discard branch: delete local JSONL, remove our stale assertion entry,
         remove snapshot entry. Log INFO.

    Returns 0 always (errors are logged and skipped; reconciliation is best-effort
    so the picker still opens).
    """
```

The `commands.default.run_picker` should call this once at startup, AFTER reading the merged view, BEFORE rendering rows. Phase 6 owns `default.py` but Phase 7 has been adding to it; Phase 8 adds one line:

```python
# In commands/default.py:run_picker, after computing merged view:
from croam.commands import reconcile
reconcile.detect_outclaim_and_prompt(state_root, hostname, home, config, merged)
```

### CLI wiring (`src/croam/cli.py`)

Add typer commands:

```python
@app.command()
def claim(
    sid: str = typer.Argument(...),
    here: bool = typer.Option(False, "--here", help="Rebase to current $PWD"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation for forced claim"),
):
    """Transfer ownership of sid to this host."""
    from croam.commands import claim as claim_mod
    raise typer.Exit(claim_mod.run(sid, _ctx(), _config(), _home(), here=here, force=force))

@app.command()
def fork(
    sid: str = typer.Argument(...),
    here: bool = typer.Option(False, "--here", help="Rebase fork to current $PWD"),
):
    """Create a new session branched from sid."""
    from croam.commands import fork as fork_mod
    raise typer.Exit(fork_mod.run(sid, _ctx(), _config(), _home(), here=here))

@app.command()
def release(
    sid: str = typer.Argument(...),
    requester: str = typer.Option(..., "--requester"),
):
    """[internal] Receive a claim handshake. Invoked over SSH by claim."""
    from croam.commands import release as release_mod
    raise typer.Exit(release_mod.run(sid, requester, _ctx(), _config(), _home()))
```

### Documentation updates (last step of phase)

After the Tier 2 test runs and the answer is captured, update:

1. **`docs/agent/project-start/CODEBASE_CONTEXT.md`**, "Encoded-cwd convention" subsection: add a line "Empirical answer to claude-resume cwd enforcement (Phase 8): YES/NO. Surgical JSONL rewrite is/is not required for `--here`. Test command used: `claude --resume <sid>` with cwd != recorded cwd; observed: <stdout/stderr summary>."
2. **`docs/agent/project-start/PROJECT_PLAN.md`**, "References" section: append the same answer with a one-line summary.
3. Set `CROAM_CLAUDE_ENFORCES_CWD` (env or module constant in `src/croam/commands/claim.py` and `fork.py`) to the empirical value so default behavior is correct.

If the Tier 2 test cannot run (e.g., `CROAM_E2E` not set), document the fallback default: assume "no enforcement" per spec section 15, leave the surgical-rewrite code unreachable but tested via unit tests, and flag the unresolved question in the phase summary's "Open Issues" section.

---

## Edge cases (explicit list)

1. **claim already-self-owned**: log "no-op", return 0. No state change.
2. **claim self-host (host claims sid it already owns)**: same as 1.
3. **claim of orphan sid**: refuse with `OrphanRefused("claim refused: orphan; use fork instead")`.
4. **claim sid not in any merge view**: `SessionNotFound`.
5. **claim with --here when $PWD does not exist**: cannot happen (we're in it); but if `os.getcwd()` raises, surface as `CroamError`.
6. **claim with --here when destination encoded-cwd dir is missing**: create it (`mkdir -p`).
7. **claim cooperative handshake but `release` SSH returns non-zero**: `SshError`. Local state UNCHANGED.
8. **claim cooperative handshake, release succeeds, but JSONL `cat` fails**: WARNING -- the owner already released. We have NOT yet written our assertion. Recovery: log error, the sid is now ownerless on this host but the owner already wrote action="release" so it's not theirs either. Surface as orphan on next run. Document in test `test_claim_handshake_cat_fails_leaves_orphan`.
9. **claim cooperative handshake, JSONL copied, but write_local_assertions fails**: WARNING -- we have the JSONL but no assertion. Surfaces as orphan on next run. Document in test `test_claim_jsonl_copied_assertion_fails_orphan`.
10. **forced claim, mirror missing**: `SshError("origin unreachable and no mirror; cannot claim")`.
11. **forced claim, user declines confirmation**: return 1, no state change.
12. **ssh-strict, peer returns malformed emit-state JSON**: log warning, treat that peer as gap (do not include in re-merge). Test: `test_claim_ssh_strict_peer_returns_garbage`.
13. **ssh-strict, all peers unreachable**: degrade to local-only merge with WARNING. Document.
14. **fork of remote-owned sid with no local JSONL and no mirror**: `SessionNotFound`.
15. **fork of orphan, --orphans not set**: `OrphanRefused`.
16. **fork same sid 5 times**: fork_n is 1, 2, 3, 4, 5 (per parent, NOT per host).
17. **fork --here when cwd matches parent cwd already**: works; no rewrite needed; lineage and assertion still written.
18. **reconcile: snapshot missing**: treat as 0; if local has any lines, prompt. (Conservative: "you might lose data, ask user.")
19. **reconcile: local JSONL missing entirely**: auto-discard the stale assertion, remove snapshot, no prompt.
20. **reconcile: user inputs garbage**: re-prompt (loop), or accept "s"/"skip" to defer.
21. **JSONL trailing partial line**: `_trim_trailing_partial_json` drops it (spec 13 atomicity).
22. **ssh argv must always include `-o ConnectTimeout=2 -o BatchMode=yes -o StrictHostKeyChecking=no`** -- enforce in a single helper to avoid drift.
23. **claim --here AND ssh-strict pre-verify peer disagrees about cwd_normalized**: spec doesn't specify. Decision: ssh-strict only checks ownership transition, not cwd. The cwd is local to claimer. Document.

---

## Dependencies

**Requires**:
- Phase 1: `errors.py` (`OwnershipConflict`, `SshError`, `SessionNotFound`, `OrphanRefused`, `TmuxError`, `CroamError`), `proc.run`, `log.configure`, conftest fixtures (`home`, `tmux_socket`, `ssh_shim`, `state_root`, `e2e_dummy`).
- Phase 2: `Config` dataclass, `paths.encode_cwd`, `paths.normalize_cwd`.
- Phase 3: `hosts.probe_reachability`, `hosts.emit_state` (the `--emit-state` subcommand schema).
- Phase 4: `Assertion`, `read_local_assertions`, `read_all_assertions`, `merge_assertions`, `write_local_assertions`, `flatten_local`, `read_lineage`, `write_lineage`, `add_lineage`, `detect_outclaim`. Phase 8 must NOT extend the `Assertion` dataclass (per the planner brief: snapshots live in a separate `snapshots.json`).
- Phase 5: `tmux.has_session`, `tmux.kill_session`.
- Phase 6: `cli.app`, `commands.default.run_picker`.
- Phase 7: `commands.attach.run` (claim's S1 ladder may dispatch to attach after a successful claim if invoked from picker; see "Notes" below for whether it does).

**Enables**:
- Phase 9: `croam doctor` checks `ownership_consistency`, which surfaces outclaims and conflict files; Phase 8's tests provide the synthetic outclaim fixtures.
- Phase 10: integration tests against synthetic two-host fixtures exercise the full claim/fork lifecycle.

---

## Completion Criteria

- [ ] All files in Deliverables created and importable.
- [ ] `tests/test_claim.py`, `tests/test_fork.py`, `tests/test_reconcile.py`, `tests/test_snapshots.py` written and passing.
- [ ] `uv run pytest -q tests/test_claim.py tests/test_fork.py tests/test_reconcile.py tests/test_snapshots.py` passes (Tier 1, no `CROAM_E2E`).
- [ ] `CROAM_E2E=1 uv run pytest -q tests/test_claim.py::test_fork_e2e_resumable tests/test_claim.py::test_claude_resume_enforces_cwd` passes on a host where `claude` is installed.
- [ ] `uv run pyright src/croam/commands/claim.py src/croam/commands/fork.py src/croam/commands/release.py src/croam/commands/reconcile.py src/croam/snapshots.py` reports 0 errors.
- [ ] `uv run ruff check src/croam/commands/{claim,fork,release,reconcile}.py src/croam/snapshots.py` is clean.
- [ ] Coverage of `claim.py + fork.py + reconcile.py + release.py + snapshots.py` is >= 90%.
- [ ] CLI verbs `claim`, `fork`, `release` are wired in `cli.py`; `commands/default.py` calls reconcile before picker render.
- [ ] `CODEBASE_CONTEXT.md` "Encoded-cwd convention" section updated with the empirical claude-resume answer.
- [ ] `PROJECT_PLAN.md` "References" or "Open Questions" updated with the same answer.
- [ ] Phase summary in `summaries/PHASE_08_SUMMARY.md` documents: (a) which design choice for snapshots was used (we MUST use the sidecar `snapshots.json`, NOT the Assertion extension -- per planner brief), (b) the empirical answer to cwd enforcement, (c) any partial-failure recovery paths that were untested and need Phase 10 coverage.

---

## Testing Requirements

### Test commands

```bash
# Tier 1 (default; no real claude needed)
uv run pytest -q tests/test_claim.py tests/test_fork.py tests/test_reconcile.py tests/test_snapshots.py

# Tier 2 (real claude; gated)
CROAM_E2E=1 uv run pytest -q -m e2e tests/test_claim.py tests/test_fork.py

# Coverage
uv run pytest --cov=croam.commands.claim --cov=croam.commands.fork --cov=croam.commands.release --cov=croam.commands.reconcile --cov=croam.snapshots --cov-report=term-missing tests/test_claim.py tests/test_fork.py tests/test_reconcile.py tests/test_snapshots.py

# Static check
uv run pyright src/croam/commands/claim.py src/croam/commands/fork.py src/croam/commands/release.py src/croam/commands/reconcile.py src/croam/snapshots.py
```

### `tests/test_snapshots.py`

- `test_read_empty(state_root)`: file missing -> `{}`.
- `test_write_then_read(state_root)`: write `{"sid-a": 42}`; read returns `{"sid-a": 42}`.
- `test_write_atomic_partial_failure(state_root, monkeypatch)`: monkeypatch `os.replace` to raise after tmpfile written; assert original file unchanged AND tmpfile cleaned up.
- `test_count_jsonl_lines_missing(tmp_path)`: returns 0.
- `test_count_jsonl_lines_three_lines(tmp_path)`: write 3 lines, returns 3.
- `test_count_jsonl_lines_no_trailing_newline(tmp_path)`: 3 lines but last has no `\n`; returns 3 (Python's iteration yields the partial last line).
- `test_remove_idempotent(state_root)`: remove nonexistent; no error.

### `tests/test_release.py` (new file)

- `test_release_idempotent_when_not_owned(state_root, home)`: we don't own sid; release returns 0, no state change.
- `test_release_kills_tmux(state_root, home, tmux_socket)`: live tmux session exists; release kills it. Verify with `tmux ls`.
- `test_release_removes_jsonl(state_root, home)`: synthetic JSONL exists; release removes it.
- `test_release_writes_assertion(state_root, home)`: after release, ownership.json shows action="release", previous_owner=requester.
- `test_release_no_exec_returns_plan(state_root, home)`: with `no_exec=True`, returns plan dict, no state change.

### `tests/test_claim.py`

- `test_claim_already_self_owned(state_root, home)`: we own sid; `runner.invoke(app, ["claim", sid])` exits 0 with log "already owned"; no state change.
- `test_claim_remote_reachable_handshake(state_root, home, ssh_shim, tmux_socket)`: synthetic state where vicar owns sid; ssh_shim returns OK for `croam release` and `cat <jsonl>`. Run claim. Assert:
  - ssh argv includes `["ssh", ..., "vicar-alias", "croam", "release", sid, f"--requester=stormtree"]`
  - ssh argv for cat includes the right JSONL path
  - local ownership.json now has the entry with action="claim", previous_owner="vicar"
  - local JSONL file exists at the expected encoded-cwd path
  - snapshots.json has a count for sid
- `test_claim_remote_unreachable_forced(state_root, home, ssh_shim, monkeypatch)`: peer probe fails (ssh_shim returns nonzero). With `monkeypatch.setattr("builtins.input", lambda _: "y")`. Synthetic mirror at `<state_root>/vicar/projects/<encoded>/<sid>.jsonl`. Assert claim copies from mirror; ownership.json shows action="claim".
- `test_claim_forced_with_force_flag(state_root, home, ssh_shim)`: with `force=True`, no input prompt; claim proceeds.
- `test_claim_unreachable_no_mirror_errors(state_root, home, ssh_shim)`: peer unreachable AND mirror absent; assert `SshError` with "no mirror present".
- `test_claim_ssh_strict_blocks_illegal(state_root, home, ssh_shim)`: synthetic two-peer state. ssh_shim's peer-B emit-state response shows a later assertion than local view. claim with `claim_verify="ssh-strict"` raises `OwnershipConflict`. Verify error message names the conflicting peer.
- `test_claim_ssh_strict_peer_returns_garbage(state_root, home, ssh_shim)`: ssh_shim returns "not json" for emit-state; assert claim degrades to local-only merge with WARNING; does not crash.
- `test_claim_ssh_strict_race_window_acknowledged(state_root, home, ssh_shim)`: this is documentation-as-test. Assert the `claim` module has a docstring or comment noting the S2-S4 race; assert no test claims atomicity. (One-line `assert "race window" in inspect.getsource(claim_mod).lower()`.)
- `test_claim_handshake_cat_fails_leaves_orphan(state_root, home, ssh_shim)`: ssh_shim returns OK for release but nonzero for cat. Assert `SshError`. Assert local JSONL not written. Assert local ownership.json not modified (NOT having a partial claim assertion).
- `test_claim_jsonl_copied_assertion_fails(state_root, home, ssh_shim, monkeypatch)`: monkeypatch `write_local_assertions` to raise after JSONL is copied. Assert the JSONL is on disk but no assertion exists. Run `croam ls --orphans`; assert sid appears as orphan.
- `test_claim_here_rebases_cwd(state_root, home, ssh_shim, monkeypatch, tmp_path)`: `monkeypatch.chdir(tmp_path / "newdir")`. claim with `here=True`. Assert ownership.json's `cwd_normalized` reflects new $PWD; assert JSONL is at `~/.claude/projects/<encoded-newdir>/<sid>.jsonl`.
- `test_claim_orphan_refused(state_root, home)`: synthetic JSONL with no assertion. claim raises `OrphanRefused`.
- `test_claim_session_not_found(state_root, home)`: claim a sid that exists nowhere. Raises `SessionNotFound`.
- `test_claim_no_exec_returns_plan(state_root, home, ssh_shim, capfd)`: with `no_exec=True`, claim emits JSON plan to stdout containing `["ssh", ..., "release", sid, ...]` and `["ssh", ..., "cat", ...]` argvs. No state change.
- (Tier 2) `test_claim_here_with_real_dummy(e2e_dummy, tmp_path, monkeypatch)`: copy dummy JSONL to `tmp_path` clone. Run `claim --here` against the clone. Run `claude --resume <sid>` -- assert it loads (or fails with cwd-mismatch, captured into the empirical-answer file).
- (Tier 2) `test_claude_resume_enforces_cwd(e2e_dummy, tmp_path)` -- THE definitive test that updates `CODEBASE_CONTEXT.md`. Documented above under "Surgical JSONL rewrite".

### `tests/test_fork.py`

- `test_fork_simple(state_root, home)`: synthetic local owned sid + JSONL. Fork. Assert: new fork_sid is uuid4; lineage.json has entry; new JSONL exists; ownership.json has new entry with action="create".
- `test_fork_jsonl_validity(state_root, home)`: parent JSONL is 5 lines of valid JSON. Fork. Assert fork JSONL is also 5 lines, each parses as JSON.
- `test_fork_jsonl_partial_trailing_line_truncated(state_root, home)`: parent JSONL has 4 valid lines + "{partial...". Fork drops the partial line. Verify destination has exactly 4 lines.
- `test_fork_here_rebases(state_root, home, monkeypatch, tmp_path)`: `monkeypatch.chdir`. Fork with `here=True`. Destination JSONL is at encoded-newdir.
- `test_fork_n_increments(state_root, home)`: fork same parent 3 times. Each call returns/writes fork_n=1, 2, 3.
- `test_fork_n_per_parent(state_root, home)`: fork parent A 2 times, parent B 1 time. fork_n for A's children: 1, 2; for B's child: 1.
- `test_fork_remote_owned_via_mirror(state_root, home)`: parent owned by vicar, no local JSONL but mirror exists. Fork reads from mirror.
- `test_fork_remote_owned_no_mirror_errors(state_root, home)`: parent owned by vicar, no mirror, no local. Raises `SessionNotFound`.
- `test_fork_orphan_with_flag(state_root, home)`: synthetic JSONL with no assertion. ctx_obj["orphans"]=True. Fork succeeds. ctx_obj["orphans"]=False -> `OrphanRefused`.
- `test_fork_no_exec_returns_plan(state_root, home, capfd)`: returns JSON plan; no files written.
- (Tier 2) `test_fork_e2e_resumable(e2e_dummy, monkeypatch)`: fork the dummy, run `claude --resume <fork_sid>` against the fork's JSONL within 5s. Assert returncode 0 (or document cwd-mismatch failure).

### `tests/test_reconcile.py`

- `test_no_outclaims_noop(state_root, home)`: no outclaims; reconcile returns 0; no prompts; no state change.
- `test_outclaim_no_local_changes_auto_discard(state_root, home)`: synthetic outclaim. Snapshot=5, current_lines=5. Assert: local JSONL deleted, local stale assertion removed, no prompt.
- `test_outclaim_local_changes_fork(state_root, home, monkeypatch)`: `monkeypatch.setattr("builtins.input", lambda _: "f")`. Snapshot=5, current_lines=8. Assert: new fork_sid created with our local JSONL bytes; lineage entry; local JSONL deleted; stale assertion removed.
- `test_outclaim_local_changes_discard(state_root, home, monkeypatch)`: input returns "d". Assert: local JSONL deleted; stale assertion removed; no fork created.
- `test_outclaim_input_invalid_then_valid(state_root, home, monkeypatch)`: input returns ["x", "f"] sequentially. Assert: re-prompts once, then forks.
- `test_outclaim_skip_defers(state_root, home, monkeypatch)`: input returns "s". Assert: NO state change; sid still appears as outclaim on next run.
- `test_outclaim_local_jsonl_missing(state_root, home)`: outclaim detected, no local JSONL. Assert: stale assertion removed, snapshot removed, no prompt.
- `test_outclaim_snapshot_missing_treated_as_zero(state_root, home, monkeypatch)`: no snapshot entry; current_lines=3; input returns "f". Assert: prompt fired; fork created.

### Anti-pattern checks

Every test in this phase must:
- Use the `home` fixture (HOME redirected). The autouse conftest guard enforces.
- Use `ssh_shim` fixture (real subprocess argv -> fake binary on PATH) -- NOT monkeypatch `subprocess.run`.
- Use `tmux_socket` fixture for any tmux test.
- Compare datetimes only after `astimezone(timezone.utc)`.
- For input-driven tests, `monkeypatch.setattr("builtins.input", ...)` -- never `typer.prompt`.

---

## Functional QA

> Surfaces exercised: Surface 1 (CLI verbs `claim`, `fork`, `release`), Surface 4 (per-host state files: ownership.json, lineage.json, snapshots.json).

Each check below references one of the User Loops in `FUNCTIONAL_QA_STRATEGY.md`. The coding agent must run each, capture the actual command and observable output, and paste both into the phase summary's "Functional QA Results" section.

### Surface 1 checks (CLI verbs)

- [ ] (CLI surface, Loop C) `runner.invoke(app, ["claim", sid])` for a sid already owned by self exits 0; `result.stderr` contains `"already owned"`; `read_local_assertions(state_root, "stormtree")` returns the same dict before and after. Capture stdout+stderr.
- [ ] (CLI surface, Loop C) `runner.invoke(app, ["claim", sid])` for a sid owned by a remote, reachable peer (synthetic ssh_shim returning OK for release+cat) exits 0; `read_local_assertions(state_root, "stormtree")[sid].action == "claim"`; `read_local_assertions(state_root, "stormtree")[sid].previous_owner == "vicar"`; the local JSONL exists at `home / ".claude" / "projects" / encoded_cwd / f"{sid}.jsonl"`. Capture: invocation argv, ssh_shim's recorded argvs, the new ownership.json bytes.
- [ ] (CLI surface, Loop D) `runner.invoke(app, ["claim", sid])` for a sid whose origin is unreachable (ssh_shim probe fails) AND user types "n": exits 1; no state change. With `--force`: exits 0; mirror copy succeeded; ownership.json updated. Capture both invocations' stdout+stderr.
- [ ] (CLI surface, Loop C) `runner.invoke(app, ["claim", sid])` against a synthetic two-peer state where peer B has a later assertion: raises `OwnershipConflict` (caught at top level, prints clean one-liner to stderr, exits non-zero). The error message names peer B as the conflicting host. Capture stderr.
- [ ] (CLI surface, Loop E) `runner.invoke(app, ["fork", sid])` against a locally-owned sid: exits 0; `read_lineage(state_root, "stormtree")` has a new entry mapping `fork_sid -> {parent_sid: sid, fork_n: 1}`; `read_local_assertions(state_root, "stormtree")[fork_sid].action == "create"`; `(home / ".claude" / "projects" / encoded_cwd / f"{fork_sid}.jsonl").exists()`. Capture the new lineage.json and ownership.json bytes.
- [ ] (CLI surface, Loop E, Tier 2) `CROAM_E2E=1` AND `claude` on PATH: `runner.invoke(app, ["fork", e2e_dummy_sid])` followed by `subprocess.run(["claude", "--resume", fork_sid, "--print", "exit"], cwd=<dest>)` exits 0 within 5s. THIS DETERMINES THE EMPIRICAL ANSWER documented in `CODEBASE_CONTEXT.md`. Capture: stdout, stderr, returncode, elapsed time.

### Surface 4 checks (state files = wire format)

- [ ] (state surface, Loop C) After successful claim handshake, run `croam --emit-state` (Phase 3) on the new owner's host: the JSON output's `ownership.<sid>.action` is `"claim"` and `<sid>.previous_owner` is the old owner. Run `croam --emit-state` on the old owner's host: the JSON output's `ownership.<sid>.action` is `"release"`. Paste both JSON dumps.
- [ ] (state surface, Loop E) After fork, the `<state_root>/<self>/lineage.json` file parses as valid JSON and contains the fork entry. The `snapshots.json` file has an entry for `fork_sid`. Paste both files.
- [ ] (state surface, no-loop -- atomicity) Inject a fault between JSONL copy and assertion write (`monkeypatch.setattr(ownership, "write_local_assertions", lambda *a, **k: 1/0)`); run claim; assert: JSONL is on disk, ownership.json is unchanged from before claim, snapshots.json has no entry for sid (handshake left orphan; documented behavior). Paste pre/post snapshots of all three files.

### Anti-patterns to watch for in this phase

From `FUNCTIONAL_QA_STRATEGY.md`:
- **A**: every test must use `home` fixture. The conftest guard refuses if HOME is real.
- **B**: every SSH-related test must use `ssh_shim` (real subprocess), never `monkeypatch subprocess.run`.
- **C**: tmux tests use the private `tmux_socket`; `release` kills tmux on the receiving side and tests must verify with `tmux -S <sock> ls`.
- **E**: every datetime comparison goes through `.astimezone(timezone.utc)`. The `asserted_at` in our claim assertion MUST be UTC-aware.
- **G**: claim handshake is multi-step; tests inject failures at each boundary (ssh fail, cat fail, write_assertion fail) and verify the system either rolls forward cleanly or surfaces the inconsistency clearly.

---

## Helpers Required

None. Per the planner brief, all mechanics in this phase are either one-shot (the empirical Tier 2 test against the dummy) or already covered by Phase 1's `proc.run` and `ssh_shim`. The proposed `spark-claim-handshake-trace` debug helper was rejected: use `--debug` flag + log inspection instead.

---

## External Interfaces Consumed

- **`claude --resume <sid>` cwd-enforcement behavior**: spec section 11/15 open question. Phase 8 RESOLVES this empirically.
  - **Consumed by**: `src/croam/commands/claim.py` (the `--here` rebase logic) and `src/croam/commands/fork.py` (same).
  - **How to capture**: with `CROAM_E2E=1` and the dummy at `/tmp/croam-e2e/`:
    ```bash
    # Setup: copy dummy JSONL to a fork_sid in a different cwd
    fork_sid=$(uuidgen)
    test_cwd=/tmp/croam-test-fork-$$
    mkdir -p "$test_cwd"
    encoded=$(python3 -c "import sys; p=sys.argv[1]; print(p.replace('/', '-').replace('.', '-'))" "$test_cwd")
    mkdir -p "$HOME/.claude/projects/$encoded"
    src_jsonl=$(ls /tmp/croam-e2e/*.jsonl 2>/dev/null | head -n1)
    cp "$src_jsonl" "$HOME/.claude/projects/$encoded/$fork_sid.jsonl"
    # The test:
    cd "$test_cwd"
    timeout 10 claude --resume "$fork_sid" --print "exit" 2>&1
    echo "EXITCODE=$?"
    # Cleanup:
    rm -f "$HOME/.claude/projects/$encoded/$fork_sid.jsonl"
    rmdir "$HOME/.claude/projects/$encoded" 2>/dev/null
    rmdir "$test_cwd"
    ```
    Observe: does `claude --resume` succeed (exit 0) or fail with a cwd-mismatch error?
  - **If not observable**: if `CROAM_E2E` is not set or the dummy is missing, default to "no enforcement" (per spec section 15) and document in the phase summary's "Open Issues" section. The surgical-rewrite code stays in place but unreachable; unit tests still cover the rewrite logic itself in isolation.
  - **Where to record**: AFTER capturing the answer, update `docs/agent/project-start/CODEBASE_CONTEXT.md` "Encoded-cwd convention" section AND `docs/agent/project-start/PROJECT_PLAN.md` "References" with the empirical answer (1-2 sentences + the captured exit code/stderr).

- **`croam --emit-state` JSON output (from peer hosts via SSH)**: well-defined by Phase 3's `emit_state` function. Phase 8 consumes it during `ssh-strict` pre-verify.
  - **Consumed by**: `src/croam/commands/claim.py:run` (the S2 ssh-strict step).
  - **How to capture**: run `uv run croam emit-state` locally against synthetic state under `tmp_path` -- this is Phase 3's function, called as a regular Python function. The SSH wrapping is just `ssh peer croam emit-state`, and `ssh_shim` produces the canned output. Inspect the actual schema by calling `hosts.emit_state(home, state_root)` in a Python REPL with a populated `state_root`.
  - **If not observable**: cannot happen -- Phase 3 is a hard dependency and its output schema is fixed. If the schema changed after Phase 3 shipped, update Phase 8 to match and flag in summary.

---

## Notes

- **The reconcile prompt MUST use `input()`, NOT `typer.prompt`.** Test mocking via `monkeypatch.setattr("builtins.input", ...)` is the only sane way to test interactive prompts; `typer.prompt` is harder to mock.
- **The forced-claim confirmation prompt also uses `input()`** for the same reason.
- **Snapshots design choice (mandatory)**: per the planner brief, store `snapshots.json` in a separate file under `<state_root>/<self>/snapshots.json`. Do NOT extend the `Assertion` dataclass (Phase 4 owns that file; cross-phase coordination is forbidden by the file-contention rules).
- **Race window between S2 (ssh-strict pass) and S4 (assertion write)**: do not attempt to fix it. Document in code comments and in `test_claim_ssh_strict_race_window_acknowledged`. The fix requires distributed locking which is out of scope.
- **`--here` cwd rebase**: the spec defaults to "no rewrite" assumption. Phase 8's job is to verify. If the empirical test reveals enforcement, implement the per-line rewrite and gate it behind `CROAM_CLAUDE_ENFORCES_CWD` (env var or module constant set from the empirical answer). If the test cannot run (e.g., no `CROAM_E2E`), keep the rewrite code dormant and document in the phase summary.
- **claim from picker**: the picker (Phase 6) returns `(expect_key, selected_rows)`. `commands/default.py:run_picker` dispatches `c -> claim(here=False)`, `C -> claim(here=True)`, `f -> fork(here=False)`, `F -> fork(here=True)`. Phase 8 wires this dispatch.
- **After successful claim, do NOT auto-attach.** The user explicitly asked to claim; if they want to attach, they'll press Enter on the picker next, or run `croam attach`. Auto-attach would be surprising; document in the claim docstring.
- **Logging**: every step of the handshake logs at INFO with the sid + action. ssh argvs go to DEBUG. The full state machine should be reconstructible from `~/.local/state/croam/croam.log` with `--debug`.
- **Atomic file ops**: re-use Phase 4's `_atomic_write_json` pattern for snapshots.json. Use a similar `_atomic_write_text` helper for JSONL writes.
- **JSONL bytes**: when copying via `ssh ... cat`, use `subprocess.run(..., capture_output=True)` and pipe `result.stdout` to file. For large transcripts (100+ KB) this is fine; if real-world transcripts grow to MB-scale, revisit. Do NOT use `text=True` -- use bytes and decode at write time, because JSONL may have partial UTF-8 mid-stream that text=True would mangle.
- **Phase 3's `emit_state` JSON schema**: when ssh-strict-fetching peer state, you receive a JSON dict. Use Phase 4's `read_all_assertions(state_root, peer_states=peer_states)` overload to feed it into the merge. Do NOT replicate parsing logic.
- **DUMMY_SID**: `ff7afd8a-ea17-4183-a131-566e7bcb0758` (referenced in `CODEBASE_CONTEXT.md` and `e2e_dummy` fixture).
