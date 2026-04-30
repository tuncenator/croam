# Functional Verification Strategy

> Per-feature artifact. Captures HOW to prove croam works from a real user's
> perspective. Read by phase planners (to write phase-specific functional
> checks) and coding agents (to verify their work).
>
> Visual concerns are universal across UIs and live in `VISUAL_QA_CHECKLIST.md`.
> croam is mostly non-visual (it's a CLI), but the fzf picker has visual aspects
> that Phase 6 covers via screenshot+manual review against the dummy fixture.
> The bulk of verification is functional: did the right state transitions happen,
> did the right SSH commands fire, did the right tmux session get created.
>
> **Living document.** Phases that uncover new surfaces, new harness needs, or
> new anti-patterns update this file before completing.
>
> **Last updated by**: Phase 0 - Initial Setup (2026-04-30)

---

## Surface Inventory

croam exposes four user-facing surfaces. Each has a different verification
shape; phases that touch a surface must use the matching mechanics.

### Surface 1: CLI verbs (the primary surface)

- **What it is**: a typer-based CLI with verbs `croam`, `croam ls`, `croam attach <sid>`, `croam peek <sid>`, `croam claim <sid>`, `croam fork <sid>`, `croam launch [args...]`, `croam doctor`, plus the hidden `croam emit-state`.
- **Who calls it**: the user from any shell on any configured host. Also: croam itself, recursively, over SSH (e.g., `croam attach <sid>` SSHes to the owner and runs `croam attach <sid> --here-on-owner` there).
- **Entry point**: `src/croam/cli.py:app` (typer instance), wired via `[project.scripts] croam = "croam.cli:app"` in pyproject.toml.
- **In scope for this feature**: all verbs are new -- this is a greenfield project. Each phase ships one or more verbs.

### Surface 2: The fzf picker (the interactive layer)

- **What it is**: a fzf-based row picker invoked when the user types `croam` with no verb (or `croam ls` with no `--json`). Shows tab-delimited rows of sessions, supports multi-select with `Tab`, dispatches to verbs via `--expect=p,c,f,C,F,ctrl-r` and the implicit Enter key.
- **Who calls it**: the user, interactively. Always launched from a terminal with a tty; non-tty contexts must NOT invoke the picker (use `--json` instead).
- **Entry point**: `src/croam/picker.py:launch_picker(rows, filter_pwd)` -- consumed by `cli.py:cmd_default()` (no-verb invocation) and `cli.py:cmd_ls()` (when interactive).
- **In scope**: picker is new in Phase 6.

### Surface 3: The claude shim (`croam launch`)

- **What it is**: a thin wrapper around the real `claude` binary. When invoked from the user's shell as `croam launch [args...]` (or via the `claude` alias they set up in `.zshrc`), it decides whether to wrap the launch inside a `tmux new-session -d -s claude-<sid>` or pass through.
- **Who calls it**: the user, every time they type `claude` (after they've installed the alias). Also: croam itself, when an `attach` finds a sid that is owned-but-not-running (kill+relaunch in tmux).
- **Entry point**: `src/croam/shim.py:should_wrap(argv, env, stdin_isatty)` and `src/croam/shim.py:derive_sid(argv, env)`, dispatched from `cli.py:cmd_launch()`.
- **In scope**: new in Phase 5.

### Surface 4: Per-host state files (the inter-host wire format)

- **What it is**: the JSON files under `<state_root>/<HOSTNAME>/` (`ownership.json`, `lineage.json`, `host-cache.json`). These are not "user-facing" in the click-button sense, but they ARE the contract between hosts -- if host A writes a malformed `ownership.json`, host B cannot read it correctly. They are the wire format.
- **Who reads them**: croam on every host, on every invocation (during the read-time merge), via syncthing mirror or SSH `--emit-state` fanout.
- **Entry point**: `src/croam/ownership.py:read_local_assertions()`, `merge_assertions()`, `flatten_local()`. Schema documented in `CODEBASE_CONTEXT.md` Data Models section.
- **In scope**: new in Phase 4.

croam does NOT expose: HTTP APIs, web UIs, message queues, or library imports for downstream Python consumers (it is a leaf application). Visual concerns apply only to Surface 2 (the fzf picker layout) and are covered by Phase 6's Visual QA section against the dummy fixture.

---

## User Loop

### Loop A: First-run sanity (new install, single host)

User installs croam (`uv tool install --editable [PROJECT_ROOT]`), runs `croam doctor`. They observe:

- `[OK] config: ~/.config/croam/config.toml exists and parses`
- `[OK] hosts: 1 configured (self only)`
- `[OK] state_root: ~/.local/share/croam writable`
- `[OK] tmux: 3.5a on PATH`
- `[OK] fzf: 0.65.x on PATH`
- `[OK] claude: on PATH at /usr/bin/claude`
- Exit 0

Then they run `claude` (which is now the croam shim alias). Behind the scenes: shim generates a uuid4 sid, execs `tmux new-session -d -s claude-<sid> claude-real`, `croam.cli` writes `ownership.json` with `action="create"`. User sees the claude REPL, types something. Exits.

Now `croam` (no verb): fzf picker opens, shows one row -- the session they just created -- with status glyph `o` (host reachable, idle), CWD column matching `$PWD`. They press `Enter`: croam dispatches `attach <sid>`. Since the session is not currently running (claude exited), croam re-launches via tmux + `claude --resume <sid>` and attaches the user's terminal.

**Observable outcomes:** `croam doctor` exits 0 with green checks; `croam` shows a non-empty fzf with a row matching the just-created sid; pressing Enter reattaches to a tmux session named `claude-<sid>` and the user types in it normally.

### Loop B: Cross-host attach (two hosts, both reachable)

User on VICAR ran `claude` earlier (shim wraps in `tmux new-session -d -s claude-<sid>`); session is currently `idle` on VICAR.

Now user is on STORMTREE in a new shell. They run `croam --all` (or `croam` with `[picker.default_filter] = "exact-pwd"` matching). Picker shows the session on VICAR with glyph `o`, host column `vicar`. They press `Enter`.

Behind the scenes: croam sees ownership = vicar; vicar is reachable (SSH probe succeeded); croam SSHes `vicar` and runs `croam attach <sid> --here-on-owner`. Vicar-side croam sees ownership = self, runs `tmux has-session -t claude-<sid>`, finds it, execs `tmux attach -t claude-<sid>`. The user's STORMTREE terminal is now attached to vicar's tmux session.

**Observable outcomes:** picker row appears with `host=vicar`; `Enter` results in attached tmux on vicar (verifiable: `tmux ls` on vicar shows `claude-<sid> (attached)`); the user can interact with claude on vicar through the SSH terminal.

### Loop C: Claim ownership

User on STORMTREE wants to take a session that is owned by VICAR. They `croam claim <sid>`. With ssh-strict (default):

1. STORMTREE croam SSHes every reachable peer (VICAR, CORPSEFIRE) and fetches `croam --emit-state` JSON. Merges with local view.
2. Confirms the sid is currently owned by vicar (no conflicting later assertion exists).
3. STORMTREE croam SSHes vicar with `croam release <sid>` -- vicar stops the live process if running (`tmux kill-session -t claude-<sid>`), removes the JSONL from its local `~/.claude/projects/.../<sid>.jsonl`, marks its own assertion as `action="release"`.
4. STORMTREE croam copies the JSONL from vicar (over scp or cat over SSH) to local `~/.claude/projects/<encoded-stormtree-cwd>/<sid>.jsonl`.
5. STORMTREE croam writes its own `ownership.json` with `action="claim"`, `previous_owner="vicar"`, `asserted_at=<now>`.

**Observable outcomes:** after the claim, on STORMTREE: `croam ls --json` shows the session with `owner=stormtree`. On VICAR: `croam ls --json` shows the session with `owner=stormtree` (read-time merge picks up STORMTREE's later assertion via syncthing). The JSONL exists on STORMTREE and not on VICAR.

### Loop D: Forced claim (origin offline)

User on STORMTREE wants a session whose origin (CORPSEFIRE) is currently unreachable. They run `croam claim <sid>`. ssh-strict tries CORPSEFIRE, fails to reach it, prints a warning and asks for confirmation. User confirms. croam:

1. Reads CORPSEFIRE's last-known `ownership.json` from the syncthing mirror.
2. Copies the JSONL from `<state_root>/corpsefire/projects/<encoded>/<sid>.jsonl` (the syncthing mirror).
3. Writes STORMTREE's own assertion with `action="claim"`, `previous_owner="corpsefire"`.
4. Writes a "claimed away" marker for corpsefire to reconcile when it returns.

**Observable outcomes:** STORMTREE shows ownership=stormtree. When CORPSEFIRE comes back online and runs `croam ls`, it detects its own assertion was superseded; if its local JSONL has lines added after the claim's `asserted_at`, croam prompts fork-or-discard.

### Loop E: Fork

User wants to branch a session. `croam fork <sid>`:

1. Generates new uuid4 (call it `fork-sid`).
2. Copies the JSONL: `~/.claude/projects/<encoded>/<sid>.jsonl` -> `~/.claude/projects/<encoded>/<fork-sid>.jsonl`.
3. Writes `lineage.json` entry: `{fork-sid: {parent_sid: sid, fork_n: 1}}`.
4. Writes `ownership.json` entry: `{fork-sid: {owner: <self>, action: "create", cwd_normalized: ...}}`.

**Observable outcomes:** `croam ls` shows both rows; the forked one has `[abc123-F#1]` suffix in the name column. Both can be attached independently.

### Loop F: Peek (read-only)

`croam peek <sid>` for a session whose origin is reachable: croam SSHes owner with `tmux attach -r -t claude-<sid>` (read-only mode). Owner-side keystrokes don't propagate. User can scroll the conversation view but cannot type.

For unreachable origin: croam falls back to rendering the static JSONL from the syncthing mirror in a TUI (less, bat, or built-in renderer).

**Observable outcomes:** read-only attach prevents typing (verifiable: trying to send keystrokes does nothing); static render shows the conversation history with no live updates.

### Loop G: Doctor diagnoses

`croam doctor` exercises every layer once. With a deliberately broken config (e.g., a host entry pointing at a non-existent SSH alias), it should print:

- `[FAIL] hosts: vicar -- ssh: Could not resolve hostname vicar-typo`
- `[OK] state_root: ~/Sync/croam writable, syncthing healthy (peer subdirs mtimed within 1h)`
- `[WARN] ownership: 1 conflicting assertion (sid=<x>): stormtree(2026-04-30T10:00) and vicar(2026-04-30T10:01); merged view honors vicar but stormtree retains the JSONL`
- Exit non-zero (some `[FAIL]` present)

**Observable outcomes:** doctor's output enumerates each diagnostic with `[OK|WARN|FAIL]` + reason; exit code is 0 iff zero `[FAIL]`s.

---

## Verification Mechanics

The bulk of croam verification happens via the synthetic Tier 1 fixtures. A
small minority of high-stakes assertions are also exercised against the real
disposable dummy session in Tier 2.

### Mechanism for Surface 1: CLI verbs

- **typer.testing.CliRunner**: in-process invocation. `runner.invoke(app, ["ls", "--json"])` returns `result.exit_code`, `result.stdout`, `result.stderr`. Use `mix_stderr=False` to separate them. Fast, deterministic, runs entirely in pytest.
- **subprocess invocation against the installed CLI**: `subprocess.run(["uv", "run", "croam", "ls", "--json"], capture_output=True, text=True)`. Slower but exercises the real entry-point wiring (console-script -> typer). Use sparingly -- one or two integration tests per verb is enough.

### Mechanism for Surface 2: fzf picker

- The picker wraps `subprocess.Popen([...fzf...])`. Tests cannot drive the interactive UI directly. Two test strategies:
  1. **Unit test**: pass a synthetic `list[PickerRow]` to `picker.render_rows()` (or whatever the public function is); assert on the resulting tab-delimited input string that would be fed to fzf's stdin. Verify column ordering, hidden filter tokens, multi-select header content.
  2. **End-to-end test (rare, marked slow)**: invoke the picker with a mock fzf binary (a shell script on PATH that reads stdin, ignores it, prints back a known selection on stdout, exits 0). Verify Python parses the result correctly.

### Mechanism for Surface 3: claude shim

- The shim's decision logic (`should_wrap`, `derive_sid`) is a pure function over (argv, env, stdin_isatty). Test directly with synthetic inputs. Hundreds of tests, microseconds each.
- The actual `exec_tmux_new` call is tested by the tmux harness:
  - Private socket: `tmux -S <tmp_path>/sock`
  - Real `tmux new-session -d -s claude-<sid> -- /bin/sleep 5` (a no-op program substituting for `claude-real`)
  - Verify `tmux has-session -t claude-<sid>` returns 0
  - `tmux kill-session -t claude-<sid>` to clean up

### Mechanism for Surface 4: per-host state files

- Pure JSON read/write/merge. Test with synthetic `tmp_path`-rooted state_root, multiple hostname subdirs, write assertion files by hand, run merge, assert on output.
- Atomicity test: write a partial file, simulate a crash mid-write, run croam, ensure it doesn't crash on malformed JSON (it should warn and skip the broken file, not propagate the parse error to the picker).

### The shared test harness (Phase 1 deliverable)

- `home` fixture: builds a `tmp_path/home/` tree mirroring the user's real `~/.claude`, `~/.config`, `~/.local/{share,state}`. Sets `monkeypatch.setenv("HOME", str(tmp_path / "home"))`.
- `tmux_socket` fixture: returns `tmp_path / "tmux.sock"`. Tests pass it as `-S` to every tmux invocation.
- `ssh_shim` fixture: writes a fake `ssh` script to `tmp_path/bin/ssh`, `chmod +x`, prepends `tmp_path/bin` to `PATH`. The script reads its argv, looks up canned output by `(host, command)` key from a pytest-managed registry, prints it, exits with the registered code.
- `state_root` fixture: returns `tmp_path / "state"`. Pre-populates with synthetic per-host subdirs.
- `e2e_dummy` fixture: gated on `CROAM_E2E=1`. Returns `(/tmp/croam-e2e, "[DUMMY_SID]")`.
- **Conftest guard** (autouse): asserts `os.environ["HOME"]` is under `tmp_path` UNLESS `CROAM_E2E=1` is set. Refuses to run otherwise.

Concrete Tier 1 example (Phase 7 attach test):

```python
def test_attach_local_session_dispatches_tmux(home, tmux_socket, monkeypatch):
    sid = "abc12345-6789-abcd-ef01-23456789abcd"
    write_synthetic_session(home, sid, cwd=Path.cwd(), pid=99999)
    write_synthetic_assertion(home, sid, owner="self", action="create")

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    runner = CliRunner()
    result = runner.invoke(app, ["attach", sid, "--no-exec"])  # --no-exec returns the planned argv instead of execing

    assert result.exit_code == 0
    plan = json.loads(result.stdout)
    assert plan["action"] == "tmux-attach"
    assert plan["argv"] == ["tmux", "-S", str(tmux_socket), "attach", "-t", f"claude-{sid}"]
```

---

## Anti-Patterns

These are project-specific traps. Each names the trap and the way to avoid it.

### A. Tests that don't redirect HOME silently corrupt the user's real `~/.claude`

The user has 57 real claude project directories and 6 currently-running sessions. A test that calls `croam.sessions.discover_local_sessions(home=Path.home())` with the real home path will:
- Read 57 transcripts (slow, possibly leaks user data into log files)
- Possibly write to `~/.config/croam/config.toml` (overwriting the user's config)
- In the worst case, attempt to claim/fork a real session and trash the JSONL

**Avoid**: every test takes the `home` fixture which redirects HOME. The autouse conftest guard refuses to run if HOME is not redirected. NEVER override the guard. NEVER call `Path.home()` or `os.path.expanduser("~")` in test code -- those return the real home unless HOME is in the environment.

### B. Tests that mock the SSH subprocess miss real reachability semantics

If a test does `monkeypatch.setattr(croam.hosts, "subprocess.run", fake)`, it bypasses the real argv assembly, the real flag parsing, the real timeout handling. A bug in "we passed `ConnectTimeout=2.0` instead of `ConnectTimeout=2`" would slip through.

**Avoid**: use the `ssh_shim` fixture, which puts a real fake `ssh` binary on PATH. The `subprocess.run(["ssh", "host", "true"])` call goes through the OS-level dispatch, exec()s our fake ssh, which honors the actual argv. Bugs in argv assembly surface immediately.

### C. Tests that mock tmux miss session-naming and socket-isolation bugs

If `tmux.has_session()` is mocked to return `True`, you'll never catch:
- A test passing a sid with a `:` in it (would break `tmux -t claude-<sid>:colon`)
- The shim accidentally launching against the real tmux server because `-S` was forgotten

**Avoid**: real tmux against a private socket. `tmux_socket` fixture provides the path; every test passes `-S <socket>` explicitly. Verify with `tmux -S <socket> ls` after the operation.

### D. Encoded-cwd tests that don't go through the dummy fixture

The encoding rules are subtle (slashes -> dashes, AND leading-dot path components -> dashes). If the test only covers `/home/tunc/foo` -> `-home-tunc-foo`, it misses `/home/tunc/.claude` -> `-home-tunc--claude`.

**Avoid**: phase 2 paths tests must include cases harvested from the dummy fixture and from `~/.claude/projects/` real listings (a small curated subset, NOT the user's real cwds -- harvest one example of each interesting shape: bare path, hidden component, multi-hidden, path-with-dashes).

### E. Ownership merge tests that assume timezone-unaware datetimes

`asserted_at` is stored as ISO8601 UTC. If a test mixes naive and aware datetimes when comparing, the comparison raises `TypeError` (Python 3.11 strict). Worse, a future "ssh-strict" merge that fetches a peer's assertion with a non-UTC offset could silently mis-order events.

**Avoid**: every datetime comparison goes through `datetime.fromisoformat(...).astimezone(timezone.utc)`. Tests assert the UTC offset of every parsed assertion. Phase 4 must include a "mixed-offset" test case.

### F. Picker tests that only check stdout shape without exercising fzf's flag parsing

`picker.render_rows()` returns a list of dataclasses; `picker.launch_picker()` builds the fzf argv and Popen call. A unit test that only inspects the dataclasses misses bugs in the fzf flag construction (e.g., wrong `--with-nth` indices for hidden filter columns).

**Avoid**: test `picker._build_argv()` separately, asserting on the exact argv list. At least one Phase 6 test runs the real fzf binary against a fake stdin and verifies the picker correctly parses fzf's actual exit code (1 vs 130 vs 0) and stdout shape (the `--expect` first-line key behavior).

### G. Claim handshake tests that assume "claim" is atomic

The claim sequence has 4-5 steps (verify ssh-strict, release on origin, copy JSONL, write assertion, flatten). A failure between step 3 (copy) and step 4 (write assertion) leaves orphaned JSONL on the new owner without an assertion. The next `croam` invocation surfaces it as an orphan, but a naive test asserting "after claim, the new owner has the JSONL" misses the inconsistency.

**Avoid**: phase 8 tests inject failures at each handshake step boundary and verify the system recovers (or surfaces the inconsistency clearly via `croam doctor`). The test checklist names every cleanup path.

---

## Required Harness Deliverables

Phase 1 ships the harness; subsequent phases compose with it.

| Deliverable | File path | Phase | Inheritance |
|---|---|---|---|
| `home` fixture (HOME redirect, fake `~/.claude` tree) | `tests/conftest.py` | Phase 1 | All phases inherit |
| `tmux_socket` fixture (private socket path) | `tests/conftest.py` | Phase 1 | Phase 5+ uses it |
| `ssh_shim` fixture (fake ssh binary on PATH) | `tests/conftest.py`, `tests/_helpers/fake_ssh.py` | Phase 1 | Phase 3, 7, 8, 9 use it |
| `state_root` fixture (tmp-rooted, synthetic per-host subdirs) | `tests/conftest.py` | Phase 1 | Phase 4+ uses it |
| `e2e_dummy` fixture (gated on `CROAM_E2E=1`) | `tests/conftest.py` | Phase 1 | Phase 2 (paths), Phase 3 (sessions discovery), Phase 5 (shim resume), Phase 8 (--here cwd rebase) |
| Conftest guard (refuses if HOME unredirected) | `tests/conftest.py` | Phase 1 | All phases |
| Synthetic JSONL builder (`tests/_helpers/synth_jsonl.py`) | Phase 1 | Phase 3, 4, 7, 8 use it |
| Synthetic assertion builder (`tests/_helpers/synth_assertions.py`) | Phase 4 | Phase 7, 8, 9, 10 use it |

All harness lives under `tests/` and `tests/_helpers/`. None of it ships in `src/croam/`. Coding agents in Phase 2+ should `from tests._helpers.synth_jsonl import build_jsonl` (or similar) -- never replicate the fixture logic in their own test files.

---

## How Agents Use This Document

**Setup agent (you, during step 6.5)**: complete -- this document is now filled in.

**Phase planner (during step 7.5)**: read this document in full before writing each phase plan. Derive 3-7 phase-specific functional checks for each phase's "Functional QA" section. Each check must reference one of the user loops above and name the concrete invocation + observable outcome. Phases that ship one of the four surfaces above (CLI verb, picker, shim, state file) have `Functional: yes`. Pure scaffolding phases (e.g., a hypothetical "set up linter config" phase) have `Functional: no`. For croam, every phase 1-11 has `Functional: yes` because every phase ships behavior at one of the four surfaces.

**Coding agent (during phase execution)**: read this document plus your phase plan's "Functional QA" section. Run each check using the verification mechanics. Capture the actual command, the actual output, and a pass/fail verdict in your phase summary's "Functional QA Results" section. Watch for the anti-patterns listed above.

**Checkpoint agent**: validates that phase summaries for every phase include "Functional QA Results" with real surface invocations and outputs. Missing or hand-waved results = checkpoint failure.
