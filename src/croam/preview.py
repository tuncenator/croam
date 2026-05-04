"""Preview pane rendering for the fzf picker.

Produces a metadata block (owner, status, cwd, actions) and a conversation
tail (last N messages) for a given session id. Invoked by fzf via
`croam preview {1}` on every cursor movement, so speed matters.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from croam.transcript import _extract_text

# ---------------------------------------------------------------------------
# Conversation tail extraction
# ---------------------------------------------------------------------------

_TAIL_TYPES = {"user", "assistant"}


def extract_conversation_tail(
    jsonl_path: Path,
    n: int = 10,
    max_msg_chars: int = 200,
) -> list[tuple[str, str]]:
    """Return the last *n* user/assistant messages from a JSONL transcript.

    Each entry is a (role, text) tuple. Messages longer than *max_msg_chars*
    are truncated with a "..." suffix. Returns an empty list on missing or
    unreadable files.
    """
    try:
        raw = jsonl_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("extract_conversation_tail: cannot read {}: {}", jsonl_path, exc)
        return []

    messages: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        msg_type = obj.get("type")
        if msg_type not in _TAIL_TYPES:
            continue
        text = _extract_text(obj.get("message", "")).strip()
        if len(text) > max_msg_chars:
            text = text[:max_msg_chars] + "..."
        messages.append((msg_type, text))

    return messages[-n:]


# ---------------------------------------------------------------------------
# Session lookup (targeted, not full discovery)
# ---------------------------------------------------------------------------


def _find_transcript(sid: str, home: Path) -> Path | None:
    """Scan ~/.claude/projects/*/ for <sid>.jsonl. Returns path or None."""
    projects_dir = home / ".claude" / "projects"
    if not projects_dir.exists():
        return None
    for subdir in projects_dir.iterdir():
        if not subdir.is_dir():
            continue
        candidate = subdir / f"{sid}.jsonl"
        if candidate.exists():
            return candidate
    return None


def _find_session_metadata(sid: str, home: Path) -> dict | None:
    """Find session metadata for *sid* in ~/.claude/sessions/*.json.

    Returns the parsed JSON dict or None. If multiple files reference
    the same sid, keeps the one with the highest updatedAt.
    """
    sessions_dir = home / ".claude" / "sessions"
    if not sessions_dir.exists():
        return None
    best: dict | None = None
    for json_path in sessions_dir.glob("*.json"):
        try:
            meta = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(meta, dict) or meta.get("sessionId") != sid:
            continue
        if best is None or (meta.get("updatedAt") or 0) > (best.get("updatedAt") or 0):
            best = meta
    return best


def _find_owner(sid: str, home: Path) -> str:
    """Look up the owner hostname for *sid* from the assertions store.

    Scans ~/.local/share/croam/*/ownership.json. Returns the owner string
    or "unknown" if no assertion is found.
    """
    state_root = home / ".local" / "share" / "croam"
    if not state_root.exists():
        return "unknown"
    for host_dir in state_root.iterdir():
        if not host_dir.is_dir():
            continue
        ownership_file = host_dir / "ownership.json"
        if not ownership_file.exists():
            continue
        try:
            data = json.loads(ownership_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        entry = data.get(sid)
        if isinstance(entry, dict) and "owner" in entry:
            return entry["owner"]
    return "unknown"


def _derive_status(meta: dict | None) -> str:
    """Derive the status word from session metadata.

    Returns one of: running-idle, running-busy, archived.
    """
    if meta is None or meta.get("pid") is None:
        return "archived"
    raw = meta.get("status")
    if raw == "busy":
        return "running-busy"
    return "running-idle"


def _derive_actions(status: str, cwd_exists: bool) -> list[str]:
    """List available actions based on status and cwd presence."""
    actions = ["peek"]
    if status.startswith("running"):
        actions.append("attach")
    if cwd_exists:
        actions.append("claim")
        actions.append("fork")
    actions.append("claim-here")
    actions.append("fork-here")
    return actions


# ---------------------------------------------------------------------------
# Preview renderer
# ---------------------------------------------------------------------------


def render_preview(sid: str, home: Path) -> str:
    """Build the full preview pane text for a session.

    Returns a formatted string with a metadata block and conversation tail.
    Never raises; returns a fallback message on any error.
    """
    # Import fish_truncate_path here to avoid circular import at module level.
    from croam.picker import fish_truncate_path

    transcript_path = _find_transcript(sid, home)
    if transcript_path is None:
        return f"sid: {sid}\n(preview unavailable: session not found)"

    meta = _find_session_metadata(sid, home)
    owner = _find_owner(sid, home)
    status = _derive_status(meta)

    # Derive cwd from transcript location: parent dir name is the encoded cwd.
    from croam.paths import decode_cwd

    try:
        cwd_raw = str(decode_cwd(transcript_path.parent.name, host_home=home))
    except Exception:
        cwd_raw = str(transcript_path.parent.name)

    cwd_display = fish_truncate_path(cwd_raw, str(home))
    cwd_exists = Path(cwd_raw).is_dir()
    actions = _derive_actions(status, cwd_exists)

    # Metadata block.
    lines = [
        f"Owner:   {owner}",
        f"Status:  {status}",
        f"CWD:     {cwd_display}",
        f"Actions: {', '.join(actions)}",
    ]

    # Conversation tail.
    tail = extract_conversation_tail(transcript_path)
    if tail:
        lines.append("")
        lines.append(f"--- last {len(tail)} messages ---")
        lines.append("")
        for role, text in tail:
            lines.append(f"[{role}] {text}")
    else:
        lines.append("")
        lines.append("(no messages)")

    return "\n".join(lines)
