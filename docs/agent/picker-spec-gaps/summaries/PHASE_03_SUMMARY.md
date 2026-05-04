# Phase 3: Preview Pane - Summary

**Date Completed:** 2026-05-04
**Actual Token Usage:** ~40k tokens

---

## Objective

Replace the preview pane stub with a real preview showing a metadata block (owner, status, cwd, available actions) and a conversation tail (last N messages from the JSONL transcript).

---

## Work Completed

### What Was Built

- `extract_conversation_tail()`: reads JSONL, filters to user/assistant messages, returns last N as (role, text) tuples with truncation
- `render_preview()`: orchestrates session lookup, metadata block, and conversation tail into a single formatted string
- Targeted session lookup helpers (`_find_transcript`, `_find_session_metadata`, `_find_owner`) that avoid full `discover_local_sessions` scans
- `_derive_status()` and `_derive_actions()` for metadata block fields
- `croam preview <sid>` CLI subcommand (hidden, for fzf invocation)
- `build_fzf_argv()` wired with `--preview=croam preview {1}`

### Files Created

- `src/croam/preview.py` - Preview pane rendering module
- `tests/test_preview.py` - 11 tests for preview functionality

### Files Modified

- `src/croam/picker.py` - Replaced `--preview` stub with `croam preview {1}`
- `src/croam/cli.py` - Added hidden `preview` subcommand

### Key Design Decisions

- Targeted session lookup by sid (scan projects/*/sid.jsonl, sessions/*.json, ownership.json) instead of calling `discover_local_sessions()`. Keeps preview fast since fzf re-invokes on every cursor movement.
- Owner lookup scans `~/.local/share/croam/*/ownership.json` directly rather than going through the full assertion merge pipeline.
- `croam preview {1}` invoked via the package script entry point, not via `sys.executable -m`. Since pyproject.toml defines the `croam` script, it's on PATH when installed.

---

## Completion Criteria Status

- [x] `src/croam/preview.py` exists with `render_preview()` and `extract_conversation_tail()` - Verified: file exists, both functions importable
- [x] `croam preview <sid>` CLI subcommand works and prints formatted preview - Verified: Functional QA check 3
- [x] Preview shows metadata block: owner, status, cwd (fish-truncated), actions - Verified: Functional QA check 3 output contains all fields
- [x] Preview shows conversation tail: last 10 messages formatted as [user]/[assistant] - Verified: Functional QA check 3 shows all 5 messages
- [x] `build_fzf_argv()` uses `croam preview {1}` as the --preview command - Verified: Functional QA check 5
- [x] Graceful fallback when session not found - Verified: Functional QA check 4 returns `sid: nonexistent-sid\n(preview unavailable: session not found)`
- [x] Messages truncated at 200 chars with "..." suffix - Verified: test_extract_conversation_tail_truncation passes
- [x] Unit tests for `render_preview()` and `extract_conversation_tail()` - Verified: 11 tests in test_preview.py
- [x] All existing tests pass - Verified: `uv run pytest` 439 passed, 4 skipped
- [x] `uv run pytest` passes with 0 failures - Verified: 439 passed
- [x] `uv run ruff check src/croam/preview.py` clean - Verified: All checks passed

---

## Testing

### Tests Written

- `tests/test_preview.py`
  - test_extract_conversation_tail_happy_path_last_n
  - test_extract_conversation_tail_short_transcript
  - test_extract_conversation_tail_truncation
  - test_extract_conversation_tail_skips_non_user_assistant
  - test_extract_conversation_tail_empty_file
  - test_extract_conversation_tail_file_not_found
  - test_render_preview_full
  - test_render_preview_session_not_found
  - test_render_preview_no_transcript_messages
  - test_render_preview_archived_session
  - test_build_fzf_argv_uses_croam_preview

### Test Results

```
$ uv run pytest tests/test_preview.py -v --tb=short
tests/test_preview.py::test_extract_conversation_tail_happy_path_last_n PASSED [  9%]
tests/test_preview.py::test_extract_conversation_tail_short_transcript PASSED [ 18%]
tests/test_preview.py::test_extract_conversation_tail_truncation PASSED  [ 27%]
tests/test_preview.py::test_extract_conversation_tail_skips_non_user_assistant PASSED [ 36%]
tests/test_preview.py::test_extract_conversation_tail_empty_file PASSED  [ 45%]
tests/test_preview.py::test_extract_conversation_tail_file_not_found PASSED [ 54%]
tests/test_preview.py::test_render_preview_full PASSED                   [ 63%]
tests/test_preview.py::test_render_preview_session_not_found PASSED      [ 72%]
tests/test_preview.py::test_render_preview_no_transcript_messages PASSED [ 81%]
tests/test_preview.py::test_render_preview_archived_session PASSED       [ 90%]
tests/test_preview.py::test_build_fzf_argv_uses_croam_preview PASSED     [100%]

============================== 11 passed in 0.07s ==============================
```

Full suite:

```
$ uv run pytest --tb=short -q
439 passed, 4 skipped in 6.68s
```

---

## Evidence Captured

### JSONL Transcript Format (user/assistant entries)

- **How captured**: Observed via existing test fixtures and synth_jsonl.py, consistent with codebase context
- **Consumed by**: `src/croam/preview.py:extract_conversation_tail()` (line 42-58)
- **Sample**:

  ```json
  {"type": "user", "message": {"role": "user", "content": "help me debug the auth flow"}, "uuid": "...", "timestamp": 1000}
  {"type": "assistant", "message": {"role": "assistant", "content": "I'll look at..."}, "uuid": "...", "timestamp": 1001}
  {"type": "last-prompt", "leafUuid": "...", "sessionId": "..."}
  ```

- **Notes**: Only `type: "user"` and `type: "assistant"` entries have the message.content field we extract. Other types (last-prompt, permission-mode, tool_use, system) are filtered out.

### Session Metadata Format (sessions/*.json)

- **How captured**: Observed via synth_session.py and existing sessions.py patterns
- **Consumed by**: `src/croam/preview.py:_find_session_metadata()` (line 82-99)
- **Sample**:

  ```json
  {"pid": 42, "sessionId": "abc-123", "cwd": "/home/tunc/Programs/croam", "startedAt": 1714824000000, "status": "idle", "updatedAt": 1714824060000, "version": "2.1.123"}
  ```

### Ownership Assertion Format (ownership.json)

- **How captured**: Observed via ownership.py read_local_assertions pattern
- **Consumed by**: `src/croam/preview.py:_find_owner()` (line 102-120)
- **Sample**:

  ```json
  {"sid-here": {"owner": "stormtree", "asserted_at": "2026-05-04T10:00:00+00:00", "action": "create", "cwd_normalized": "/home/tunc/Programs/croam", "previous_owner": null}}
  ```

---

## Functional QA Results

### Check 1: extract_conversation_tail with n=5 on 8 messages

- **Surface**: Pure formatting functions (library surface)
- **Invocation**: `extract_conversation_tail(jsonl, n=5)` on synthetic JSONL with 8 user+assistant messages
- **Observed outcome**:

  ```
  [('assistant', 'message 3'), ('user', 'message 4'), ('assistant', 'message 5'), ('user', 'message 6'), ('assistant', 'message 7')]
  ```

- **Verdict**: pass

### Check 2: extract_conversation_tail on nonexistent path

- **Surface**: Pure formatting functions (library surface)
- **Invocation**: `extract_conversation_tail(home / 'nonexistent.jsonl')`
- **Observed outcome**:

  ```
  []
  ```

- **Verdict**: pass

### Check 3: render_preview with known session data

- **Surface**: Pure formatting functions (library surface)
- **Invocation**: `render_preview(sid, home)` with owner="stormtree", status idle, cwd="/home/.../Programs/croam", 5 messages
- **Observed outcome**:

  ```
  Owner:   stormtree
  Status:  running-idle
  CWD:     ~/P/croam
  Actions: peek, attach, claim, fork, claim-here, fork-here

  --- last 5 messages ---

  [user] help me debug the auth flow
  [assistant] I will look at the authentication middleware...
  [user] the token refresh is failing
  [assistant] Let me check the refresh endpoint...
  [user] that fixed it, thanks
  ```

- **Verdict**: pass

### Check 4: render_preview for nonexistent sid

- **Surface**: Pure formatting functions (library surface)
- **Invocation**: `render_preview('nonexistent-sid', home)`
- **Observed outcome**:

  ```
  'sid: nonexistent-sid\n(preview unavailable: session not found)'
  ```

- **Verdict**: pass

### Check 5: build_fzf_argv --preview element

- **Surface**: fzf picker (interactive TUI)
- **Invocation**: `build_fzf_argv(filter_pwd=None, keyfile="/tmp/k")`, filter for `--preview=`
- **Observed outcome**:

  ```
  '--preview=croam preview {1}'
  ```

- **Verdict**: pass

### Anti-Patterns Watched For

- **Anti-pattern 5 (mocking fzf to test preview)**: Tested `render_preview()` directly as a pure function. Did not attempt to capture fzf preview window output.
- **Anti-pattern 6 (importing render_static_transcript for preview)**: `extract_conversation_tail` is independent from `render_static_transcript`. Only shared dependency is `_extract_text` from transcript.py.

### Strategy Updates

No strategy updates.

---

## Dependencies

### Required by This Phase
- Phase 1: Glyph/color infrastructure
- Phase 2: `fish_truncate_path()` for CWD display

### Unblocked Phases
None (this is the final phase)

---

## Codebase Context Updates

- Added `src/croam/preview.py` to Key Files: Preview pane rendering (metadata block + conversation tail)
- Added `extract_conversation_tail()` and `render_preview()` to Important APIs
- Added `croam preview <sid>` to CLI subcommands list
- Updated `build_fzf_argv()` description: now uses `croam preview {1}` instead of printf stub
- Added `tests/test_preview.py` to Key Files: 11 tests for preview module

## Notes for Future Phases

- The owner lookup in `_find_owner()` does a simple scan of ownership.json files. If performance becomes an issue with many hosts, consider caching or passing the merged assertions dict.
- `_derive_actions()` is a simplified version of `_row_safe_actions()` from picker.py. If the action logic grows more complex, consider consolidating.
- The preview reads the entire JSONL to get the tail. For very large transcripts (>1MB), this could be slow. Consider reading from the end of the file if needed.

---

## Integration Points

- `render_preview()` is called by `croam preview <sid>` CLI subcommand
- fzf invokes `croam preview {1}` on every cursor movement via `--preview`
- Reuses `fish_truncate_path()` from picker.py and `_extract_text()` from transcript.py
- Reuses `decode_cwd()` from paths.py for deriving cwd from project directory name

---

## Known Issues / Technical Debt

- `_find_owner()` reads ownership.json files directly instead of going through the ownership module's `read_local_assertions()`. This avoids the full validation overhead but means schema changes need to be reflected in two places.
- The preview subprocess is spawned fresh on every cursor movement. With `croam` installed as a package script, Python startup time adds latency. If this becomes noticeable, consider a socket-based preview server.
