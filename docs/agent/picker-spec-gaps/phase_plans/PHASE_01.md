# Phase 1: Glyphs and Colors

**Feature**: picker-spec-gaps
**Estimated Context Budget**: ~50k tokens

**Difficulty**: easy
**Visual**: no
**Functional**: yes

**Execution Mode**: sequential
**Batch**: 1

---

## Objective

Replace ASCII reachability glyphs with Unicode circles and add ANSI color encoding per session status, so the picker rows show colored indicators at a glance.

---

## Deliverables

1. Modified `compute_glyph()` in `src/croam/picker.py` to return colored Unicode circles
2. Status-to-color mapping constant in `src/croam/picker.py`
3. Updated `format_input_lines()` to pass ANSI codes through (already does via `--ansi` flag; verify no stripping)
4. Updated tests in `tests/test_picker.py` for new glyph values and color codes

---

## Detailed Requirements

### Glyph change

Modify `compute_glyph(host_status: HostStatus | None) -> str`:

- `host_status is None` -> return `"?"` (unchanged, no color, unknown state)
- `host_status.reachable == True` -> return filled circle `"●"`
- `host_status.reachable == False` -> return open circle `"○"`

### Color encoding

Add ANSI color wrapping based on the session's status word. The color applies to the glyph character.

Create a new function `colorize_glyph(glyph: str, status_word: str) -> str` that wraps the glyph in ANSI escape codes:

| status_word | Color | ANSI code |
|-------------|-------|-----------|
| `running-idle` | green | `\033[32m` |
| `running-busy` | yellow | `\033[33m` |
| `archived` | gray (bright black) | `\033[90m` |
| `unreachable` | neutral gray (dim) | `\033[2m` |

Reset code: `\033[0m`

Example output for a reachable running-idle session: `"\033[32m●\033[0m"`

### Integration point

In `render_rows()`, after computing `glyph` and `status_word`, apply colorization:

```python
glyph = compute_glyph(hs)
status_word = compute_status_word(session, hs)
glyph = colorize_glyph(glyph, status_word)
```

The `PickerRow.glyph` field will now contain the ANSI-wrapped string. Since fzf is invoked with `--ansi`, it will render the colors. The `_scrub()` function in `format_input_lines()` must NOT strip ANSI codes (it currently only strips tabs/newlines/CRs, so it's already safe).

### Test updates

Existing tests use glyph values `"o"` and `"O"`. Update them:
- Where tests assert `glyph="o"`, change to assert the glyph contains `"●"`
- Where tests assert `glyph="O"`, change to assert the glyph contains `"○"`
- Add new tests for `colorize_glyph()` covering all 4 status words
- Update `test_format_input_lines_exact_shape` to use the new glyph values (assert ANSI codes present)

---

## Dependencies

**Requires**: None (this is the first phase)

**Enables**: Phase 3 (Preview Pane uses colored glyph rendering as context)

---

## Completion Criteria

- [ ] `compute_glyph()` returns Unicode circles (● / ○) instead of ASCII (o / O)
- [ ] `colorize_glyph()` wraps glyph in correct ANSI code per status
- [ ] `render_rows()` produces colored glyphs in PickerRow objects
- [ ] All existing picker tests updated and passing
- [ ] New unit tests for `colorize_glyph()` covering all 4 status words + unknown/None cases
- [ ] `uv run pytest tests/test_picker.py` passes with 0 failures
- [ ] `uv run ruff check src/croam/picker.py` clean

---

## Testing Requirements

- Update `test_format_input_lines_exact_shape` for new glyph characters
- Update any test that constructs `PickerRow` with `glyph="o"` or `glyph="O"` to use the new values
- New parametrized test for `colorize_glyph`:
  - `("running-idle", "\033[32m")` green
  - `("running-busy", "\033[33m")` yellow
  - `("archived", "\033[90m")` gray
  - `("unreachable", "\033[2m")` dim
- Test that `format_input_lines()` preserves ANSI codes in output (no stripping)

---

## Functional QA

- [ ] (pure function, Loop 3) `compute_glyph(HostStatus(name="h", reachable=True, last_probed=NOW, error=None))` returns a string containing `"●"` (filled circle Unicode character). Paste the actual return value.
- [ ] (pure function, Loop 3) `compute_glyph(HostStatus(name="h", reachable=False, last_probed=NOW, error=None))` returns a string containing `"○"` (open circle Unicode character). Paste the actual return value.
- [ ] (pure function, Loop 3) `colorize_glyph("●", "running-idle")` returns `"\033[32m●\033[0m"`. Paste actual return value.
- [ ] (pure function, Loop 3) `colorize_glyph("○", "unreachable")` returns `"\033[2m○\033[0m"`. Paste actual return value.
- [ ] (wire format, Loop 1) Call `format_input_lines()` with a PickerRow whose glyph is `"\033[32m●\033[0m"`. The output string contains the ANSI escape sequences unstripped. Paste the relevant line.

**Anti-patterns to watch for:**
- Anti-pattern 1: Don't verify colors by visual inspection. Assert exact escape code strings.
- Anti-pattern 2: Don't scatter raw escape codes. Use the mapping constant.

---

## Notes

- The `--ansi` flag is already in `build_fzf_argv()` output, so fzf will render colors.
- The `_scrub()` function only strips `\t`, `\n`, `\r`. ANSI codes pass through safely.
- `compute_glyph()` returns `"?"` for None host_status. Leave this uncolored (no status to color by).
