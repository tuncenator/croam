# croam - Project Plan

**Feature/Initiative**: picker-spec-gaps
**Type**: Enhancement
**Created**: 2026-05-04
**Estimated Total Phases**: 3

---

## Project Location

**IMPORTANT: All paths in this document are relative to the project root.**

- **Project Root**: `/home/tunc/Sync/Programs/croam`
- **Verify with**: `pwd` -> should output `/home/tunc/Sync/Programs/croam`

When you see a path like `src/croam/picker.py`, it means `/home/tunc/Sync/Programs/croam/src/croam/picker.py`

---

## Project Overview

### Purpose

Close 5 spec gaps in croam's fzf picker: Unicode glyphs with ANSI color, fish-style cwd truncation, first-user-message fallback for unnamed sessions, and a real preview pane replacing the current stub.

### Scope

**In Scope**:
- Unicode circle glyphs (reachable/unreachable)
- ANSI color encoding per session status
- Fish-style cwd path truncation
- First-user-message fallback for unnamed sessions
- Full preview pane (metadata block + conversation tail)

**Out of Scope**:
- Session autoname/rename infrastructure
- Picker layout changes beyond what the spec gaps require
- Remote session preview (SSH-fetched transcripts)

### Success Criteria

- [ ] Picker shows colored Unicode glyphs (green/yellow/gray/neutral-gray circles)
- [ ] Long cwds render fish-style truncated (~/P/o/i/iam)
- [ ] Unnamed sessions show first user message (up to 80 chars) instead of sid[:8]
- [ ] Preview pane shows metadata block + last N conversation messages
- [ ] All existing tests pass; new tests cover all new behavior

---

## Architecture Overview

### Key Components

1. **picker.py**: Row rendering, fzf argv construction, subprocess orchestration
2. **transcript.py**: Read-only JSONL transcript rendering (already exists)
3. **sessions.py**: Session discovery and metadata (already exists)

### Data Flow

```
sessions + assertions + host_statuses
    -> render_rows() builds PickerRow list
    -> format_input_lines() produces fzf stdin (with ANSI colors)
    -> build_fzf_argv() constructs fzf command (with --preview pointing to preview script)
    -> fzf displays rows + preview pane
```

### Technology Stack

- **Language**: Python 3.11+
- **Key Libraries**: typer, loguru, fzf (external binary)
- **Testing**: pytest
- **Build**: hatchling + uv

---

## Phase Overview

> **Detailed phase plans are in `phase_plans/PHASE_XX.md`.**
> Only read the plan file for your assigned phase to save context.

| Phase | Name | Objective (one line) | Dependencies |
|-------|------|---------------------|--------------|
| 1 | Glyphs and Colors | Unicode circle glyphs + ANSI color encoding per status | None |
| 2 | Display Formatting | Fish-style cwd truncation + first-user-message fallback | None |
| 3 | Preview Pane | Real preview pane with metadata block + conversation tail | Phase 1, Phase 2 |

---

## Phase Dependencies Graph

```
Phase 1 (Glyphs+Colors)
    \
     +---> Phase 3 (Preview Pane)
    /
Phase 2 (Display Formatting)
```

---

## Cross-Cutting Concerns

### Code Style

- Follow PEP 8, ruff enforced (line-length 100, select E/F/W/I/B/UP/SIM/RUF)
- Type hints for all function signatures
- Pyright in standard mode

### Error Handling

- Use `CroamError` (from `src/croam/errors.py`) for user-facing errors
- Log with loguru before raising

### Logging (MANDATORY)

Logging is already set up in this project. All new code must use the existing loguru setup.

- **Framework**: loguru (already in dependencies and configured in `src/croam/log.py`)
- **Output**: stderr via loguru default sink
- **Format**: loguru default (timestamp, level, module, message)
- **Levels**: DEBUG for development tracing, WARNING+ for user-visible issues

### Configuration

- Config lives in `~/.config/croam/` (TOML)
- Loaded via `src/croam/config.py`

### Testing Strategy

- Unit tests for all pure functions
- Integration tests via fake-fzf subprocess helper (`tests/_helpers/fake_fzf.py`)
- Synthetic JSONL via `tests/_helpers/synth_jsonl.py`
- All tests require HOME redirection (conftest.py safety guard)
- Test command: `uv run pytest`

---

## Integration Points

### picker.py <-> transcript.py

Phase 3's preview pane reads JSONL transcripts. The existing `transcript.py` has `_extract_text()` for parsing message content blocks. The preview module should reuse this extraction logic.

### picker.py <-> sessions.py

`render_rows()` receives `ClaudeSession` objects. The `transcript_path` field provides the path to the JSONL file for both first-message extraction (Phase 2) and preview rendering (Phase 3).

---

## Glossary

**sid**: Session ID (UUID string from transcript filename stem)
**glyph**: Single character indicating host reachability in picker row
**fish-style truncation**: Path display where intermediate components show only first character
**JSONL**: JSON Lines format used by claude-code for conversation transcripts

---

## Future Enhancements

- [ ] Session autoname from conversation content
- [ ] Remote transcript fetching for preview of unreachable sessions
- [ ] Syntax highlighting in preview pane conversation tail
- [ ] Configurable preview pane width/position

---

## References

- croam spec (internal): sections on picker display, glyphs, colors, preview
- fzf documentation: --ansi, --preview, --preview-window flags
- cctakeover: reference implementation for preview_session.py and cwd truncation

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
