# Phase 3: Preview Pane

**Feature**: picker-spec-gaps
**Estimated Context Budget**: ~80k tokens

**Difficulty**: hard
**Visual**: no
**Functional**: yes

**Execution Mode**: sequential
**Batch**: 3

---

## Objective

Replace the preview pane stub with a real preview showing a metadata block (owner, status, cwd, available actions) and a conversation tail (last N messages from the JSONL transcript).

---

## Deliverables

1. New module `src/croam/preview.py` with preview rendering logic
2. Modified `build_fzf_argv()` in `src/croam/picker.py` to invoke the preview script
3. New test file `tests/test_preview.py`
4. CLI entry point for the preview command (invokable by fzf's `--preview`)

---

## Detailed Requirements

### Architecture decision: how fzf invokes the preview

fzf's `--preview` takes a shell command where `{1}` is the first field (sid in our wire format). The preview command must:
1. Be a standalone invokable command (fzf spawns it as a subprocess)
2. Accept the sid as an argument
3. Print formatted text to stdout
4. Exit quickly (fzf re-invokes it on every cursor movement)

**Approach**: Add a `croam preview <sid>` subcommand to the CLI. fzf invokes `croam preview {1}`. This keeps the preview logic inside the croam package with full access to session discovery and transcript reading.

### Preview output format

```
Owner:   stormtree
Status:  running-idle
CWD:     ~/P/o/i/iam
Actions: attach, peek, claim, fork

--- last 10 messages ---

[user] help me debug the auth flow
[assistant] I'll look at the authentication middleware...
[user] the token refresh is failing
[assistant] Let me check the refresh endpoint...
```

### Preview rendering function

Create `src/croam/preview.py`:

```python
def render_preview(sid: str, home: Path) -> str:
```

**Steps:**
1. Discover the session: scan `~/.claude/sessions/*.json` for the matching sid to get metadata (owner from assertions, status, pid). Also find the transcript path by scanning `~/.claude/projects/`.
2. Build the metadata block:
   - **Owner**: from the assertion file for this sid (fall back to "unknown")
   - **Status**: derive from session metadata (running-idle/running-busy/archived/unreachable)
   - **CWD**: fish-truncated path (reuse `fish_truncate_path` from picker.py)
   - **Actions**: list available actions based on reachability and cwd presence (reuse `_row_safe_actions` logic)
3. Build the conversation tail:
   - Read the JSONL transcript
   - Extract the last N messages (N=10 by default) of type "user" or "assistant"
   - Format as `[user] <text>` / `[assistant] <text>`
   - Truncate each message to 200 chars (for preview readability)
4. Join metadata block + separator + conversation tail
5. Return as a single string

**Reuse from existing code:**
- `fish_truncate_path()` from `src/croam/picker.py` (Phase 2)
- `_extract_text()` from `src/croam/transcript.py`
- Session discovery patterns from `src/croam/sessions.py`

### Conversation tail extraction

Create a helper in `src/croam/preview.py`:

```python
def extract_conversation_tail(jsonl_path: Path, n: int = 10, max_msg_chars: int = 200) -> list[tuple[str, str]]:
```

Returns a list of `(role, text)` tuples for the last `n` user/assistant messages.

**Algorithm:**
1. Read all lines from the JSONL file
2. Filter to lines where `type` is `"user"` or `"assistant"`
3. For each, extract text via `_extract_text(obj.get("message", ""))`
4. Keep only the last `n` entries
5. Truncate each text to `max_msg_chars` (append "..." if truncated)
6. Return as list of (type, text) tuples

**Note:** Reading the entire file to get the tail is acceptable. JSONL files are typically <1MB. For very large transcripts, this might be slow, but optimization is out of scope.

### CLI subcommand

Add to `src/croam/cli.py`:

```python
@app.command()
def preview(sid: str) -> None:
    """Render preview pane for a session (called by fzf --preview)."""
```

This command calls `render_preview(sid, Path.home())` and prints to stdout. On any error, print a minimal fallback (e.g., `"sid: {sid}\n(preview unavailable)"`) instead of crashing.

### Wiring into build_fzf_argv()

Replace the current preview stub:

```python
# Before:
"--preview=printf 'sid: {1}\\n(preview pane to be filled in v2)\\n'",

# After:
"--preview=croam preview {1}",
```

This assumes `croam` is on PATH (it is, since the user installed the package). If running via `uv run croam`, the preview also needs to go through `uv run`. Check how the picker itself is invoked. If the test uses a fake fzf, the preview command is never actually called during tests (fzf isn't really running). For integration, the user will have croam installed.

**Alternative if PATH isn't guaranteed**: Use `sys.executable` to get the Python path and invoke as a module:
```python
f"--preview={sys.executable} -m croam preview {{1}}",
```

Decide based on how the CLI is structured. Since `pyproject.toml` defines `croam = "croam.cli:main"` as a script entry point, `croam` should be on PATH when installed. Use `croam preview {1}`.

### Session lookup for preview

The preview function needs to find session data by sid. Reuse the discovery logic but optimize for single-sid lookup:

```python
def _find_session_for_preview(sid: str, home: Path) -> tuple[ClaudeSession | None, str]:
```

Returns the ClaudeSession and the owner hostname. Implementation:
1. Check `~/.claude/sessions/*.json` for a metadata entry with matching sessionId
2. Scan `~/.claude/projects/*/` for `<sid>.jsonl`
3. If found, construct a minimal ClaudeSession
4. For owner: check the assertions store (simplified lookup)

For the preview, we don't need the full multi-host discovery. A simplified lookup is fine. If the session isn't found locally, return None and the preview shows "session not found".

---

## Dependencies

**Requires**:
- Phase 1: Glyph/color infrastructure exists (for consistent status display)
- Phase 2: `fish_truncate_path()` exists for CWD display, `extract_first_user_message()` pattern established

**Enables**: Nothing (this is the final phase)

---

## Completion Criteria

- [ ] `src/croam/preview.py` exists with `render_preview()` and `extract_conversation_tail()`
- [ ] `croam preview <sid>` CLI subcommand works and prints formatted preview
- [ ] Preview shows metadata block: owner, status, cwd (fish-truncated), actions
- [ ] Preview shows conversation tail: last 10 messages formatted as [user]/[assistant]
- [ ] `build_fzf_argv()` uses `croam preview {1}` as the --preview command
- [ ] Graceful fallback when session not found (prints "session not found" instead of crashing)
- [ ] Messages truncated at 200 chars with "..." suffix
- [ ] Unit tests for `render_preview()` and `extract_conversation_tail()`
- [ ] All existing tests pass (no regression from --preview change)
- [ ] `uv run pytest` passes with 0 failures
- [ ] `uv run ruff check src/croam/preview.py` clean

---

## Testing Requirements

### tests/test_preview.py

**extract_conversation_tail tests:**
- Happy path: JSONL with 15 messages returns last 10
- Short transcript: JSONL with 3 messages returns all 3
- Truncation: messages over 200 chars are truncated with "..."
- Mixed types: only user/assistant messages included (tool_use, system skipped)
- Empty file: returns empty list
- File not found: returns empty list (or raises; decide on error handling)

**render_preview tests:**
- Full preview with known session data: verify output contains owner, status, cwd, actions, messages
- Session not found: verify graceful fallback output
- Session with no transcript: metadata block shown, conversation section says "(no transcript)"

**Integration:**
- Test that `build_fzf_argv()` output contains `--preview=croam preview {1}` (or the chosen invocation form)

### Existing test updates

- `test_build_fzf_argv_includes_required_flags`: update the assertion about `--preview` to match the new command (no longer checks for "preview pane to be filled in v2")

---

## Functional QA

- [ ] (pure function, Loop 3) Call `extract_conversation_tail(jsonl_path, n=5)` on a synthetic JSONL with 8 user+assistant messages. Returns exactly the last 5 entries as (role, text) tuples. Paste actual return value.
- [ ] (pure function, Loop 3) Call `extract_conversation_tail(nonexistent_path)` returns an empty list (no crash). Paste actual return value.
- [ ] (integration, Loop 2) Call `render_preview(sid, home)` where `sid` maps to a session with owner="stormtree", status idle, cwd="/home/tunc/Programs/croam", and a 5-message transcript. Output contains "Owner:   stormtree", fish-truncated cwd "~/P/croam", and the last 5 messages formatted as [user]/[assistant]. Paste full output.
- [ ] (integration, Loop 2) Call `render_preview("nonexistent-sid", home)` returns graceful fallback text (not a crash/traceback). Paste actual output.
- [ ] (wire format, Loop 1) `build_fzf_argv(filter_pwd=None, keyfile="/tmp/k")` contains an element matching `--preview=croam preview {1}`. Paste the matching argv element.

**Anti-patterns to watch for:**
- Anti-pattern 5: Don't mock fzf to test the preview. Test `render_preview()` directly as a pure function.
- Anti-pattern 6: Don't test preview by importing `render_static_transcript`. The preview needs only the tail, not the full renderer.

---

## Notes

- The preview is invoked by fzf on every cursor movement. Keep `render_preview()` fast. Avoid unnecessary file scanning.
- For the `_find_session_for_preview` lookup, don't call the full `discover_local_sessions()` (which scans all projects). Instead, do a targeted lookup: check sessions dir for the sid, then find its transcript.
- The `Assertion` lookup for owner may require reading the assertions store. If this is complex, simplify: check if there's a straightforward way to get the owner for a sid from the existing data structures. If not, display "unknown" and note it for future improvement.
- Consider caching or memoizing if performance becomes an issue, but don't over-engineer for this phase.
