# Functional Verification Strategy

> Per-feature artifact. Captures HOW to prove this feature works from a real
> user's perspective in this specific project.
>
> **Living document.** Phases that uncover new surfaces, new harness needs, or
> new anti-patterns update this file before completing.
>
> **Last updated by**: Phase 0 - Initial Setup (2026-05-04)

---

## Surface Inventory

### 1. fzf picker (interactive TUI)

- **What**: An fzf-based interactive terminal picker that displays claude-code sessions as selectable rows with glyphs, colors, host, time, cwd, and name columns, plus a preview pane
- **Who calls it**: The user, via `croam` or `croam attach` (invokes the picker when multiple sessions match)
- **Entry point**: `src/croam/picker.py:launch_picker()`
- **New behavior this feature adds**:
  - Unicode circle glyphs with ANSI status colors (Phase 1)
  - Fish-style truncated cwd display (Phase 2)
  - First-user-message fallback for unnamed sessions (Phase 2)
  - Full metadata + conversation tail preview pane (Phase 3)

### 2. Pure formatting functions (library surface)

- **What**: Pure functions that produce formatted strings consumed by the picker and potentially by other croam commands (e.g. `croam ls`)
- **Who calls it**: Internal callers (`render_rows()`, `format_input_lines()`, `build_fzf_argv()`, and the preview script)
- **Entry point**: Individual functions in `src/croam/picker.py` and the new preview module
- **New behavior**:
  - `compute_glyph()` returns Unicode instead of ASCII
  - New `fish_truncate_path()` function
  - New `extract_first_user_message()` function
  - New preview rendering function(s)

---

## User Loop

### Loop 1: Picker row display (Surfaces 1 + 2)

User runs `croam` in a terminal with sessions available. The picker opens. User observes:
- Each row shows a colored circle glyph (green/yellow/gray) instead of plain "o"/"O"
- Cwd column shows `~/P/o/i/iam` instead of `/home/tunc/Programs/onlayer-x/internal/iam`
- Unnamed sessions show a descriptive first-message excerpt instead of `abc12345`

### Loop 2: Preview pane (Surface 1)

User highlights a session in the picker. The preview pane (right side) shows:
- Metadata block: owner hostname, status (running-idle/busy/archived), full cwd, available actions
- Conversation tail: last N messages from the transcript, formatted as `[user] ...` / `[assistant] ...`

### Loop 3: Pure function correctness (Surface 2)

Calling `compute_glyph(HostStatus(reachable=True, ...))` returns `"\033[32m●\033[0m"` (green filled circle). Calling `fish_truncate_path("/home/tunc/Programs/onlayer-x/internal/iam", home="/home/tunc")` returns `"~/P/o/i/iam"`. Calling `extract_first_user_message(jsonl_path)` on a transcript whose first user message is "help me debug the auth flow" returns `"help me debug the auth flow"`.

---

## Verification Mechanics

### For Surface 2 (pure functions): unit tests via pytest

The primary verification mechanism. Pure functions are tested directly:

```python
# In tests/test_picker.py or tests/test_preview.py
def test_compute_glyph_reachable():
    hs = HostStatus(name="h", reachable=True, last_probed=NOW, error=None)
    result = compute_glyph(hs)
    assert "●" in result  # filled circle
    assert "\033[32m" in result  # green

def test_fish_truncate():
    assert fish_truncate_path("/home/tunc/Programs/onlayer-x/internal/iam", "/home/tunc") == "~/P/o/i/iam"
```

The test harness already exists: `conftest.py` provides `home` fixture, `synth_jsonl.py` creates transcripts, `fake_fzf.py` creates canned fzf binaries.

### For Surface 1 (fzf picker): fake-fzf subprocess tests

The picker spawns fzf as a subprocess. Tests use `make_fake_fzf()` to create a script that:
- Receives stdin (the formatted rows with ANSI codes)
- Outputs canned selections
- Writes action keys to a keyfile

Verification of ANSI correctness: assert that `format_input_lines()` output contains expected escape sequences. The `--ansi` flag on fzf handles rendering; we verify the wire format, not the visual output.

Preview pane verification: the `--preview` command is a shell command invoked by fzf. We verify the preview script/module independently (unit tests on the preview rendering function) and check that `build_fzf_argv()` wires it correctly.

---

## Anti-Patterns

1. **Testing glyphs/colors by visual inspection instead of asserting escape sequences.** The picker runs in a TTY we can't observe from tests. Always assert the exact ANSI escape codes in the string output of `format_input_lines()` and `compute_glyph()`.

2. **Hardcoding ANSI codes as string literals without a named constant or helper.** This makes tests brittle and unreadable. Use a small mapping (status -> color code) and test through the mapping, not through raw "\033[32m" strings everywhere.

3. **Testing fish truncation only with the happy path.** Edge cases matter: root path "/", home directory itself "~", single-component paths, paths with dots, Windows-style paths (shouldn't appear but shouldn't crash).

4. **Testing first-message extraction against synthetic JSONL only.** The `synth_jsonl.py` helper produces a specific format. Real transcripts have quirks: empty content blocks, tool_use messages before the first user message, multi-block content. Test with at least one realistic JSONL fixture.

5. **Mocking fzf to test the preview pane.** The preview command is invoked by fzf as a shell subprocess. Test the preview rendering function directly (it takes a sid and returns formatted text). Don't try to capture what fzf displays in its preview window.

6. **Testing the preview module by importing `render_static_transcript` and checking its full output.** The preview needs only the LAST N messages, not the full transcript. Verify the tail extraction independently from the full-transcript renderer.

---

## Required Harness Deliverables

All required harness exists in the codebase:

- `tests/conftest.py`: `home` fixture, `ssh_shim` fixture
- `tests/_helpers/fake_fzf.py`: `make_fake_fzf()` for picker subprocess tests
- `tests/_helpers/synth_jsonl.py`: `build_jsonl()` for creating test transcripts
- `tests/_helpers/synth_session.py`: Session metadata creation

No new harness infrastructure needed. Phase plans should reuse existing helpers and add test functions to existing test files.

---

## How Agents Use This Document

**Phase planner**: Derives 3-7 functional checks per phase from the User Loops above.

**Coding agent**: Runs each check using pytest, captures actual output in phase summary.

**Checkpoint agent**: Validates phase summaries include Functional QA Results with real invocations and outputs.
