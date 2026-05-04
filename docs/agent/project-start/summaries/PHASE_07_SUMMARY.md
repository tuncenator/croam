# Phase 07: Verbs: attach, peek, ls - Summary

**Date Completed:** 2026-05-04
**Completed By:** claude-sonnet-4-6 (agent-a9a7f3f3aa237860b)
**Actual Token Usage:** ~120k tokens

---

## Objective

Implement the three read-mostly verbs (`attach`, `peek`, `ls`) that make up croam's primary CLI surface, wire them into `cli.py`, fill in `commands/default.py:_dispatch`, and add `transcript.py` for static JSONL rendering.

---

## Work Completed

### What Was Built

- `src/croam/transcript.py`: `render_static_transcript(jsonl_path, *, fp=sys.stdout) -> int` with `_extract_text` handling string/dict/list-block message shapes.
- `src/croam/commands/ls.py`: `run(ctx_obj, config, home) -> int` with JSON/text output, PWD filter, `--all`, `--host`, `--last`, `--orphans` support.
- `src/croam/commands/peek.py`: `run(sid, ctx_obj, config, home, *, here_on_owner, no_exec) -> int` with local tmux / local archived / remote reachable / remote unreachable mirror dispatch matrix.
- `src/croam/commands/attach.py`: `run(sid, ctx_obj, config, home, *, here_on_owner, no_exec) -> int` with recursion guard, tmux-attach/new-and-attach/ssh-recurse/SshError branches.
- `src/croam/commands/default.py`: rewrote `_dispatch` to route enter->attach, p->peek, ctrl-r->re-run, c/C/f/F->NotImplementedError("Phase 8"), multi-row iteration with action intersection check.
- `src/croam/cli.py`: filled in `cmd_ls`, `cmd_attach` (added `--no-exec`), `cmd_peek` (added `--here-on-owner`, `--no-exec`) -- only verb bodies changed, no other lines touched.

### Files Created

- `src/croam/transcript.py`
- `src/croam/commands/ls.py`
- `src/croam/commands/peek.py`
- `src/croam/commands/attach.py`
- `tests/test_transcript.py` (20 tests)
- `tests/test_ls.py` (10 tests)
- `tests/test_peek.py` (12 tests)
- `tests/test_attach.py` (10 tests)
- `tests/test_default_dispatch.py` (11 tests)

### Files Modified

- `src/croam/commands/default.py`: replaced `_dispatch` stub with full routing; updated `run_picker` call to pass `config` and `home` into `_dispatch`.
- `src/croam/cli.py`: replaced `cmd_ls`, `cmd_attach`, `cmd_peek` stubs with real implementations; added `--no-exec` to `cmd_attach` and `cmd_peek`, added `--here-on-owner` to `cmd_peek`.
- `tests/test_cli.py`: updated `test_global_debug_flag` to write a config and assert exit 0 (stub replaced, so NotImplementedError no longer raised).

### Key Design Decisions

- `render_static_transcript` passes `fp=sys.stdout` explicitly at call site in `peek.py` (not relying on the default arg) because Python evaluates default arguments at module import time, not call time, so CliRunner's patched stdout would not be seen.
- Error cases (`SessionNotFound`, `SshError`) are tested via subprocess invoking `main()` so the `CroamError -> SystemExit(2)` path in `main()` fires. `CliRunner` invokes `app()` directly and bypasses `main()`.
- `_dispatch` signature extended with `config: Config, home: Path` (was just `ctx_obj`). The existing `run_picker` call was updated to pass these through.
- `--no-exec` is honored as `CROAM_NO_EXEC=1` env var as well as explicit kwarg.
- `CROAM_TMUX_SOCK` env var is used to inject a private tmux socket in tests.

---

## Completion Criteria Status

- [x] `src/croam/transcript.py` exists with `render_static_transcript(jsonl_path, *, fp=sys.stdout) -> int` -- verified by 20 passing tests.
- [x] `src/croam/commands/{attach,peek,ls}.py` exist with public `run(...)` entry points -- verified by 32 passing tests.
- [x] `src/croam/commands/default.py:_dispatch` handles attach + peek + ctrl-r + multi-row, raises NotImplementedError for claim/fork -- verified by 11 tests in `test_default_dispatch.py`.
- [x] `src/croam/cli.py:cmd_attach`, `cmd_peek`, `cmd_ls` call into new modules. No other lines touched -- verified by `git diff` showing only the three command bodies changed.
- [x] All tests pass: 272 passed, 2 skipped (expected Tier 2 skips).
- [x] Coverage >= 90%: transcript 100%, attach 93%, ls 96%, peek 90%.
- [x] `uv run croam ls --json` against synthetic fixture returns parseable JSON -- verified in Functional QA.
- [x] `uv run croam attach <sid> --no-exec` against synthetic local session returns planned tmux argv -- verified in Functional QA.
- [x] No `print()` in production code except where stdout IS the protocol.
- [x] No `Path.home()` or `os.path.expanduser("~")` in new production code.
- [x] All paths normalized via `paths.encode_cwd` / `paths.denormalize_cwd`.

### Deviations / Incomplete Items

- The execvp lines (L100-101 in attach, L87-88/97-98/126-127/140-141 in peek) are structurally untestable in unit tests since they replace the current process. These account for the gap between measured coverage and 100%.
- `test_peek_local_archived_renders` passes output check via `result.output` (works because `fp=sys.stdout` is passed explicitly, making CliRunner's captured stdout the target).

---

## Testing

### Tests Written

- `tests/test_transcript.py`: 20 tests covering `_extract_text` (6 shape variants), file missing (1), empty file (1), metadata-only (1), user/assistant messages (4), skip other types (1), unicode (1), malformed line skip (1), multiple records (1), OSError (1), blank lines (1), non-dict JSON (1).
- `tests/test_ls.py`: 10 tests covering empty state, one local session schema, text mode, PWD filter, `--all`, `--host`, orphans hidden, orphans with flag, `--last` window, zero-state exit 0.
- `tests/test_peek.py`: 12 tests covering local live (tmux-peek), local archived (static-transcript path/render), remote reachable (ssh-recurse), remote unreachable mirror (action + render), remote unreachable no mirror (SshError), sid not found, here_on_owner, peer_alias fallback, mirror render no-exec.
- `tests/test_attach.py`: 10 tests covering local running (tmux-attach), local archived (new-and-attach), remote reachable (ssh-recurse), remote unreachable (SshError), recursion guard, sid not found, picker fallback, direct run() sid-not-found, direct run() remote-unreachable, peer_alias fallback.
- `tests/test_default_dispatch.py`: 11 tests covering enter->attach, p->peek, ctrl-r->re-run, c/C raises Phase 8, f/F raises Phase 8, unknown key returns 0, multi-row attach, multi-row action not in intersection, multi-row peek.

### Test Results

```
$ uv run pytest -v 2>&1 | tail -10
SKIPPED [1] tests/test_paths.py:298: needs real claude
SKIPPED [1] tests/test_sessions.py:520: CROAM_E2E=1 not set; skipping Tier 2 dummy-session test
======================== 272 passed, 2 skipped in 3.79s ========================
```

### Manual Testing

All Functional QA checks run via `runner.invoke(app, ...)` in-process. See Functional QA Results below.

---

## Evidence Captured

### `croam emit-state` JSON shape

- **How captured**: `runner.invoke(app, ["emit-state"])` with synthetic HOME containing one JSONL
- **Captured on**: 2026-05-04, synthetic fixture, local worktree
- **Consumed by**: `src/croam/hosts.py` (already existed), `src/croam/commands/ls.py` reads sessions
- **Sample**:

  ```json
  {
    "hostname": "stormtree",
    "ownership": null,
    "lineage": null,
    "host_cache": null,
    "sessions": [
      {
        "sid": "31186226-49f3-483a-98f9-4fddd8452dee",
        "cwd": "/tmp/tmpr0tuds8a/home/proj",
        "transcript_path": "/tmp/tmpr0tuds8a/home/.claude/projects/-tmp-tmpr0tuds8a-home-proj/31186226-49f3-483a-98f9-4fddd8452dee.jsonl",
        "pid": null,
        "status": null,
        "started_at_ms": null,
        "updated_at_ms": null,
        "name": null,
        "version": null
      }
    ]
  }
  ```

- **Notes**: `ownership`, `lineage`, `host_cache` are null when no state files exist. Session fields are null when no `~/.claude/sessions/<pid>.json` is present (archived session).

### tmux command output shapes

- **How captured**: `sock=$(mktemp -u /tmp/tmux-XXXXXX.sock); tmux -S "$sock" new-session -d -s probe sleep 60; tmux -S "$sock" has-session -t probe; tmux -S "$sock" list-sessions -F "#{session_name}:#{session_attached}"; tmux -S "$sock" kill-session -t probe`
- **Captured on**: 2026-05-04, local tmux 3.4
- **Sample**:

  ```
  create rc=0
  has-session rc=0
  probe:0
  list-sessions rc=0
  kill rc=0
  ```

- **Notes**: `list-sessions` format is `name:attached_count` where `0` means not attached. `has-session` exits 0 (exists) or 1 (not found).

### claude JSONL transcript records

- **How captured**: `build_jsonl()` synthetic fixture; real E2E session not observed (CROAM_E2E=1 not set in this environment).
- **Consumed by**: `src/croam/transcript.py:render_static_transcript`
- **Sample** (synthetic):

  ```json
  {"type": "last-prompt", "leafUuid": "...", "sessionId": "..."}
  {"type": "permission-mode", "permissionMode": "default", "sessionId": "..."}
  {"parentUuid": "...", "isSidechain": false, "type": "user", "message": {"role": "user", "content": "synthetic prompt 0"}, "uuid": "...", "timestamp": 1746397740534, "cwd": "/path/to/proj", "sessionId": "...", "version": "2.1.123", "gitBranch": "master"}
  ```

- **Notes**: Real transcripts may have `message` as a plain string or with `content` as a list of content blocks per Anthropic API shape. All three shapes handled by `_extract_text`.

---

## Helper Issues

None. No helpers were listed for this phase. All work done inline.

---

## Functional QA Results

### (CLI surface, Loop A) Empty state: `["ls", "--json"]` returns exit 0, stdout `"[]\n"`

- **Surface**: CLI surface (typer app), Loop A
- **Invocation**: `runner.invoke(app, ["--json", "ls"])` with fresh state_root (no sessions, no assertions)
- **Observed outcome**:

  ```
  exit_code=0
  stdout='[]'
  ```

- **Verdict**: pass

### (CLI surface, Loop A) Single local session: schema check

- **Surface**: CLI surface, Loop A
- **Invocation**: `runner.invoke(app, ["--json", "ls"])` with one seeded session and assertion
- **Observed outcome**:

  ```json
  [
    {
      "sid": "5cdd86fc-30ae-47b9-a9b7-0700fb909516",
      "owner": "stormtree",
      "host_reachable": true,
      "status": null,
      "cwd": "~/proj",
      "last_activity": "2026-05-03T22:29:00.534251+00:00",
      "is_orphan": false,
      "name": null
    }
  ]
  ```

- **Verdict**: pass -- all 8 schema keys present, owner == self_hostname, last_activity matches ISO8601.

### (CLI surface, Loop A) Local-running attach plan

- **Surface**: CLI surface, Loop A
- **Invocation**: `runner.invoke(app, ["attach", sid, "--no-exec"])` with tmux session pre-created
- **Observed outcome**:

  ```json
  {"action": "tmux-attach", "argv": ["tmux", "-S", "/tmp/tmpn3tsqr7g/tmux.sock", "attach", "-t", "claude-0cd4ad4c-bb66-491f-8661-ecd7af832049"]}
  ```

- **Verdict**: pass -- action is `tmux-attach`, argv contains `attach -t claude-<sid>`.

### (CLI surface, Loop A) Local-archived attach plan

- **Surface**: CLI surface, Loop A
- **Invocation**: `runner.invoke(app, ["attach", sid, "--no-exec"])` with no tmux session
- **Observed outcome**:

  ```json
  {"action": "tmux-new-and-attach", "argv": ["tmux", "-S", "/tmp/tmpn3tsqr7g/tmux.sock", "new-session", "-A", "-s", "claude-0cd4ad4c-bb66-491f-8661-ecd7af832049", "claude-real", "--resume", "0cd4ad4c-bb66-491f-8661-ecd7af832049"]}
  ```

- **Verdict**: pass -- action is `tmux-new-and-attach`, argv tail contains `new-session -A -s claude-<sid> claude-real --resume <sid>`.

### (CLI surface, Loop B) Remote-reachable attach plan

- **Surface**: CLI surface, Loop B
- **Invocation**: `runner.invoke(app, ["attach", sid, "--no-exec"])` with vicar assertion, ssh_shim exit 0
- **Observed outcome**:

  ```json
  {"action": "ssh-recurse", "argv": ["ssh", "vicar", "croam", "attach", "3c015049-9b95-4409-ac4d-e80d919ee3eb", "--here-on-owner"]}
  ```

- **Verdict**: pass -- action is `ssh-recurse`, argv has `vicar` alias and `--here-on-owner`.

### (CLI surface, Loop B) Recursion guard property

- **Surface**: CLI surface, Loop B
- **Invocation**: `runner.invoke(app, ["attach", sid, "--here-on-owner", "--no-exec"])` with vicar assertion
- **Observed outcome**:

  ```json
  {"action": "tmux-new-and-attach", "argv": ["tmux", "-S", "/tmp/tmpui2izvpd/tmux.sock", "new-session", "-A", "-s", "claude-3c015049-9b95-4409-ac4d-e80d919ee3eb", "claude-real", "--resume", "3c015049-9b95-4409-ac4d-e80d919ee3eb"]}
  ```

- **Verdict**: pass -- action starts with `tmux-` not `ssh-recurse`.

### (CLI surface, Loop F) Peek local-archived dispatch

- **Surface**: CLI surface, Loop F
- **Invocation**: `runner.invoke(app, ["peek", sid, "--no-exec"])` with local assertion, no tmux
- **Observed outcome**:

  ```json
  {"action": "static-transcript", "argv": ["render_static_transcript", "/tmp/tmpr0nsn1se/home/.claude/projects/-tmp-tmpr0nsn1se-home-proj/6f89f1a8-03af-4568-abce-5f240a35a3e9.jsonl"]}
  ```

- **Verdict**: pass -- action is `static-transcript`, argv[1] ends with `<sid>.jsonl`.

### (CLI surface, Loop F) Peek remote-unreachable mirror read

- **Surface**: CLI surface, Loop F
- **Invocation**: `runner.invoke(app, ["peek", sid])` with mirror JSONL, ssh_shim exit 1
- **Observed outcome**:

  ```
  exit_code=0
  stdout='[user] mirror prompt 1\n[user] mirror prompt 2\n'
  ```

- **Verdict**: pass -- exit 0, stdout has `[user]` twice.

### (CLI surface, scripting) `ls --orphans` schema

- **Surface**: CLI surface, scripting
- **Invocation part a**: `runner.invoke(app, ["--orphans", "--json", "ls"])` with orphan JSONL and no assertion
- **Observed outcome part a**:

  ```json
  [
    {
      "sid": "f961c39c-0f16-4479-80c7-02adbe91e919",
      "owner": null,
      "host_reachable": null,
      "status": null,
      "cwd": "/tmp/tmptd8x10oe/home/orphan-proj",
      "last_activity": null,
      "is_orphan": true,
      "name": null
    }
  ]
  ```

- **Invocation part b**: `runner.invoke(app, ["--json", "ls"])` (no --orphans), chdir to orphan-proj
- **Observed outcome part b**:

  ```
  exit_code=0
  sids present: []
  ```

- **Verdict**: pass -- orphan has `is_orphan=True, owner=null`; absent from normal `ls`.

### Anti-Patterns Watched For

- **A (HOME redirect)**: Every test uses the `home` fixture to redirect HOME. `Path.home()` not called in any new production code. `load_config()` uses `os.path.expanduser` which respects HOME env var.
- **B (mocking SSH)**: Used `ssh_shim` fixture for all SSH probes. No monkeypatching of SSH subprocess.
- **C (mocking tmux)**: Used real tmux against `tmux_socket` fixture. No mocking of tmux subprocess.
- **E (timezones)**: All datetimes in JSON output use `.astimezone(UTC).isoformat()`.

### Strategy Updates

No strategy updates. The existing surfaces, loops, and anti-patterns cover this phase completely.

---

## Challenges & Solutions

### Challenge 1: CliRunner does not capture sys.stdout written by render_static_transcript

**Solution:** Python evaluates `fp=sys.stdout` default args at module import time, not call time. Passing `fp=sys.stdout` explicitly at the call site in `peek.py` ensures the lookup happens at invocation time, which is when CliRunner has replaced `sys.stdout` with its capture buffer.

### Challenge 2: CroamError exit code via CliRunner is 1 not 2

**Solution:** `CliRunner` invokes `app()` directly, bypassing `main()`. The `CroamError -> SystemExit(2)` handler only runs in `main()`. Error-exit tests use `subprocess.run` invoking `main()` directly so the full error handler fires. Success tests continue to use the faster `CliRunner`.

### Challenge 3: `_dispatch` signature had no `config`/`home` parameters

**Solution:** Extended `_dispatch` with `config: Config, home: Path` parameters (matching the full set of things verbs need). Updated the `run_picker` call site to pass them through.

---

## Code Quality

### Formatting
- [x] Code formatted with `ruff format`
- [x] Imports organized per ruff isort
- [x] No unused imports

### Documentation
- [x] All public functions have one-line docstrings
- [x] Type annotations on all function signatures
- [x] Module-level docstrings present

### Linting
```
$ uv run ruff check src tests
All checks passed!
$ uv run ruff format --check src tests
45 files already formatted
$ uv run pyright src tests
0 errors, 0 warnings, 0 informations
```

---

## Dependencies

### Required by This Phase

- Phase 1: errors, log, proc, conftest
- Phase 2: paths, config
- Phase 3: sessions, hosts
- Phase 4: ownership
- Phase 5: tmux
- Phase 6: cli, picker, default

### Unblocked Phases

- Phase 8: claim/fork can replace `NotImplementedError("Phase 8")` stubs in `_dispatch` and reuse `--no-exec` pattern from attach/peek.
- Phase 9: doctor/sync can use `ls` as a reference for multi-host ownership reading patterns.
- Phase 10: integration tests can drive attach/peek/ls via the `--no-exec` JSON contract.

---

## Codebase Context Updates

Add to Key Files table:

| `src/croam/transcript.py` | `render_static_transcript(jsonl_path, *, fp=sys.stdout) -> int`; `_extract_text(message_field) -> str` | Phase 7 |
| `src/croam/commands/ls.py` | `run(ctx_obj, config, home) -> int`; JSON/text listing with filters | Phase 7 |
| `src/croam/commands/peek.py` | `run(sid, ctx_obj, config, home, *, here_on_owner, no_exec) -> int` | Phase 7 |
| `src/croam/commands/attach.py` | `run(sid, ctx_obj, config, home, *, here_on_owner, no_exec) -> int` | Phase 7 |
| `tests/test_transcript.py` | 20 tests for transcript rendering | Phase 7 |
| `tests/test_ls.py` | 10 tests for ls command | Phase 7 |
| `tests/test_peek.py` | 12 tests for peek command | Phase 7 |
| `tests/test_attach.py` | 10 tests for attach command | Phase 7 |
| `tests/test_default_dispatch.py` | 11 tests for _dispatch routing | Phase 7 |

Update `commands/default.py` entry: `_dispatch` now has full routing (not stub).

Update `cli.py` entry: `cmd_attach`, `cmd_peek`, `cmd_ls` now implemented (not stubs). `cmd_attach` and `cmd_peek` gained `--no-exec` hidden option. `cmd_peek` gained `--here-on-owner`.

## Notes for Future Phases

- `--no-exec` is the test seam contract: `{"action": "...", "argv": [...]}` JSON on stdout, exit 0. Phase 8 should follow the same pattern for claim/fork.
- `CROAM_TMUX_SOCK` env var overrides the tmux socket path in all three verbs (attach, peek, ls does not use tmux). Tests set it via `monkeypatch.setenv`.
- `_dispatch` signature: `(expect_key, selected, ctx_obj, config, home)`. Phase 8 should extend the `c`/`C`/`f`/`F` branches without changing the signature.
- `render_static_transcript` must be called with explicit `fp=sys.stdout` at call sites inside the CLI layer (not relying on default arg) to work correctly inside CliRunner test invocations.
- The `ls` PWD filter only applies when `not all_mode and not host_filter and not orphans_only`. Combining `--all` with `--host` works; the host filter takes precedence.

---

## Next Steps

**Next Phase:** Phase 8 -- claim and fork verbs

**Recommended Actions:**
1. Replace `NotImplementedError("Phase 8: claim")` and `NotImplementedError("Phase 8: fork")` in `commands/default.py:_dispatch`.
2. Implement `commands/claim.py` and `commands/fork.py` following the `--no-exec` pattern.
3. Wire `cmd_claim` and `cmd_fork` in `cli.py` (currently `NotImplementedError("Phase 8")`).

---

## Approval

**Phase Status:** COMPLETE

---

*This summary was generated following the PHASE_SUMMARY_TEMPLATE.md structure.*
