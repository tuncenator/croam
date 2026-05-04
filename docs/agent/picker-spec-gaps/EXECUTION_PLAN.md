# Execution Plan: picker-spec-gaps

**Created**: 2026-05-04
**Mode**: Conductor
**Total Phases**: 3
**Total Batches**: 3

---

## Model Configuration

| Role | Subagent | Pinned model | Context | Notes |
|------|----------|--------------|---------|-------|
| Orchestrator | (slash command) | inherits user session | -- | Runs as `/spark-conductor` |
| Hard phases | `spark-coder-hard` | `claude-opus-4-6` | 1M | Phase 3 |
| Easy/Medium phases | `spark-coder-easy` | `claude-sonnet-4-6` | 1M | Phases 1, 2 |
| Checkpoint | `spark-checkpoint` | `claude-opus-4-6` | 1M | After each batch |
| Code review | `spark-code-reviewer` | `claude-opus-4-6` | 1M | Reviews batch diff |
| Dedicated fix | `spark-fix` | `claude-opus-4-6` | 1M | If checkpoint fails 3x |

---

## Cache Strategy

**Shared Prefix** (identical across all coding agents in a batch):
- CODEBASE_CONTEXT.md (~2k tokens)
- Cross-cutting concerns from PROJECT_PLAN.md (~1k tokens)
- Previous checkpoint summary (~1k tokens first batch, ~2k subsequent)
- Universal agent instructions (~4k tokens)
- **Estimated shared prefix**: ~9k tokens

**Per-Agent Suffix** (unique to each coding agent):
- Phase plan from PHASE_XX.md (~2-3k tokens)
- Phase-specific instructions (~0.5k tokens)
- **Estimated per-agent suffix**: ~3k tokens

**Note**: All batches are sequential (1 phase each), so cache sharing between parallel agents is not applicable. Cache benefits come from the conductor reusing context across sequential dispatches.

---

## File Contention Analysis

| File / Directory | Phases That Touch It | Risk | Mitigation |
|-----------------|---------------------|------|------------|
| `src/croam/picker.py` | 1, 2, 3 | HIGH (different functions but same file) | Sequential batches |
| `tests/test_picker.py` | 1, 2, 3 | MEDIUM (adding new tests, updating existing) | Sequential batches |
| `src/croam/cli.py` | 3 | LOW (only Phase 3 adds preview subcommand) | N/A |
| `src/croam/preview.py` | 3 | LOW (only Phase 3 creates this file) | N/A |

All phases modify `picker.py` and `test_picker.py`, making parallel execution unsafe. Sequential batches eliminate contention.

## Runtime Contention Analysis

No runtime contention identified. Each phase runs `uv run pytest` independently. No shared services, databases, or external APIs.

---

## Batch Schedule

| Batch | Phases | Mode | Checkpoint Deploy | Checkpoint Verify |
|-------|--------|------|-------------------|-------------------|
| 1 | Phase 1 | sequential | No | Glyphs are Unicode, colors applied per status |
| 2 | Phase 2 | sequential | No | Fish-cwd truncation works, first-message fallback works |
| 3 | Phase 3 | sequential | No | Preview renders metadata + conversation tail |

---

## Batch Details

### Batch 1: Glyphs and Colors

**Mode**: sequential
**Rationale**: Foundation phase; changes compute_glyph() and format_input_lines() which Phase 3 depends on contextually.

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 1 | Glyphs and Colors | easy | spark-coder-easy | ~50k | Straightforward substitution + color wrapping |

**Checkpoint**:
- **Deploy**: No -- CLI tool, no deployment target
- **Verify**: `compute_glyph()` returns Unicode circles, `colorize_glyph()` wraps with correct ANSI codes, all tests pass
- **Critical**: No -- Phase 2 is independent of Phase 1

### Batch 2: Display Formatting

**Mode**: sequential
**Rationale**: Adds new functions to picker.py; Phase 3 depends on fish_truncate_path() being available.

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 2 | Display Formatting | medium | spark-coder-easy | ~60k | Fish truncation algorithm + JSONL reading + render_rows integration |

**Checkpoint**:
- **Deploy**: No
- **Verify**: Fish truncation produces correct output for all edge cases, first-message fallback works for unnamed sessions, render_rows integrates both
- **Critical**: Yes -- Phase 3 imports fish_truncate_path from this phase

### Batch 3: Preview Pane

**Mode**: sequential
**Rationale**: Depends on Phase 1 (status display) and Phase 2 (fish_truncate_path). Largest phase, creates new module.

| Phase | Name | Difficulty | Subagent | Est. Tokens | Notes |
|-------|------|------------|----------|-------------|-------|
| 3 | Preview Pane | hard | spark-coder-hard | ~80k | New module, CLI subcommand, fzf integration, transcript tail reading |

**Checkpoint**:
- **Deploy**: No
- **Verify**: `croam preview <sid>` renders metadata + conversation tail, build_fzf_argv wires it correctly, graceful fallback on missing sessions
- **Critical**: No -- final phase

---

## Dependency Graph

```
=== Batch 1 ===
Phase 1 (easy, sequential) -- Glyphs and Colors
  |
--- Checkpoint 1 ---
  |
=== Batch 2 ===
Phase 2 (medium, sequential) -- Display Formatting
  |
--- Checkpoint 2 ---
  |
=== Batch 3 ===
Phase 3 (hard, sequential) -- Preview Pane
  |
--- Checkpoint 3 ---
```

---

## Conductor Pacing

- **Mode**: full-auto
- **Batches Per Session**: N/A

Small project (3 batches). Conductor runs all batches without pausing.

---

## Fix Strategy

- **Max inline fix attempts per checkpoint**: 3
- **Inline fix**: `spark-checkpoint` itself attempts fixes (it has full merge context)
- **Dedicated fix subagent**: `spark-fix` (fresh context, claude-opus-4-6 pinned)
- **Escalation path**: 3 inline fixes -> dedicated fix subagent -> human intervention
- **Fix scope rules**:
  - Localized failure (one file, clear cause, <50 lines): inline fix in checkpoint
  - Systemic failure (architectural incompatibility, missing interfaces): skip inline, dispatch `spark-fix` immediately
  - Fix outcomes are appended to the checkpoint summary

---

## Notes

- All 3 phases touch `src/croam/picker.py`, forcing sequential execution. No parallel opportunities.
- Phase 3 is rated hard because it creates a new module, adds a CLI subcommand, and must handle session lookup gracefully. The coding agent needs to make architectural decisions about the preview lookup strategy.
- Phase 1 and Phase 2 are truly independent (touch different functions), but both modify `picker.py` so git merge would be fragile. Sequential is safer.
