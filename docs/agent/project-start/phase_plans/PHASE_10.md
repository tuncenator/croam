# Phase 10: Integration tests round 1

**Feature**: project-start
**Estimated Context Budget**: ~65k tokens

**Difficulty**: medium
**Visual**: no
**Functional**: yes (covers all 4 surfaces)

**Execution Mode**: sequential
**Batch**: 7 (sole phase in this batch; depends on Phases 7, 8, 9)

---

## Objective

Write end-to-end integration tests that exercise every surface in croam (CLI verbs, picker, shim, per-host state files) using synthetic two-host fixtures plus opt-in real-claude E2E tests against the dummy at `/tmp/croam-e2e/`. This phase writes ZERO new code under `src/croam/`; it is a pure test phase that proves the assembly of Phases 1-9 satisfies spec section 16's acceptance criteria and closes the open questions in spec section 15.

The phase explicitly closes two open questions from spec section 15:
1. **Exact format of claude's encoded-cwd directory naming** -- already answered in the Phase 0 setup pass (`CODEBASE_CONTEXT.md` "Encoded-cwd convention"): per-segment, `/` and leading-`.` -> `-`, decoding is lossy. Phase 10 verifies this answer against the real dummy at runtime.
2. **Whether claude enforces recorded cwd on resume** -- answered empirically by Phase 8 against the dummy. Phase 10 verifies the answer holds for fork-and-resume specifically (the more invasive case), and updates `CODEBASE_CONTEXT.md` with the final verdict (with or without surgical JSONL rewrite).

---

## Deliverables

1. `tests/integration/__init__.py` (empty package marker)
2. `tests/integration/conftest.py` (the two-host fixture: `two_host_env` returning a structured object holding both `tmp_path/stormtree/{home,state}/` and `tmp_path/vicar/{home,state}/`, plus a `vicar_ssh_router` that wires the existing `ssh_shim` so that `ssh vicar <cmd>` invokes croam in a Python subprocess against vicar's HOME and state_root)
3. `tests/integration/test_two_host_picker.py` (picker round-trip: stormtree sees vicar's session, Enter dispatches the right ssh argv)
4. `tests/integration/test_two_host_claim.py` (claim handshake end-to-end: full state mutation on both sides verified)
5. `tests/integration/test_two_host_offline.py` (forced claim with vicar unreachable; post-claim state on stormtree verified)
6. `tests/integration/test_doctor_full.py` (clean -> exit 0; corrupted state with conflict file -> non-zero with FAIL line)
7. `tests/integration/test_e2e_dummy_attach.py` (Tier 2 only: `croam attach <DUMMY_SID> --no-exec` against the real dummy emits a planned argv with `claude --resume <sid>` inside tmux)
8. `tests/integration/test_e2e_dummy_fork.py` (Tier 2 only: `croam fork <DUMMY_SID>` against a tmp_path clone of the dummy, then `claude --resume <fork_sid>` actually loads the forked transcript)
9. `tests/integration/test_shim_real_tmux.py` (real tmux on private socket; shim invocation with `claude-real` substituted by `/bin/sleep 5`; tmux session name verified)
10. `tests/integration/test_orphan_handling.py` (JSONL with no backing assertion: hidden by default, listed by `--orphans`, refused by `claim`, allowed by `fork`)
11. Coverage report: `uv run pytest --cov=croam --cov-report=term-missing` shows >= 80% overall coverage
12. `CODEBASE_CONTEXT.md` updated with the empirical findings (encoded-cwd verdict against real dummy; claude cwd-enforcement verdict from Phase 8 referenced; any new gotchas observed in `claude --resume` non-interactive behavior)

---

## Detailed Requirements

### 10.1 Tests directory structure

```
tests/
  integration/
    __init__.py
    conftest.py                       # two_host_env fixture
    test_two_host_picker.py
    test_two_host_claim.py
    test_two_host_offline.py
    test_doctor_full.py
    test_e2e_dummy_attach.py          # Tier 2
    test_e2e_dummy_fork.py            # Tier 2
    test_shim_real_tmux.py
    test_orphan_handling.py
```

Do NOT touch `tests/conftest.py` (root). It owns the `home`, `tmux_socket`, `ssh_shim`, `state_root`, `e2e_dummy` fixtures from Phase 1. Phase 10 composes them via a new `tests/integration/conftest.py`.

Do NOT touch any file under `src/croam/`. If you find a missing feature or bug while writing tests, document it in your phase summary's "Findings" section. Do NOT silently patch source. The fix belongs in a follow-up phase.

### 10.2 The `two_host_env` fixture (in `tests/integration/conftest.py`)

Compose existing fixtures into a two-host environment. Signature:

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class HostEnv:
    name: str          # "stormtree" or "vicar"
    home: Path         # tmp_path/<name>/home (with .claude/, .config/, .local/)
    state_root: Path   # tmp_path/<name>/state (the state_root for this host)
    config_path: Path  # <home>/.config/croam/config.toml

@dataclass(frozen=True)
class TwoHostEnv:
    stormtree: HostEnv
    vicar: HostEnv
    ssh_registry: dict[tuple[str, str], tuple[str, int]]  # (host, command) -> (stdout, returncode)

@pytest.fixture
def two_host_env(tmp_path: Path, monkeypatch) -> TwoHostEnv: ...
```

Implementation:
- For each host in `["stormtree", "vicar"]`: build `tmp_path/<host>/home/.claude/{projects,sessions}`, `tmp_path/<host>/home/.config/croam/`, `tmp_path/<host>/state/<HOSTNAME_UPPERCASE>/`.
- Write a config.toml in each `home/.config/croam/config.toml` declaring `self_hostname = "<host>"`, both hosts in `[hosts.*]`, `state_root = "<tmp_path>/<host>/state"`, `discovery_mode = "ssh"`, `claim_verify = "local"` (override per test if you need ssh-strict).
- Set HOME to `tmp_path/stormtree/home` by default (the "current" host in tests is stormtree). Tests that need to simulate "running on vicar" do so by passing `home=two_host_env.vicar.home` to the verb's `run()` function directly (the verbs already accept `home: Path` per Phase 7's signatures).
- Build the `ssh_registry` dict and wire `ssh_shim` (from root conftest) to look up `(host, command)` keys. The fake ssh script reads its argv `[ssh, host, ...command_words]`, looks up `(host, " ".join(command_words))` in the registry, prints `stdout`, exits with `returncode`.
- For the `ssh vicar croam ...` case (the most common): the registry value is computed by spawning a Python subprocess that runs `croam` against vicar's HOME and state_root. Concretely, register a handler that, when `ssh vicar croam <args...>` is invoked, runs `subprocess.run(["uv", "run", "croam", *args], env={"HOME": str(vicar.home), "CROAM_STATE_ROOT": str(vicar.state_root), ...}, capture_output=True, text=True)` and registers the result in `ssh_registry` lazily. The simplest implementation is a small wrapper script in `tests/integration/_helpers/vicar_ssh_handler.py` that the `ssh_shim` invokes when it detects `ssh vicar ...`.

You can keep it simpler: the `vicar_ssh_router` precomputes the expected commands the test will issue and pre-populates `ssh_registry` with the corresponding outputs. Most tests only need 2-3 entries (e.g., `ssh vicar true` for reachability probe, `ssh vicar croam emit-state`, `ssh vicar croam attach <sid> --here-on-owner`). For each test, register exactly the commands that test expects, and assert at the end that the registry was consumed (no untriggered entries) -- this catches drift in the orchestration layer.

Provide two helper methods on `TwoHostEnv`:

```python
def register_ssh(self, host: str, cmd: str, stdout: str, returncode: int = 0) -> None: ...
def assert_ssh_invoked(self, host: str, cmd: str) -> None: ...
```

The `assert_ssh_invoked` reads a per-test log of which `(host, cmd)` keys were actually hit by the fake ssh script (the script appends to `tmp_path/ssh_log.jsonl`).

Edge case: when vicar is meant to be unreachable, register `ssh vicar true` with returncode 255 (SSH connect-refused convention). The reachability probe in `hosts.probe_reachability` should treat returncode 255 as `reachable=False`.

### 10.3 `test_two_host_picker.py`

Three tests, all under `class TestTwoHostPicker`:

```python
def test_stormtree_picker_shows_vicar_session(two_host_env, monkeypatch): ...
def test_stormtree_enter_dispatches_ssh_attach(two_host_env, monkeypatch): ...
def test_picker_filter_pwd_excludes_other_cwds(two_host_env, monkeypatch): ...
```

For each:
1. Use `tests/_helpers/synth_jsonl.py` (Phase 1 deliverable) to create a fake claude session on vicar at `tmp_path/vicar/home/.claude/projects/<encoded-cwd>/<sid>.jsonl` with a known sid like `"abcd1234-vicar-..."`.
2. Use `tests/_helpers/synth_assertions.py` (Phase 4 deliverable) to write vicar's `ownership.json` with `owner=vicar, action=create`.
3. Run the picker via `picker.render_rows(...)` (the unit-test surface) to assert the row composition. Then for the dispatch test, use `--no-exec` (per Phase 7 brief: every `run()` accepts `--no-exec` returning planned argv as JSON).
4. Test 1: assert the rendered rows include vicar's sid with `host="vicar", glyph="o"` (vicar reachable per `register_ssh("vicar", "true", "", 0)`).
5. Test 2: simulate Enter on vicar's row (call `commands.attach.run(sid=vicar_sid, here_on_owner=False, ...)` with `CROAM_NO_EXEC=1`). Capture the planned argv. Assert it equals `["ssh", "vicar", "croam", "attach", vicar_sid, "--here-on-owner"]` exactly.
6. Test 3: chdir into a subdirectory that does NOT match either session's cwd. Render rows with `pwd=<that subdir>` and `picker_default_filter="exact-pwd"`. Assert the returned row list is empty.

Edge cases to cover explicitly:
- vicar's session has a cwd of `/home/tunc/Programs/onlayer-x` while stormtree has `/home/tunc/Programs/croam` -- both should be visible under `--all`, only matching pwd shown by default.
- If sid lookup is by prefix (e.g., user provides `abcd`), test that the prefix resolves to vicar's sid.

### 10.4 `test_two_host_claim.py`

Two tests under `class TestTwoHostClaim`:

```python
def test_claim_remote_session_full_handshake(two_host_env, monkeypatch): ...
def test_claim_idempotent_when_already_owned(two_host_env): ...
```

Test 1 (the canonical Loop C from `FUNCTIONAL_QA_STRATEGY.md`):
1. Setup: vicar has a session (`vicar_sid`) with assertion `owner=vicar, action=create, asserted_at=2026-04-29T10:00Z`. JSONL exists at `tmp_path/vicar/home/.claude/projects/-home-tunc-Programs-onlayer--x/<vicar_sid>.jsonl`.
2. Register the SSH handshake commands:
   - `ssh vicar true` -> `("", 0)` (reachable)
   - `ssh vicar croam emit-state` -> `("<JSON of vicar's emit_state>", 0)` (use `hosts.emit_state(vicar.home, vicar.state_root)` to compute the JSON ahead of time)
   - `ssh vicar croam release <vicar_sid> --requester stormtree` -> `("", 0)` (the release on origin)
   - `ssh vicar cat .claude/projects/-home-tunc-Programs-onlayer--x/<vicar_sid>.jsonl` -> `(<actual JSONL bytes>, 0)` (the JSONL copy step; if Phase 8 implemented this with scp, register that command instead)
3. Run `commands.claim.run(sid=vicar_sid, ctx_obj={...}, config=stormtree_config, home=stormtree.home, here=False)`.
4. Assert:
   - Stormtree's `ownership.json` now has `vicar_sid` with `owner=stormtree, action=claim, previous_owner=vicar, asserted_at=<recent>`.
   - Stormtree's `~/.claude/projects/-home-tunc-Programs-onlayer--x/<vicar_sid>.jsonl` exists and content matches what was on vicar.
   - `assert_ssh_invoked("vicar", "croam release <vicar_sid> --requester stormtree")` passes.
   - Vicar's state was NOT directly mutated by the test (test only verifies what stormtree-side croam would request via SSH; the actual remote mutation is verified by Phase 8's tests, NOT here).

Test 2:
1. Setup: stormtree owns `stormtree_sid` already (asserted in stormtree's ownership.json).
2. Run `commands.claim.run(sid=stormtree_sid, ...)`.
3. Assert: exit code 0, no SSH issued, log contains `"already owned by self"`.

### 10.5 `test_two_host_offline.py`

Three tests under `class TestForcedClaim` (Loop D):

```python
def test_forced_claim_origin_unreachable(two_host_env, monkeypatch): ...
def test_doctor_reports_unreachable_host(two_host_env, monkeypatch): ...
def test_forced_claim_writes_claimed_away_marker(two_host_env, monkeypatch): ...
```

Test 1:
1. Vicar has a session in syncthing mirror at `stormtree.state_root/VICAR/projects/<encoded>/<vicar_sid>.jsonl` (synthesize this -- forced claim copies from mirror, not from vicar directly).
2. Register `ssh vicar true` -> `("", 255)` (unreachable).
3. Run `commands.claim.run(sid=vicar_sid, home=stormtree.home, ...)`. The claim handler asks for confirmation when origin is unreachable (Loop D); inject confirmation via `monkeypatch.setattr("builtins.input", lambda _: "y")`.
4. Assert: stormtree's ownership.json has the claim entry; stormtree's `~/.claude/projects/.../<vicar_sid>.jsonl` exists; the JSONL bytes match the mirror's bytes.
5. Assert: a "claimed away" marker exists for vicar in stormtree's state -- per Phase 8, this is either an extra entry in stormtree's ownership.json with `action="claim", previous_owner="vicar"` (the same marker as a regular claim) OR a separate sidecar. Verify whichever Phase 8 chose. Read `summaries/PHASE_08_SUMMARY.md` to confirm the implementation choice before writing the assertion.

Test 2:
1. With vicar unreachable (`ssh vicar true` -> 255).
2. Run `doctor.run_doctor(stormtree_config, stormtree.home)`.
3. Assert: exit code != 0; stdout contains `"[FAIL] hosts: vicar"` (and a reason mentioning unreachable or connect-refused).
4. Also assert the stormtree mirror is reported as fresh: `"[OK] state_root"` line present.

Test 3:
1. Same setup as test 1.
2. After the claim, simulate vicar coming back online by re-running `commands.claim.run` from vicar's perspective (call with `home=vicar.home, state_root=vicar.state_root`) -- this is the reconciliation hook.
3. Actually, per Phase 8, the reconciliation runs from `commands.default.run_picker` BEFORE building rows. So instead: invoke `commands.reconcile.detect_outclaim_and_prompt(state_root=vicar.state_root, hostname="vicar", home=vicar.home, merged=...)`.
4. Synthesize vicar's "merged view" with stormtree's later assertion present.
5. Inject `input` for the discard path: `monkeypatch.setattr("builtins.input", lambda _: "d")`.
6. Assert: vicar's local JSONL deleted; vicar's ownership.json no longer has an active assertion for that sid (per "flatten" rule -- vicar's ownership.json only contains sids vicar currently owns).

### 10.6 `test_doctor_full.py`

Four tests under `class TestDoctorFull`:

```python
def test_doctor_clean_two_host_setup(two_host_env): ...
def test_doctor_conflict_file_fails(two_host_env): ...
def test_doctor_stale_mirror_warns(two_host_env, monkeypatch): ...
def test_doctor_outclaim_warns(two_host_env): ...
```

Test 1:
1. Both hosts in two_host_env; both have valid ownership.json; mirror subdirs are fresh (mtime within last hour); fzf, tmux, ssh, claude all on PATH.
2. Run `doctor.run_doctor(stormtree_config, stormtree.home)`.
3. Assert exit code 0.
4. Assert stdout contains: `[OK] config`, `[OK] state_root`, `[OK] hosts: stormtree (self)`, `[OK] hosts: vicar`, `[OK] tmux`, `[OK] fzf`, `[OK] ssh`, `[OK] claude` (one OK line per check; exact wording per Phase 9's `DiagnosticResult`).

Test 2:
1. Inject a syncthing conflict file at `stormtree.state_root/VICAR/ownership.sync-conflict-20260430-123000-VICAR.json`.
2. Run doctor.
3. Assert exit code != 0; stdout contains `[FAIL] sync conflict files: 1` (or whatever Phase 9's exact wording is -- read the source/tests if uncertain).

Test 3:
1. Mtime-touch all files under `stormtree.state_root/VICAR/` to be 25 hours old via `os.utime`.
2. Set discovery_mode to "syncthing" or "hybrid" so freshness is checked.
3. Run doctor.
4. Per Phase 9 brief: `> 1h = WARN, > 24h = FAIL`. So 25h should be FAIL.
5. Assert exit code != 0; stdout contains `[FAIL]` and `vicar` and `stale`.

Test 4:
1. Synthesize an outclaim: stormtree's ownership.json claims sid X at 10:00Z; vicar's mirror shows vicar's claim of sid X at 10:01Z (later). The merge says vicar wins, so stormtree has been "outclaimed" -- but stormtree's local ownership.json still has its claim entry (flatten happens lazily).
2. Run doctor.
3. Assert exit code 0 (outclaim is WARN, not FAIL); stdout contains `[WARN]` line mentioning the sid and both hosts.

### 10.7 `test_e2e_dummy_attach.py` (Tier 2)

Marker: `@pytest.mark.skipif(not os.environ.get("CROAM_E2E"), reason="Tier 2 only")` at module level.

```python
def test_attach_dummy_no_exec(e2e_dummy, tmp_path, monkeypatch): ...
```

1. Setup: HOME stays redirected (autouse guard requires it). But we read the dummy from `e2e_dummy.path = /tmp/croam-e2e/`. The test prepares a tmp_path-rooted state with an assertion saying the current host owns the dummy sid.
2. Synthesize stormtree's ownership.json with `<DUMMY_SID> -> owner=stormtree, action=create, cwd_normalized="/tmp/croam-e2e"`.
3. Symlink `tmp_path/home/.claude/projects/-tmp-croam-e2e/<DUMMY_SID>.jsonl` to the real dummy JSONL (read-only -- the test never mutates the real dummy).
4. Run `commands.attach.run(sid=<DUMMY_SID>, here_on_owner=False, ...)` with `CROAM_NO_EXEC=1`.
5. Assert: planned argv equals `["tmux", "-S", "<socket>", "new-session", "-d", "-s", "claude-<DUMMY_SID>", "--", "claude-real", "--resume", "<DUMMY_SID>"]` followed by `["tmux", "-S", "<socket>", "attach", "-t", "claude-<DUMMY_SID>"]` (or however Phase 5/7 structured the attach plan -- if it's a single argv list, just match what `attach.run --no-exec` outputs).
6. Importantly: the encoded-cwd `-tmp-croam-e2e` is computed by `paths.encode_cwd("/tmp/croam-e2e")`. Assert this matches the actual directory name on disk: `os.listdir("/tmp/croam-e2e/.claude/projects/")` should contain a directory whose name equals what `encode_cwd` produced. If not, fail loudly with the discrepancy -- this is the spec section 15 verification.

DO NOT actually exec `claude --resume`. The `--no-exec` flag returns the plan; that's enough for this test. The actual `claude --resume` exec is verified by `test_e2e_dummy_fork.py`.

### 10.8 `test_e2e_dummy_fork.py` (Tier 2)

Marker: `@pytest.mark.skipif(not os.environ.get("CROAM_E2E"), reason="Tier 2 only")`.

```python
def test_fork_dummy_resumable(e2e_dummy, tmp_path, monkeypatch): ...
```

This is the most invasive Tier 2 test -- it actually invokes `claude --resume`. Be careful:

1. Copy the dummy to a tmp_path-rooted clone:
   - `tmp_path/croam-e2e/` mirrors `/tmp/croam-e2e/`'s structure
   - Copy `/tmp/croam-e2e/.claude/projects/-tmp-croam-e2e/<DUMMY_SID>.jsonl` to `tmp_path/croam-e2e/.claude/projects/-tmp-croam-e2e/<DUMMY_SID>.jsonl`
   - Set HOME to `tmp_path/croam-e2e/` for the duration of the test
2. Run `commands.fork.run(sid=<DUMMY_SID>, here=False, home=tmp_path/croam-e2e/, ...)`.
3. Read the new fork sid from the lineage.json that fork wrote.
4. Assert the new JSONL exists at `<home>/.claude/projects/-tmp-croam-e2e/<fork_sid>.jsonl` and is valid JSONL (each line parses as JSON; first line has type in `{"last-prompt", "permission-mode"}`).
5. Try to actually resume: `subprocess.run(["claude", "--resume", fork_sid, "--print", "exit"], cwd="/tmp/croam-e2e", env={"HOME": str(tmp_path/"croam-e2e"), ...}, capture_output=True, timeout=15, text=True)`.
   - **Capture this interface explicitly** (see "External Interfaces Consumed" below). The exit code, stdout, and stderr of `claude --resume <fork_sid> --print 'test'` are the empirical answer to spec section 15.
   - If `claude --resume` exits 0 with the prompt's response: PASS, claude does not enforce cwd consistency for forks (or the cwd already matches because we're cwd'd into /tmp/croam-e2e).
   - If `claude --resume` exits non-zero with a cwd-mismatch error: FAIL the test, document the exact stderr in your phase summary, and update CODEBASE_CONTEXT.md to say claude DOES enforce cwd. This means Phase 8's `--here` surgical-rewrite path is the only way to do --here forks.
   - If `claude --resume <sid> --print 'test'` itself fails for unrelated reasons (claude bug, --print not supported with --resume, etc.): document in summary, mark this assertion `pytest.xfail("known claude limitation: ...")`, and capture the stderr verbatim so future phases can act on it.
6. Cleanup: `tmp_path` cleanup is automatic. Do NOT touch `/tmp/croam-e2e/` (read-only).

The test's success bar: the FORK operation produces a valid JSONL that `claude --resume` accepts (exit 0). The format of the prompt-response is irrelevant; we only care that claude found and loaded the transcript.

### 10.9 `test_shim_real_tmux.py`

This test uses real tmux but on a private socket -- it does NOT touch the user's tmux server.

```python
def test_shim_launches_real_tmux_session(home, tmux_socket, monkeypatch): ...
```

1. Place a fake `claude-real` on PATH that just sleeps: write a shell script to `tmp_path/bin/claude-real` with content `#!/bin/sh\nexec /bin/sleep 5\n`, `chmod +x`, prepend `tmp_path/bin` to PATH.
2. Set `CROAM_TMUX_SOCK=<tmux_socket>` (or whatever env var Phase 5 uses to override the socket).
3. Run `commands.launch.run(args=[], ...)` (or the equivalent shim entry point).
4. Verify with `subprocess.run(["tmux", "-S", str(tmux_socket), "ls", "-F", "#{session_name}"])` that there is a session named `claude-<some-uuid>`.
   - **Capture this interface explicitly** (see "External Interfaces Consumed").
   - The session name format `claude-<sid>` comes from Phase 5's tmux module; assert exact match via regex `^claude-[0-9a-f-]{36}$`.
5. Cleanup (mandatory, even on failure): `subprocess.run(["tmux", "-S", str(tmux_socket), "kill-server"])` in a try/finally. The `tmux_socket` fixture from root conftest may also kill on teardown -- verify by reading the fixture before relying on it.

Edge case: if the launcher exec()s tmux directly (as the spec suggests), the test cannot just call `commands.launch.run(...)` because exec() replaces the process. Use `--no-exec` or whatever Phase 5 uses to separate "build the argv" from "actually exec". If Phase 5 didn't add a `--no-exec` for the launcher, this test instead spawns the launcher in a subprocess and verifies tmux state from outside.

### 10.10 `test_orphan_handling.py`

Three tests under `class TestOrphanHandling`:

```python
def test_orphan_hidden_by_default(two_host_env): ...
def test_orphan_listed_with_orphans_flag(two_host_env): ...
def test_orphan_claim_refused(two_host_env): ...
def test_orphan_fork_allowed(two_host_env): ...
```

Setup for all four: in `two_host_env.stormtree.home`, write a JSONL at `~/.claude/projects/-home-tunc-Programs-orphan/<orphan_sid>.jsonl` but do NOT write an assertion in `ownership.json`. This is an orphan.

Test 1: `commands.ls.run(ctx_obj={"orphans": False, ...}, ...)` returns rows that do NOT contain `orphan_sid`.

Test 2: `commands.ls.run(ctx_obj={"orphans": True, ...}, ...)` returns rows that DO contain `orphan_sid`, with a marker like `"orphan": true` in the JSON output.

Test 3: `commands.claim.run(sid=orphan_sid, ...)` raises `OrphanRefused` (per Phase 1's `errors.py`). The CLI top-level catches this and prints a one-liner; verify by running through the CLI: `runner.invoke(app, ["claim", orphan_sid])` -> `result.exit_code != 0`, stderr contains "orphan" and "fork".

Test 4: `commands.fork.run(sid=orphan_sid, ...)` succeeds. Verify the new fork sid has its own assertion (`action=create`) and lineage entry (`parent_sid=orphan_sid, fork_n=1`).

### 10.11 Coverage assertion

After all integration tests pass, run:

```bash
uv run pytest --cov=croam --cov-report=term-missing tests/
```

Read the final coverage line. The TOTAL line should be `>= 80%`. If lower, either:
- Add more unit tests in the relevant phase's test file (NOT in `tests/integration/` -- integration is for end-to-end). Document which module is under-covered in your phase summary and recommend a follow-up phase.
- If the missing coverage is in a clearly-deferred area (e.g., `--debug` log file rotation, error formatting), document it as expected.

Add a test that asserts on the coverage:

```python
# tests/integration/test_coverage.py
import subprocess
import re

def test_overall_coverage_at_least_80():
    result = subprocess.run(
        ["uv", "run", "pytest", "--cov=croam", "--cov-report=term", "tests/"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0
    m = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", result.stdout, re.M)
    assert m, f"could not find coverage TOTAL line in:\n{result.stdout}"
    pct = int(m.group(1))
    assert pct >= 80, f"coverage {pct}% < 80%"
```

Note: this test will recursively invoke pytest. To avoid infinite recursion, either skip it under nested invocation (check an env var the outer pytest sets, e.g., `CROAM_COVERAGE_RECURSION=1`) or place it in a separate session (run it manually as a final step rather than inside the test suite). The simpler approach: do NOT make it a test; instead, document that the coverage check is a manual gate in the phase summary's "Completion verification" section, and run it explicitly via:

```bash
uv run pytest --cov=croam --cov-report=term-missing tests/
```

Then paste the TOTAL line into the phase summary as evidence.

### 10.12 CODEBASE_CONTEXT.md update

At the end of the phase, append a section to `CODEBASE_CONTEXT.md` titled `## Empirical findings from Phase 10 integration` with these subsections:

1. **Encoded-cwd verification against real dummy**: state whether `paths.encode_cwd("/tmp/croam-e2e")` matched the directory name actually present in `/tmp/croam-e2e/.claude/projects/`. Quote the directory name verbatim. If they match: confirm. If not: state the actual encoding rule observed and flag it as a bug to fix in a follow-up.
2. **`claude --resume <sid>` non-interactive behavior**: paste the exact stdout/stderr from `claude --resume <fork_sid> --print 'test'` in the fork test. Note the exit code. Note any caveats (e.g., `--print` not supported with `--resume`, requires interactive TTY, etc.). This is what future phases need to know if they want to programmatically verify resume.
3. **Cwd enforcement on resume verdict (final)**: cross-reference Phase 8's summary on the question. State the verdict: "claude does NOT enforce recorded cwd on resume" OR "claude DOES enforce; --here requires surgical JSONL rewrite". Phase 10 either confirms or contradicts Phase 8's verdict via the fork-and-resume test. If contradictions arise, document both observations and recommend a Phase 11 follow-up to investigate.
4. **Two-host fixture pattern (for future test phases)**: paste the public surface of `tests/integration/conftest.py:two_host_env` so future phases can reuse it without re-reading the implementation.

Update `CODEBASE_CONTEXT.md`'s `Last updated by:` header to `Phase 10 - Integration tests round 1 (2026-04-30)`.

### 10.13 Edge cases (explicit list)

- Sid with uppercase hex chars: claude generates lowercase uuid4, but a fork could in theory yield uppercase if our uuid generator doesn't normalize. Test that `commands.fork.run` writes the lineage with the same case as the new uuid (no normalization expected -- claude uses lowercase, so we should too; fail loudly if uuid4 ever returns uppercase).
- Sid prefix collision: two sessions starting with `abcd1234`. Picker prefix-resolution should refuse and ask for full sid, OR use the longer match. Test depends on what Phase 6 implemented; verify behavior with a synthetic 2-session collision.
- HOME with trailing slash (`tmp_path/home/`): make sure `paths.encode_cwd` is robust to this. Already covered by Phase 2 unit tests but adding one integration assertion is cheap.
- `--all` with one host unreachable: should still return rows for the reachable host(s), with the unreachable host's rows showing glyph `O` (capital, indicating last-known-but-currently-unreachable) per Phase 6's row layout.
- Conflict file in stormtree's own subdir (not vicar's): doctor should still report it. Test: place a conflict file at `stormtree.state_root/STORMTREE/ownership.sync-conflict-...json` and verify doctor flags it.
- Empty mirror (vicar's state_root subdir doesn't exist on stormtree): `read_peer_state_from_mirror` returns None per Phase 9; `--all` should not crash; should report vicar as "unknown state, last-reachable=never".
- Two simultaneous claims (unobservable in Tier 1 since tests are single-process; document as an acknowledged limitation in the phase summary).

---

## Dependencies

**Requires**:
- Phase 1: harness fixtures (`home`, `tmux_socket`, `ssh_shim`, `state_root`, `e2e_dummy`, conftest guard, `synth_jsonl.py`)
- Phase 2: `paths.encode_cwd`, `Config`, `load_config`
- Phase 3: `sessions.discover_local_sessions`, `hosts.probe_reachability`, `hosts.emit_state`
- Phase 4: `ownership.read_local_assertions`, `merge_assertions`, `flatten_local`, `synth_assertions.py` helper
- Phase 5: `tmux` module, `shim` module, `commands.launch`
- Phase 6: `cli.app`, `picker.render_rows`, `picker.launch_picker`
- Phase 7: `commands.attach`, `commands.peek`, `commands.ls`, `--no-exec` flag on every verb
- Phase 8: `commands.claim`, `commands.fork`, `commands.release`, `commands.reconcile`, the cwd-enforcement verdict
- Phase 9: `sync.read_peer_state_from_mirror`, `sync.detect_conflict_files`, `sync.mirror_freshness`, `doctor.run_doctor`

**Enables**:
- Phase 11: polish/install/README -- relies on Phase 10 confirming acceptance criteria 1-8 from spec section 16. Phase 11 cites Phase 10's coverage report and CODEBASE_CONTEXT empirical findings.

---

## Completion Criteria

- [ ] `tests/integration/__init__.py` and `tests/integration/conftest.py` exist with `two_host_env` fixture
- [ ] All 8 integration test files exist (`test_two_host_picker.py`, `test_two_host_claim.py`, `test_two_host_offline.py`, `test_doctor_full.py`, `test_e2e_dummy_attach.py`, `test_e2e_dummy_fork.py`, `test_shim_real_tmux.py`, `test_orphan_handling.py`)
- [ ] `uv run pytest tests/integration -v` exits 0 in under 30 seconds (Tier 1, no `CROAM_E2E`)
- [ ] `CROAM_E2E=1 uv run pytest tests/integration -v` exits 0 (or has only documented `xfail`s for known claude limitations) within 60 seconds
- [ ] `uv run pytest --cov=croam --cov-report=term-missing tests/` reports TOTAL coverage >= 80%
- [ ] `tests/conftest.py` (root) is unchanged
- [ ] No file under `src/croam/` is modified
- [ ] `CODEBASE_CONTEXT.md` has the "Empirical findings from Phase 10 integration" section with all 4 subsections filled in
- [ ] Phase summary in `summaries/PHASE_10_SUMMARY.md` includes:
  - The exact `pytest --cov` TOTAL line
  - The captured `claude --resume` interface output
  - The captured `tmux ls` interface output
  - The cwd-enforcement final verdict
  - Any test marked `xfail` with reason
  - Any source bug discovered (in a "Findings" section, not silently patched)

---

## Testing Requirements

This phase IS the testing phase. The "tests" of this phase are the tests it produces; the "verification" is that they all pass green and that coverage hits the bar.

Run order (in CI or manually):

1. `uv run pytest tests/integration/test_two_host_picker.py -v` -- fastest sanity check
2. `uv run pytest tests/integration/test_two_host_claim.py -v`
3. `uv run pytest tests/integration/test_two_host_offline.py -v`
4. `uv run pytest tests/integration/test_doctor_full.py -v`
5. `uv run pytest tests/integration/test_orphan_handling.py -v`
6. `uv run pytest tests/integration/test_shim_real_tmux.py -v` -- requires real tmux installed
7. `CROAM_E2E=1 uv run pytest tests/integration/test_e2e_dummy_attach.py tests/integration/test_e2e_dummy_fork.py -v` -- requires real claude installed and the dummy at /tmp/croam-e2e/
8. Final: `uv run pytest --cov=croam --cov-report=term-missing tests/` for coverage

Expected timing:
- Steps 1-5: each < 5s
- Step 6: 5-10s (real tmux startup/teardown)
- Step 7: 10-30s (real claude resume)
- Step 8: < 30s (full suite)

Total wall time for full integration verification: ~60s.

---

## Functional QA

Phase 10 IS the functional QA phase for the entire project. Each test below references a User Loop in `FUNCTIONAL_QA_STRATEGY.md`.

- [ ] (Surface 1: CLI verbs, Loop B: cross-host attach) `commands.attach.run(sid=<vicar_sid>, here_on_owner=False, home=stormtree.home, ...)` with `CROAM_NO_EXEC=1` returns planned argv `["ssh", "vicar", "croam", "attach", "<vicar_sid>", "--here-on-owner"]`. Captured argv pasted into summary's "Functional QA Results" section.
- [ ] (Surface 1: CLI verbs, Loop C: claim ownership) Full claim handshake on synthetic two-host fixture: stormtree's ownership.json after `commands.claim.run(<vicar_sid>)` contains `owner=stormtree, action=claim, previous_owner=vicar`; the JSONL exists locally on stormtree; the SSH log shows `croam release <vicar_sid> --requester stormtree` was issued. All three observable outcomes asserted in `test_claim_remote_session_full_handshake`. Paste the final ownership.json bytes and the SSH log into the summary.
- [ ] (Surface 1: CLI verbs, Loop D: forced claim) With `ssh vicar true` returning 255, `commands.claim.run(<vicar_sid>)` succeeds when user inputs `y`; stormtree has the JSONL from the mirror; a "claimed away" record exists. Asserted in `test_forced_claim_origin_unreachable`.
- [ ] (Surface 1: CLI verbs, Loop F: peek) Not specifically re-tested in Phase 10 (Phase 7 covered it). If coverage reveals gaps in `commands.peek.run`, add an integration test for `peek` against the synthetic mirror. Document if this comes up.
- [ ] (Surface 1: CLI verbs, Loop G: doctor) Clean two-host fixture -> `doctor.run_doctor` exit 0; corrupted state with conflict file -> exit non-zero with `[FAIL]` line. Asserted in `test_doctor_clean_two_host_setup` and `test_doctor_conflict_file_fails`. Paste full doctor stdout for the FAIL case into summary.
- [ ] (Surface 2: fzf picker) Picker rendering against two-host fixture: stormtree's render_rows output includes vicar's session row with the right glyph and host column. Asserted in `test_stormtree_picker_shows_vicar_session`. Note: this is the `render_rows` API surface, NOT a real fzf invocation -- real fzf is exercised in Phase 6's tests, not here.
- [ ] (Surface 3: claude shim) Real tmux on private socket: `commands.launch.run([])` creates a tmux session named `claude-<uuid>`; verified by `tmux -S <socket> ls -F "#{session_name}"`. Asserted in `test_shim_launches_real_tmux_session`. Paste the captured `tmux ls` output into summary.
- [ ] (Surface 4: per-host state files) Two-host claim mutates ownership.json correctly on both sides. Asserted across the claim and offline tests. Paste before/after state file diffs into summary.

Anti-patterns to watch for in this phase (from `FUNCTIONAL_QA_STRATEGY.md`):
- **Anti-pattern A** (HOME not redirected): every integration test takes the `home` fixture or `two_host_env`. If you write a test that doesn't, the conftest guard will halt the run -- DO NOT bypass the guard.
- **Anti-pattern B** (mocking SSH subprocess): the integration tests use the real `ssh_shim` (a fake `ssh` binary on PATH). Do not `monkeypatch.setattr` over `subprocess.run`.
- **Anti-pattern C** (mocking tmux): `test_shim_real_tmux.py` uses real tmux on a private socket -- do not mock `tmux.has_session` or similar in this test.
- **Anti-pattern G** (claim non-atomicity): the claim test verifies state across all 4-5 handshake steps, not just the end state. Inject failures at step boundaries in a follow-up test if you find Phase 8 doesn't handle them.

---

## External Interfaces Consumed

This phase consumes external interfaces ONLY in Tier 2 tests (CROAM_E2E=1). Tier 1 tests use synthetic fixtures and consume nothing external beyond what their owning module already wraps.

- **`claude --resume <sid> --print '<prompt>'` non-interactive behavior**
  - **Consumed by**: `tests/integration/test_e2e_dummy_fork.py`
  - **How to capture**: After running `commands.fork.run` against the cloned dummy, run:
    ```bash
    cd /tmp/croam-e2e && claude --resume <fork_sid> --print 'test' 2>&1
    echo "exit=$?"
    ```
    Where `<fork_sid>` is the new sid returned by the fork. Capture full stdout, stderr, and exit code. Paste into phase summary's "Evidence Captured" section verbatim. The user expects this to inform whether claude can be programmatically verified to resume; if `--print` is incompatible with `--resume`, document the exact failure and use a different probe (e.g., `claude --resume <fork_sid> </dev/null` with timeout 5s and check exit code only).
  - **If not observable**: if `claude` is not installed, the test is skipped via `@pytest.mark.skipif`. Phase 10 still passes Tier 1; the cwd-enforcement verdict carries over from Phase 8's documentation in CODEBASE_CONTEXT.md unchanged.

- **Real tmux on private socket: `tmux -S <socket> ls -F "#{session_name}"`**
  - **Consumed by**: `tests/integration/test_shim_real_tmux.py`
  - **How to capture**: After `commands.launch.run([])` returns, run:
    ```bash
    tmux -S <tmux_socket> ls -F "#{session_name}"
    ```
    Where `<tmux_socket>` is the value of the `tmux_socket` fixture. Expected output: one line `claude-<uuid>` matching `^claude-[0-9a-f-]{36}$`. Capture and paste into phase summary.
  - **If not observable**: if `tmux` is not installed, fail Phase 10 -- tmux is a hard dependency declared in `pyproject.toml`'s "External tool dependencies" section (per Phase 1) and the project cannot ship without it. Document the failure clearly so the user can install tmux.

---

## Notes

- This phase touches NO code under `src/croam/`. If you find a source bug while writing tests, document it in the phase summary's "Findings" section and recommend a fix in a follow-up phase. Do NOT silently patch source. The integrity of Phase 10 as a verification pass depends on it not modifying what it verifies.
- The two-host fixture is the most novel mechanic in this phase. Get it right first (write `conftest.py` and one trivial test that just instantiates `two_host_env` and asserts both subdirs exist), THEN build on it. If the fixture is wrong, every test built on it is wrong.
- Tier 2 tests are gated cleanly: when `CROAM_E2E` is unset, they skip with a `Tier 2 only` reason printed by pytest. Verify this by running `uv run pytest tests/integration -v` (without the env var) and seeing the skip messages.
- The `claude --resume` exec is the only place in this entire test phase where a real external tool is actually invoked with side effects. Be cautious: use a 15s timeout, capture all output, and ALWAYS run from `cwd=/tmp/croam-e2e` to ensure cwd matches the original (so any cwd-enforcement does not mask other failures).
- Coverage is a project-wide metric. If Phase 10 reveals that some module is at 60%, the fix is NOT to write integration tests for the missing parts -- it's to add unit tests in that module's own test file in a follow-up. Document under-covered modules in the phase summary.
- `CODEBASE_CONTEXT.md` updates are a hard deliverable. Without them, the open questions from spec section 15 remain unanswered in the project's living documentation, and Phase 11 will reopen them.
- If Phase 8 chose to extend the `Assertion` dataclass with `transcript_lines_at_assertion` (vs. a separate `snapshots.json`), the `test_outclaim_*` tests in Phase 10 must follow that choice. Read `summaries/PHASE_08_SUMMARY.md` first.
- The acceptance criteria mapping (spec section 16) for Phase 10:
  - Criterion 1 (single-host picker in $PWD): covered indirectly by `test_picker_filter_pwd_excludes_other_cwds`
  - Criterion 2 (shim launches in tmux): `test_shim_launches_real_tmux_session`
  - Criterion 3 (two-host `--all` and `attach`): `test_two_host_picker.*`
  - Criterion 4 (`croam claim` transfers ownership): `test_claim_remote_session_full_handshake`
  - Criterion 5 (`croam fork` lineage): `test_fork_dummy_resumable` plus Phase 8 unit tests
  - Criterion 6 (forced claim with origin offline): `test_forced_claim_origin_unreachable` plus `test_forced_claim_writes_claimed_away_marker`
  - Criterion 7 (`croam doctor` reports all): `test_doctor_full.*`
  - Criterion 8 (test suite covers ownership merge, paths, reconciliation, shim, multi-select): the COVERAGE assertion at >= 80% is the proxy; supplement with explicit greps if any of these modules are below 70% individually
- After Phase 10 completes successfully, the project should be on the verge of "v1 ready". Phase 11 only needs to add the install path, README, and the cctakeover transition shim.
