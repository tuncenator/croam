# Execution Plan: project-start

**Created**: 2026-04-30
**Mode**: Conductor
**Total Phases**: 11
**Total Batches**: 8

---

## Model Configuration

The conductor dispatches every subagent by `subagent_type`. Each subagent file under `~/.claude/agents/` pins its own model in frontmatter, so the conductor never passes a `model` parameter and version drift is impossible.

| Role | Subagent | Pinned model | Context | Notes |
|------|----------|--------------|---------|-------|
| Orchestrator | (slash command, not a subagent) | inherits user session model | -- | Runs as `/spark-conductor`. |
| Hard phases | `spark-coder-hard` | `claude-opus-4-6` | 1M | Routed when phase Difficulty = hard. Phases 1, 6, 8. |
| Easy/Medium phases | `spark-coder-easy` | `claude-sonnet-4-6` | 1M | Routed when phase Difficulty = easy or medium. Phases 2, 3, 4, 5, 7, 9, 10, 11. |
| Checkpoint | `spark-checkpoint` | `claude-opus-4-6` | 1M | Merge, test, local verify, inline fix (up to 3 attempts). Does NOT push or deploy. |
| Code review | `spark-code-reviewer` | `claude-opus-4-6` | 1M | Reviews batch diff after a successful checkpoint; must pass before any deploy step. |
| Deploy-verify | `spark-deploy-verify` | `claude-opus-4-6` | 1M | N/A for this feature -- deploy is disabled. The conductor still runs code review at each checkpoint. |
| Dedicated fix | `spark-fix` | `claude-opus-4-6` | 1M | Fresh-context fix after a checkpoint or review failure. |

---

## Cache Strategy

**Shared Prefix** (identical across all coding agents in a parallel batch -- cached after the first agent):

- `docs/agent/project-start/CODEBASE_CONTEXT.md` (~10k tokens)
- `docs/agent/project-start/FUNCTIONAL_QA_STRATEGY.md` (~6k tokens)
- Cross-cutting concerns from `PROJECT_PLAN.md` (~3k tokens)
- `docs/agent/project-start/QUICKSTART.md` if read (~6k tokens)
- Previous checkpoint summary (~2k tokens after the first checkpoint)
- Universal coder agent system prompt (~4k tokens)

**Estimated shared prefix**: ~25-31k tokens.

**Per-Agent Suffix** (unique to each coding agent):

- Phase plan from `phase_plans/PHASE_XX.md` (~5-10k tokens depending on phase)
- Inputs the coder gathers via Read/Bash inside its session

**Estimated per-agent suffix**: ~5-10k tokens.

**Note**: All agents in a parallel batch (Batch 3 = phases 3, 4, 5; Batch 6 = phases 8, 9) are spawned in a single conductor message to maximize prompt cache hits. The shared prefix must be byte-identical across all agent prompts.

---

## File Contention Analysis

| File / Directory | Phases That Touch It | Risk | Mitigation |
|-----------------|---------------------|------|------------|
| `pyproject.toml` | 1 (declares all deps), later phases may add deps via `uv add` | LOW | Phase 1 declares the full dependency set upfront (typer, loguru, pytest, pytest-cov, ruff, pyright). Later phases should not need new deps; if they do, the checkpoint merge handles it. |
| `src/croam/cli.py` | 1 (stub), 6 (full ownership; wires every verb) | LOW | Phase 1 writes a minimal stub (just `app = typer.Typer()`); Phase 6 fully replaces it. No parallel batch contains both. |
| `src/croam/commands/__init__.py` | 3 (creates), 5, 7, 8, 9 (each adds a module under it) | LOW | The `__init__.py` is empty and doesn't change. Each phase adds a separate file under `commands/`. No content collisions. |
| `src/croam/commands/<verb>.py` | 5 (launch), 7 (attach, peek, ls, default), 8 (claim, fork, release, reconcile) | NONE | Each phase owns its own files. No overlap. |
| `tests/conftest.py` | 1 (full ownership) | NONE | Phase 1 writes the full conftest. Later phases add per-test fixtures inside their own test files (e.g. `tests/test_paths.py`), not to the global conftest. |
| `tests/_helpers/*.py` | 1 (synth_jsonl, synth_session, fake_fzf, etc.), 4 (synth_assertions) | LOW | Phase 1 ships the universally-needed helpers; Phase 4 adds `synth_assertions.py` (separate file). No file overlap. |
| `docs/agent/project-start/CODEBASE_CONTEXT.md` | All phases (each updates "Last updated by" + adds entries) | LOW | Updates are append-mostly; merge conflicts unlikely. The checkpoint agent merges, no parallel-batch conflicts within the same physical merge window. |
| `docs/agent/project-start/STATUS.md` | All phases (mark complete, advance current) | LOW | Same as above. Sequential within a batch. |
| `docs/agent/project-start/PROJECT_PLAN.md` | 8 (updates References / Open Questions section after answering claude --resume cwd-enforcement question) | NONE | Only Phase 8 modifies; no parallel contention. |
| `src/croam/snapshots.py` (or `<state_root>/<host>/snapshots.json`) | 8 (introduces) | NONE | Phase 8 owns; no other phase touches. |

**Parallel batch contention check**:

- **Batch 3 (Phases 3, 4, 5)**: Phase 3 owns `sessions.py, hosts.py, commands/emit_state.py`; Phase 4 owns `ownership.py`; Phase 5 owns `tmux.py, shim.py, commands/launch.py`. No file overlap. Tests are per-module under `tests/test_*.py`, no overlap.
- **Batch 6 (Phases 8, 9)**: Phase 8 owns `commands/{claim,fork,release,reconcile}.py + snapshots.json`; Phase 9 owns `sync.py, doctor.py`. No file overlap. Both update `CODEBASE_CONTEXT.md` (Phase 8 substantively answers the cwd-enforcement question; Phase 9 lightly adds doctor's diagnostic patterns) -- the checkpoint agent merges these.

## Runtime Contention Analysis

| Resource | Type | Phases That Use It | Mitigation |
|----------|------|--------------------|------------|
| tmux server | service | 5 (creates/destroys claude-<sid> sessions for tests), 7 (attaches), 10 (e2e tmux fixture) | Each test uses a private socket via `tmux -S <tmp_path>/sock-<pid>`; the conftest `tmux_socket` fixture isolates per-test. No shared state; no contention even when phases run in parallel batches. |
| Filesystem `/tmp/croam-tests/...` | system-state | All phases (test artifacts) | Pytest's `tmp_path` fixture gives each test a unique dir. No overlap. |
| User's real `/tmp/croam-e2e/` (e2e_dummy) | external | 2 (paths Tier 2 test), 3 (sessions Tier 2), 5 (shim Tier 2), 8 (claim --here Tier 2), 10 (integration Tier 2) | All Tier 2 tests are READ-ONLY against the dummy. Mutating tests copy the JSONL to a `tmp_path`-rooted location first. No write contention. The conductor runs Tier 2 only when `CROAM_E2E=1` is explicitly set; default test runs skip them. |
| User's real `~/.claude/sessions/`, `~/.claude/projects/` | external | 3 (Tier 2 only) | Read-only enumerate; never written. The conftest guard prevents accidental writes. |
| The `claude` binary on PATH | external | 8 (`claude --resume <fork_sid>` Tier 2 test), 10 (Tier 2) | Read/exec only; one process at a time per test. The Tier 2 test runs `claude --print` (or `--resume <fork>`) against a `tmp_path`-cloned JSONL, in a tmp_path-rooted HOME. No contention with the user's real claude sessions. |
| External SSH endpoints | external-api | 3, 7, 8, 9 (all use the `ssh_shim` fixture in Tier 1; none make real SSH calls in Tier 1) | All Tier 1 tests use the fake SSH binary on PATH. No real SSH contention. Tier 2 (if added later) would target localhost only. |

No real shared services, databases, or external APIs are exercised in Tier 1. The `ssh_shim` and `tmux_socket` fixtures fully isolate every parallel test.

---

## Batch Schedule

| Batch | Phases | Mode | Checkpoint Deploy | Checkpoint Verify |
|-------|--------|------|-------------------|-------------------|
| 1 | Phase 1 | sequential | No (deploy disabled) | uv sync exits 0; smoke test passes; conftest guard refuses unredirected HOME; pyright + ruff clean |
| 2 | Phase 2 | sequential | No | All `tests/test_paths.py` and `tests/test_config.py` pass; encode_cwd matches real `~/.claude/projects/` listings; `decode_cwd` round-trips with fs_probe |
| 3 | Phase 3, Phase 4, Phase 5 | parallel | No | Per-phase tests pass; `discover_local_sessions(home)` returns expected ClaudeSession; ownership merge yields most-recent winner; tmux session creation against private socket works |
| 4 | Phase 6 | sequential | No | `croam --help` shows all visible verbs; `croam emit-state` (hidden) returns valid JSON; picker tests pass with fake-fzf script; CroamError -> exit 2 with clean stderr |
| 5 | Phase 7 | sequential | No | `croam ls --json` returns parseable JSON; `croam attach <sid> --no-exec` returns expected planned argv (local + remote-reachable + remote-unreachable cases) |
| 6 | Phase 8, Phase 9 | parallel | No | claim handshake state machine tested at every boundary; ssh-strict blocks illegal transitions; fork lineage increments; `croam doctor` clean run exits 0; doctor with conflict file exits non-zero |
| 7 | Phase 10 | sequential | No | All integration tests pass (Tier 1); two-host fixture round-trip; `--orphans` flag handling; coverage >= 80% |
| 8 | Phase 11 | sequential | No | `bash scripts/install-shim.sh --self-check` exits 0; idempotent on re-run; `uv tool install --editable .` succeeds; both Tier 1 and Tier 2 (`CROAM_E2E=1`) pytest exit 0 |

---

## Batch Details

### Batch 1: Foundation

**Mode**: sequential
**Rationale**: Phase 1 establishes the project skeleton, every fixture, and every cross-cutting concern (logging, error hierarchy, test harness). All later phases depend on this. Cannot parallelize -- there is only one foundation.

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 1 | Foundation: project skeleton, logging, test harness | hard | spark-coder-hard | ~80k | Sets up uv, pyproject.toml, src/croam/{log, errors, proc}, tests/conftest.py with all fixtures, tests/_helpers/ |

**Checkpoint**:
- **Deploy**: No -- deployment is disabled for this feature.
- **Verify**: `uv sync && uv run pytest tests/test_smoke.py -v` exits 0; `uv run pyright src` exits 0; `uv run ruff check src tests` exits 0; the conftest guard explicitly refuses to run when HOME is unredirected (verifiable via a deliberately-skipped negative test).
- **Critical**: Yes -- failure here blocks every subsequent phase.

### Batch 2: Config & paths

**Mode**: sequential
**Rationale**: Phase 2 introduces `paths.encode_cwd`, `paths.decode_cwd`, `paths.normalize_cwd`, and the full `Config` dataclass. Phases 3, 4, 5 all consume these. Phase 2 is sequential because it's the only phase here; it blocks the parallel Batch 3.

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 2 | Config & paths | medium | spark-coder-easy | ~60k | Implements encode_cwd lossy-decode, TOML config loader with Config dataclass |

**Checkpoint**:
- **Deploy**: No.
- **Verify**: All `test_paths.py` and `test_config.py` pass; encode_cwd produces values that match the real `~/.claude/projects/` listings (verified via Tier 2 test against e2e_dummy); decode_cwd handles ambiguous paths via filesystem probe.
- **Critical**: Yes -- Batch 3 needs paths and config.

### Batch 3: Sessions, ownership, tmux+shim (parallel)

**Mode**: parallel
**Rationale**: Phases 3, 4, 5 each own a disjoint module set with no file contention (Phase 3 -> sessions.py + hosts.py + commands/emit_state.py; Phase 4 -> ownership.py; Phase 5 -> tmux.py + shim.py + commands/launch.py). All depend only on Phases 1 and 2. Cache efficiency is high (3 agents share the prompt prefix containing PROJECT_PLAN, CODEBASE_CONTEXT, FUNCTIONAL_QA_STRATEGY, the previous checkpoint summary).

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 3 | Sessions & host probes | medium | spark-coder-easy | ~70k | Discovers `~/.claude/projects/<encoded>/<sid>.jsonl` and joins with `~/.claude/sessions/<PID>.json`; SSH reachability fanout |
| 4 | Ownership state | medium | spark-coder-easy | ~70k | per-host ownership.json read/write/merge/flatten with atomic-rename writes |
| 5 | Tmux integration & claude shim | medium | spark-coder-easy | ~70k | tmux subprocess wrappers; shim's should_wrap and derive_sid pure functions; commands/launch.py orchestrator |

**Checkpoint**:
- **Deploy**: No.
- **Verify**: Each phase's tests pass; merge into `feature/project-start` succeeds with no conflicts; combined test run passes; the runtime-contention mitigations (private tmux socket, ssh_shim, tmp_path-rooted state_root) are honored across all 3 phases.
- **Critical**: Yes -- Batch 4 needs all three.

### Batch 4: Picker & CLI dispatcher

**Mode**: sequential
**Rationale**: Phase 6 wires every verb in cli.py and implements the fzf picker. It's the convergence point that consumes Phase 1-5 outputs. Hard difficulty due to typer + fzf + multi-select intersection nuance.

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 6 | Picker & CLI dispatcher | hard | spark-coder-hard | ~100k | typer skeleton with verb stubs (Phase 7-9 fill them in); picker row layout, fzf argv builder, multi-select intersection |

**Checkpoint**:
- **Deploy**: No.
- **Verify**: `uv run croam --help` shows visible verbs (`ls`, `attach`, `peek`, `claim`, `fork`, `launch`, `doctor`); does NOT show `emit-state` (hidden); `uv run croam emit-state` returns valid JSON; picker tests pass with fake-fzf script; `compute_action_intersection` returns the right safe-action set across mixed-state row selections.
- **Critical**: Yes -- Batches 5+ need the wired CLI to dispatch into.

### Batch 5: Read verbs (attach, peek, ls)

**Mode**: sequential
**Rationale**: Phase 7 fills in the read-mostly verbs. They build on the picker's dispatch logic and need Phase 5's tmux + Phase 4's ownership + Phase 3's sessions/hosts. Sole phase in this batch (no parallel candidates -- Phase 8 depends on Phase 7's --no-exec contract patterns).

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 7 | Verbs: attach, peek, ls | medium | spark-coder-easy | ~80k | Recursive SSH attach with --here-on-owner guard; read-only peek; ls --json |

**Checkpoint**:
- **Deploy**: No.
- **Verify**: `croam ls --json` returns expected shape; `croam attach <sid> --no-exec` returns expected argv for local + remote cases; peek dispatches to tmux attach -r or static render correctly; orphan handling honors `--orphans` flag.
- **Critical**: Yes -- Batch 6's claim/fork need attach's recursion-guard pattern.

### Batch 6: Write verbs + doctor (parallel)

**Mode**: parallel
**Rationale**: Phase 8 owns the write verbs (claim, fork, release, reconcile) under `commands/`. Phase 9 owns sync.py and doctor.py. They share no source files. Both modify `CODEBASE_CONTEXT.md` at end-of-phase but the checkpoint agent merges these doc updates. Phase 8 is hard (claim handshake is the most complex coordination logic in the project); Phase 9 is medium (mostly composing Phase 1-4 modules).

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 8 | Verbs: claim, fork (incl. ssh-strict, --here, conflict reconciliation) | hard | spark-coder-hard | ~110k | Resolves spec section 15 open question on claude's recorded-cwd enforcement |
| 9 | Sync mode & doctor | medium | spark-coder-easy | ~65k | Read peer state from syncthing mirror; doctor diagnostic checks |

**Checkpoint**:
- **Deploy**: No.
- **Verify**: claim handshake tested at each boundary (release, copy, write, flatten); ssh-strict blocks illegal transitions; fork lineage increments correctly; `croam doctor` exits 0 against clean fixture, non-zero against injected conflict file; combined test run passes after merge.
- **Critical**: Yes -- Batch 7 (integration tests) needs all five verbs operational.

### Batch 7: Integration tests round 1

**Mode**: sequential
**Rationale**: Phase 10 doesn't write any new src/croam/ code; it writes integration tests that exercise everything Phases 1-9 built. Cannot parallelize -- only one phase.

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 10 | Integration tests round 1 | medium | spark-coder-easy | ~65k | Two-host synthetic fixtures + opt-in real-claude E2E |

**Checkpoint**:
- **Deploy**: No.
- **Verify**: Tier 1 (`uv run pytest tests/integration -v`) exits 0 in <30s; Tier 2 (`CROAM_E2E=1`) tests pass when explicitly enabled; coverage report shows >= 80% overall (`uv run pytest --cov=croam --cov-report=term-missing`); CODEBASE_CONTEXT.md updated with empirical findings on claude --resume cwd-enforcement (the answer to spec section 15's open question).
- **Critical**: Yes -- Phase 11 (install) gates on this passing.

### Batch 8: Polish, install, README

**Mode**: sequential
**Rationale**: Final wrap-up phase. README, install scripts, ruff/pyright pass. Easy difficulty; no new functionality.

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 11 | Polish, install, README | easy | spark-coder-easy | ~40k | install-shim.sh, README.md, `uv tool install --editable .` verification |

**Checkpoint**:
- **Deploy**: No.
- **Verify**: install-shim.sh `--self-check` exits 0 and is idempotent; cctakeover-alias install adds the line to a tmp HOME's rc file; `uv tool install --editable <project_root>` succeeds; both Tier 1 and Tier 2 pytest exit 0; ruff and pyright clean.
- **Critical**: No -- this is the final batch; failure here is documented but doesn't block prior work.

---

## Dependency Graph

```
=== Batch 1 ===
Phase 1 (hard, sequential)    [foundation: pyproject, log, errors, proc, conftest, _helpers]
  |
--- Checkpoint 1 ---
  |
=== Batch 2 ===
Phase 2 (medium, sequential)  [paths.encode_cwd / decode_cwd / normalize, Config dataclass]
  |
--- Checkpoint 2 ---
  |
=== Batch 3 ===
Phase 3 (medium, parallel)    [sessions.py, hosts.py, commands/emit_state.py] --+
Phase 4 (medium, parallel)    [ownership.py + lineage]                          +-> merge
Phase 5 (medium, parallel)    [tmux.py, shim.py, commands/launch.py]            --+
  |
--- Checkpoint 3 ---
  |
=== Batch 4 ===
Phase 6 (hard, sequential)    [cli.py wires all verbs; picker.py with fzf orchestration]
  |
--- Checkpoint 4 ---
  |
=== Batch 5 ===
Phase 7 (medium, sequential)  [commands/{attach, peek, ls}.py + commands/default.py orchestrator]
  |
--- Checkpoint 5 ---
  |
=== Batch 6 ===
Phase 8 (hard, parallel)      [commands/{claim, fork, release, reconcile}.py + snapshots.json] --+
Phase 9 (medium, parallel)    [sync.py + doctor.py]                                              +-> merge
  |
--- Checkpoint 6 ---
  |
=== Batch 7 ===
Phase 10 (medium, sequential) [tests/integration/* end-to-end + e2e_dummy Tier 2]
  |
--- Checkpoint 7 ---
  |
=== Batch 8 ===
Phase 11 (easy, sequential)   [README.md, scripts/install-shim.sh, scripts/install-cctakeover-alias.sh]
  |
--- Checkpoint 8 (final) ---
```

---

## Conductor Pacing

- **Mode**: auto-refresh
- **Batches Per Session**: 4

Rationale: 8 batches total, > 5 threshold, so default applies. Batches per session = ceil(8/2) = 4. The conductor runs 4 batches in one session, then prompts the user to restart `/spark-conductor` for a fresh context window. Resumes automatically from the last completed checkpoint.

For croam specifically, the natural session split is:
- Session 1: Batches 1-4 (foundation through CLI wired with stubs) -- about 4-5 hours of compute
- Session 2: Batches 5-8 (verbs filled in, integration tests, polish)

If the user prefers `confirm-each-batch` (more checkpoints, slower, more control), that's a one-flag flip in the next `/spark-conductor` invocation.

---

## Fix Strategy

- **Max inline fix attempts per checkpoint**: 3
- **Inline fix**: `spark-checkpoint` itself attempts fixes (it has full merge context)
- **Dedicated fix subagent**: `spark-fix` (fresh context, claude-opus-4-6 pinned)
- **Escalation path**: 3 inline fixes -> dedicated fix subagent -> human intervention
- **Fix scope rules**:
  - Localized failure (one file, clear cause, <50 lines): inline fix in checkpoint
  - Systemic failure (architectural incompatibility, missing interfaces): skip inline, dispatch `spark-fix` immediately
  - Phase 8's claim handshake bugs are a likely candidate for `spark-fix` (multi-step state machine; localized fixes often miss the root cause)
  - Phase 6's picker bugs (fzf flag interactions) often admit inline fixes

---

## Notes

### Risk areas requiring human attention

- **Phase 8's `--here` cwd rebase**: the spec has an open question (does claude enforce the recorded cwd?). Phase 8 is supposed to resolve it empirically against the e2e_dummy. If the answer is "yes, claude enforces", the surgical JSONL rewrite is a per-line operation that adds complexity. Watch the checkpoint output for the empirical finding and the resulting code path. If Phase 8 punts on this and assumes "no enforcement" without verification, flag for human review.

- **Phase 1's conftest guard**: the autouse safety check is the difference between Tier 1 being safe and Tier 1 silently corrupting the user's real `~/.claude`. A Phase 1 bug that makes the guard always pass (without HOME redirection) would not surface until Phase 3 (sessions) starts touching real session files. Verify in checkpoint 1 that the guard explicitly fails on a deliberately-unredirected test.

- **Phase 6's fzf flag construction**: easy to get `--with-nth=2,6,7,8,9` wrong off-by-one. Easy to forget `FZF_DEFAULT_OPTS=""` in the env. Easy to use `$FZF_SELECTED_COUNT` instead of `$FZF_SELECT_COUNT`. The plan's Technical Reference is verbose specifically to prevent these.

- **Batch 3's parallelism**: 3 phases in parallel maximize cache efficiency but also means 3 worktrees being checkpoint-merged at once. If any of the 3 has a checkpoint failure, the merge complexity goes up. The conductor should be willing to fall back to sequential at this batch if early signals (e.g., Phase 3 takes 2x estimated tokens) indicate trouble.

### Difficulty ratings to revisit

- Phase 4 is on the easy side of medium. If it lands cleanly in <50k tokens, future similar phases might rate as easy.
- Phase 8 is firmly hard due to the multi-step state machine. Plan budget is 110k -- if the coder approaches this ceiling, watch for context exhaustion.
- Phase 11 is easy but includes shell scripts (install-shim.sh) that are notoriously bug-prone. Watch the checkpoint review for shell quoting issues.

### Suggested human review points

- After Checkpoint 3 (Batch 3 merge): review the synthesis of sessions+ownership+tmux modules. This is the first parallel-batch merge and the most complex one in the project.
- After Checkpoint 6 (Batch 6 merge): review the claim handshake's partial-failure recovery paths. State machines with disk-and-network IO are where bugs hide.
- After Checkpoint 7 (integration tests): review the empirical findings about claude --resume cwd enforcement. This determines whether `--here` is a simple metadata write or a per-line JSONL rewrite.
