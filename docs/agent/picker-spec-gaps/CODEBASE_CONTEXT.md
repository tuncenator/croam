# Codebase Context

> **Living document** -- each phase updates this with new discoveries and changes.
> Read this before exploring the codebase. It may already have what you need.
>
> Last updated by: Checkpoint 2 - Phase 2 Display Formatting (2026-05-04)

---

## Architecture Overview

croam is a cross-host claude-code session manager. It discovers claude-code sessions across multiple machines (via syncthing-replicated state), displays them in an fzf-based picker, and provides actions (attach, peek, claim, fork) on selected sessions.

Key layers:
- **CLI** (`src/croam/cli.py`): typer-based CLI entry point, subcommands
- **Session discovery** (`src/croam/sessions.py`): scans `~/.claude/projects/` and `~/.claude/sessions/` to build `ClaudeSession` objects
- **Ownership** (`src/croam/ownership.py`): assertion-based ownership tracking across hosts
- **Picker** (`src/croam/picker.py`): fzf row rendering, argv construction, subprocess orchestration, action intersection
- **Transcript** (`src/croam/transcript.py`): read-only JSONL transcript rendering
- **Host probing** (`src/croam/hosts.py`): SSH-based reachability checks

---

## Key Files & Modules

| File Path | Purpose | Notes |
|-----------|---------|-------|
| `src/croam/picker.py` | Picker row rendering, fzf orchestration | Main target for this feature |
| `src/croam/transcript.py` | JSONL transcript parsing and rendering | Has `_extract_text()` for content block parsing |
| `src/croam/sessions.py` | Session discovery from `~/.claude/` | Provides `ClaudeSession` dataclass |
| `src/croam/hosts.py` | Host reachability probing | Provides `HostStatus` dataclass |
| `src/croam/ownership.py` | Ownership assertion tracking | Provides `Assertion` dataclass |
| `src/croam/paths.py` | Path encoding/decoding for claude project dirs | `decode_cwd()`, `encode_cwd()` |
| `src/croam/cli.py` | CLI entry point (typer) | Subcommands: ls, attach, peek, claim, fork, etc. |
| `src/croam/errors.py` | Custom exception hierarchy | `CroamError` base class |
| `src/croam/log.py` | Loguru configuration | Already set up |
| `tests/conftest.py` | Test fixtures: fake HOME, ssh shim, safety guard | `home` fixture redirects HOME to tmp |
| `tests/_helpers/fake_fzf.py` | Fake fzf binary for picker tests | `make_fake_fzf()` creates a script that outputs canned data |
| `tests/_helpers/synth_jsonl.py` | Synthetic JSONL transcript builder | `build_jsonl()` creates test transcripts |
| `tests/_helpers/synth_session.py` | Synthetic session metadata builder | Session JSON file creation |
| `tests/test_display_formatting.py` | Tests for fish_truncate_path, extract_first_user_message, render_rows integration | 22 tests covering Phase 2 display formatting |
| `tests/test_picker.py` | Picker unit/integration tests | 15+ tests covering formatters, rows, fzf argv, launch |

---

## Important APIs & Interfaces

### ClaudeSession (src/croam/sessions.py)

```python
@dataclass(frozen=True)
class ClaudeSession:
    sid: str                          # uuid from filename stem
    cwd: Path                         # decoded from dir name; absolute
    transcript_path: Path             # absolute path to <sid>.jsonl
    pid: int | None                   # None when no live session
    status: Literal["idle", "busy"] | None  # None when archived
    started_at_ms: int | None
    updated_at_ms: int | None
    name: str | None                  # autoname or /rename; absent in many sessions
    version: str | None
```

### HostStatus (src/croam/hosts.py)

```python
@dataclass(frozen=True)
class HostStatus:
    name: str
    reachable: bool
    last_probed: datetime
    error: str | None
```

### PickerRow (src/croam/picker.py)

```python
@dataclass(frozen=True)
class PickerRow:
    sid: str           # column 1 (hidden)
    glyph: str         # column 2 (displayed)
    status_word: str   # column 3 (hidden)
    reach_word: str    # column 4 (hidden)
    cwd_word: str      # column 5 (hidden)
    host: str          # column 6 (displayed)
    last: str          # column 7 (displayed)
    cwd_display: str   # column 8 (displayed)
    name: str          # column 9 (displayed)
```

### Key picker functions

- `compute_glyph(host_status: HostStatus | None) -> str`: Returns Unicode circle glyphs: `"●"` reachable, `"○"` unreachable, `"?"` unknown
- `colorize_glyph(glyph: str, status_word: str) -> str`: Wraps glyph in ANSI escape codes based on status_word (green/yellow/gray/dim); unknown status returns glyph unchanged
- `compute_status_word(session, host_status) -> str`: Returns status category string
- `fish_truncate_path(path: str, home: str) -> str`: Fish-shell style path truncation (abbreviates intermediate components to first char, replaces home prefix with `~`)
- `extract_first_user_message(jsonl_path: Path, max_chars: int = 80) -> str | None`: Returns first non-empty user message from JSONL transcript, truncated to max_chars with `...` suffix; returns None on missing files or no user messages. Uses `_extract_text()` from transcript.py via local import.
- `format_last_column(updated_at_ms: int | None, now: datetime) -> str`: Relative time formatting
- `render_rows(sessions, assertions, host_statuses, pwd, lineage, ...) -> list[PickerRow]`: Main row builder. Applies `fish_truncate_path()` to `cwd_display`. For unnamed sessions, falls back to first user message then `sid[:8]`.
- `format_input_lines(rows: list[PickerRow]) -> str`: Tab-joined fzf stdin wire format
- `build_fzf_argv(filter_pwd, *, keyfile) -> list[str]`: Constructs fzf argv with two-mode bindings
- `launch_picker(rows, filter_pwd, ...) -> tuple[str, list[PickerRow]]`: Runs fzf subprocess

### transcript.py

- `_extract_text(message_field: object) -> str`: Extracts plain text from JSONL message field (handles string, dict with content string, dict with content block list)
- `render_static_transcript(jsonl_path: Path, *, fp: TextIO) -> int`: Renders full transcript as [user]/[assistant] lines

### synth_jsonl.py (test helper)

- `build_jsonl(home, sid, cwd, *, n_user=1, version="2.1.123") -> Path`: Creates synthetic JSONL transcript with metadata lines + user entries

---

## Patterns & Conventions

- **Frozen dataclasses**: All data objects are `@dataclass(frozen=True)` for immutability
- **Pure functions**: Formatting helpers are stateless pure functions; side effects isolated to `launch_picker()`
- **Test safety**: All tests require HOME redirection via the `home` fixture. The `pytest_runtest_call` hook enforces this.
- **Fake subprocess pattern**: Tests that involve fzf use `make_fake_fzf()` which creates an executable script in `tmp_path` that emits canned stdout and optionally writes to a keyfile
- **Wire format**: fzf stdin is tab-delimited columns with `--with-nth=2,6,7,8,9` controlling which columns are visible. Column 1 (sid) is always hidden but used for identification.
- **ANSI passthrough**: fzf is invoked with `--ansi` flag, so ANSI escape sequences in the input are rendered as colors. `render_rows()` now applies `colorize_glyph()` so `PickerRow.glyph` contains ANSI-wrapped Unicode circles.
- **Status-to-color mapping**: `_STATUS_ANSI` dict maps status_word to ANSI codes: `running-idle` -> green (`\033[32m`), `running-busy` -> yellow (`\033[33m`), `archived` -> gray (`\033[90m`), `unreachable` -> dim (`\033[2m`)

### End-to-end picker flow

1. CLI command collects sessions, assertions, host_statuses
2. `render_rows()` joins them into `PickerRow` objects
3. `format_input_lines()` serializes rows as tab-separated lines
4. `build_fzf_argv()` builds the fzf command with bindings
5. `launch_picker()` spawns fzf with stdin data, reads stdout for selections
6. CLI dispatches action based on returned (expect_key, selected_rows)

---

## Data Models

### JSONL Transcript Format

Each line is a JSON object. Key types:
- `{"type": "last-prompt", "leafUuid": ..., "sessionId": ...}` - metadata
- `{"type": "permission-mode", ...}` - metadata
- `{"type": "user", "message": {"role": "user", "content": ...}, "uuid": ..., "timestamp": ..., "cwd": ...}` - user message
- `{"type": "assistant", "message": {"role": "assistant", "content": ...}, ...}` - assistant message

The `message.content` field can be:
- A plain string
- A list of content blocks: `[{"type": "text", "text": "..."}, ...]`

---

## Dependencies & Integration Points

- fzf must be installed on the system (external binary)
- Sessions come from `~/.claude/projects/<encoded-cwd>/<sid>.jsonl`
- Session metadata from `~/.claude/sessions/<pid>.json`
- Host probing via SSH (uses `src/croam/hosts.py`)

---

## Environment & Configuration

- **Build**: `uv sync` installs deps into `.venv/`
- **Test**: `uv run pytest` (activates venv automatically)
- **Lint**: `uv run ruff check src/ tests/`
- **Type check**: `uv run pyright`
- **Run**: `uv run croam <subcommand>`

---

## External Services & APIs

No external services for this feature. All data is local filesystem (JSONL files, session metadata JSON).
