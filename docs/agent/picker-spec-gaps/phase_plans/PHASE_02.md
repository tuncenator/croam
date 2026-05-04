# Phase 2: Display Formatting

**Feature**: picker-spec-gaps
**Estimated Context Budget**: ~60k tokens

**Difficulty**: medium
**Visual**: no
**Functional**: yes

**Execution Mode**: sequential
**Batch**: 2

---

## Objective

Add fish-style cwd path truncation and first-user-message fallback for unnamed sessions, so picker rows show concise, informative labels.

---

## Deliverables

1. New function `fish_truncate_path(path: str, home: str) -> str` in `src/croam/picker.py`
2. New function `extract_first_user_message(jsonl_path: Path, max_chars: int = 80) -> str | None` in `src/croam/picker.py`
3. Modified `render_rows()` to apply fish truncation to `cwd_display` and first-message fallback to `name`
4. Tests for both new functions and integration with `render_rows()`

---

## Detailed Requirements

### Fish-style cwd truncation

Implement `fish_truncate_path(path: str, home: str) -> str`:

**Algorithm:**
1. If `path` starts with `home + "/"`, replace that prefix with `"~/"`
2. If `path == home`, return `"~"`
3. Split the remaining path by `/`
4. Keep the LAST component in full
5. Truncate each intermediate component to its first character only
6. Join with `/`

**Examples** (assuming home = `/home/tunc`):
- `/home/tunc/Programs/onlayer-x/internal/iam` -> `~/P/o/i/iam`
- `/home/tunc/Programs/croam` -> `~/P/croam`
- `/home/tunc` -> `~`
- `/opt/services/myapp` -> `/o/s/myapp` (no home prefix)
- `/` -> `/`
- `/usr` -> `/usr` (single component, nothing to truncate)

**Edge cases:**
- Path equal to home: return `"~"`
- Path is root `/`: return `"/"`
- Single component after prefix: return as-is (e.g. `~/croam`)
- Components starting with `.`: keep the dot + first char (e.g. `.config` -> `.c`)

### First-user-message extraction

Implement `extract_first_user_message(jsonl_path: Path, max_chars: int = 80) -> str | None`:

**Algorithm:**
1. Open the JSONL file, read line by line
2. For each line, parse as JSON
3. Skip lines where `type` is not `"user"`
4. On the first `"user"` line, extract the text using the same logic as `transcript.py:_extract_text()` (import and reuse it)
5. Strip leading/trailing whitespace from the extracted text
6. If the text is empty after stripping, continue to the next user line
7. Truncate to `max_chars` characters. If truncated, append `"..."` (total length = max_chars + 3)
8. Return the text, or `None` if no non-empty user message found

**Reuse `_extract_text()`** from `src/croam/transcript.py`. Import it:
```python
from croam.transcript import _extract_text
```

Note: `_extract_text` is private (underscore prefix) but it's within the same package. This is acceptable for internal reuse.

**Robustness:**
- If `jsonl_path` does not exist or is unreadable, return `None` (log at debug level)
- If a line fails JSON parsing, skip it (don't abort)
- Stop reading after the first valid user message (don't scan the whole file)

### Wiring into render_rows()

In `render_rows()`, modify two assignments:

**cwd_display** (currently line 124):
```python
# Before:
cwd_display = cwd_normalized if assertion else str(session.cwd)

# After:
raw_cwd = cwd_normalized if assertion else str(session.cwd)
cwd_display = fish_truncate_path(raw_cwd, str(Path.home()))
```

Note: `Path.home()` gives the current user's home. For test compatibility, the `home` fixture overrides `HOME` env var, so `Path.home()` in tests returns the fake home. This is correct because we're truncating for display on the LOCAL machine.

But wait: the `host_homes` parameter already exists. Use it if available for the session's owner. If `host_homes` is `None` or the owner isn't in it, fall back to `Path.home()`. Actually, for display truncation, always use the local machine's home since we're displaying on this terminal. Use `str(Path.home())`.

**name** (currently line 127):
```python
# Before:
base_name = session.name or session.sid[:8]

# After:
base_name = session.name
if base_name is None:
    base_name = extract_first_user_message(session.transcript_path) or session.sid[:8]
```

This means: prefer session.name, then first-user-message, then sid[:8] as last resort.

---

## Dependencies

**Requires**: None (independent of Phase 1's glyph/color changes)

**Enables**: Phase 3 (Preview Pane can reuse fish truncation and knows about first-message extraction)

---

## Completion Criteria

- [ ] `fish_truncate_path()` correctly truncates paths per the algorithm above
- [ ] `fish_truncate_path()` handles all edge cases (root, home itself, dotfiles, no home prefix)
- [ ] `extract_first_user_message()` returns the first non-empty user message text
- [ ] `extract_first_user_message()` returns None for missing/unreadable files
- [ ] `extract_first_user_message()` truncates at max_chars with "..." suffix
- [ ] `render_rows()` produces fish-truncated cwd_display
- [ ] `render_rows()` uses first-user-message when session.name is None
- [ ] All existing tests pass (update assertions for new cwd_display format)
- [ ] `uv run pytest` passes with 0 failures
- [ ] `uv run ruff check src/croam/picker.py` clean

---

## Testing Requirements

### fish_truncate_path tests

New parametrized test `test_fish_truncate_path` covering:
- Standard case: `/home/tunc/Programs/onlayer-x/internal/iam` -> `~/P/o/i/iam`
- Short path: `/home/tunc/Programs/croam` -> `~/P/croam`
- Home itself: `/home/tunc` -> `~`
- No home prefix: `/opt/services/myapp` -> `/o/s/myapp`
- Root: `/` -> `/`
- Single component: `/usr` -> `/usr`
- Dotfile component: `/home/tunc/.config/croam` -> `~/.c/croam`
- Tilde-prefixed input: `~/Programs/croam` -> `~/P/croam` (handle ~ prefix)

### extract_first_user_message tests

- Happy path: transcript with user messages returns first one
- Truncation: message longer than 80 chars gets truncated with "..."
- Empty content: skips empty user messages, returns next non-empty one
- No user messages: returns None
- File not found: returns None
- Malformed JSON lines: skips them, still finds user message

### render_rows integration

- Verify cwd_display is fish-truncated in output rows
- Verify unnamed session (name=None) gets first-user-message as name
- Verify named session still uses session.name

---

## Functional QA

- [ ] (pure function, Loop 3) `fish_truncate_path("/home/tunc/Programs/onlayer-x/internal/iam", "/home/tunc")` returns exactly `"~/P/o/i/iam"`. Paste actual return value.
- [ ] (pure function, Loop 3) `fish_truncate_path("/home/tunc", "/home/tunc")` returns exactly `"~"`. Paste actual return value.
- [ ] (pure function, Loop 3) `fish_truncate_path("/opt/services/myapp", "/home/tunc")` returns exactly `"/o/s/myapp"`. Paste actual return value.
- [ ] (pure function, Loop 3) Call `extract_first_user_message()` on a synthetic JSONL (created with `build_jsonl(home, sid, cwd, n_user=1)`) whose first user message content is `"synthetic prompt 0"`. Returns `"synthetic prompt 0"`. Paste actual return value.
- [ ] (pure function, Loop 3) Call `extract_first_user_message()` on a nonexistent path. Returns `None`. Paste actual return value.
- [ ] (integration, Loop 1) Call `render_rows()` with a session whose `name=None` and whose transcript contains a user message `"help me debug the auth flow"`. The resulting `PickerRow.name` contains `"help me debug the auth flow"` (not the sid[:8]). Paste actual row.name value.

**Anti-patterns to watch for:**
- Anti-pattern 3: Test fish truncation edge cases, not just the happy path.
- Anti-pattern 4: Test extract_first_user_message against realistic JSONL shapes (tool_use lines before first user, multi-block content), not just synth_jsonl output.

---

## Notes

- The `_extract_text` function in `transcript.py` is underscore-prefixed but importing it cross-module within the package is fine for this project.
- `render_rows()` calls `extract_first_user_message()` for every session without a name. For large session lists this could be slow (file I/O per session). Acceptable for now; optimization (caching, lazy loading) is out of scope.
- The existing `test_format_input_lines_exact_shape` test uses hardcoded `cwd_display` values. These DON'T need updating because `format_input_lines` just formats whatever `cwd_display` is in the PickerRow (it doesn't call fish truncation itself). The truncation happens in `render_rows()`.
