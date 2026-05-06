"""Preview pane rendering for the fzf picker.

Produces a metadata block (owner, status, cwd, actions) and a conversation
tail (last N messages) for a given session id. Invoked by fzf via
``croam preview {1}`` on every cursor movement, so speed matters.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from croam.transcript import _extract_text

_TAIL_TYPES = {"user", "assistant"}
_MAX_LINES_PER_MSG = 8


def extract_conversation_tail(
    jsonl_path: Path,
    n: int = 20,
) -> list[tuple[str, str]]:
    """Return the last *n* user/assistant messages from a JSONL transcript."""
    try:
        raw = jsonl_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("extract_conversation_tail: cannot read {}: {}", jsonl_path, exc)
        return []
    return _parse_tail(raw, n)


def _extract_tail_from_text(
    raw: str,
    n: int = 20,
) -> list[tuple[str, str]]:
    """Parse conversation tail from raw JSONL text (local or SSH-fetched)."""
    return _parse_tail(raw, n)


def _parse_tail(
    raw: str,
    n: int,
) -> list[tuple[str, str]]:
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
        if not text:
            continue
        if msg_type == "user" and text.startswith("<"):
            continue
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
    """Find session metadata for *sid* in ~/.claude/sessions/*.json."""
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


def _find_assertion(sid: str, state_root: Path) -> tuple[str, str] | None:
    """Look up owner and cwd_normalized for *sid* from the assertions store.

    Returns (owner, cwd_normalized) or None.
    """
    if not state_root.exists():
        return None
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
            cwd = entry.get("cwd_normalized", "")
            return entry["owner"], cwd
    return None


def _read_remote_transcript(
    sid: str,
    ssh_alias: str,
    timeout_s: float = 3.0,
) -> str | None:
    """SSH to a remote host and cat the transcript for *sid*.

    Returns raw JSONL text or None on failure.
    """
    from croam import proc
    from croam.errors import TimeoutError as CroamTimeoutError

    cmd = f'f=$(find -L ~/.claude/projects -name "{sid}.jsonl" -print -quit 2>/dev/null) && [ -n "$f" ] && cat "$f"'
    argv = [
        "ssh",
        "-o", "ConnectTimeout=2",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        ssh_alias,
        "bash", "-c", cmd,
    ]
    try:
        result = proc.run(argv, timeout=timeout_s)
    except CroamTimeoutError:
        logger.debug("_read_remote_transcript: SSH timeout for sid={} host={}", sid, ssh_alias)
        return None
    if result.returncode != 0:
        logger.debug("_read_remote_transcript: SSH failed for sid={} host={}", sid, ssh_alias)
        return None
    if not result.stdout.strip():
        return None
    return result.stdout


def _derive_status(meta: dict | None) -> str:
    if meta is None or meta.get("pid") is None:
        return "archived"
    raw = meta.get("status")
    if raw == "busy":
        return "running-busy"
    return "running-idle"


def _derive_actions(status: str, cwd_exists: bool) -> list[str]:
    actions = ["peek"]
    if status.startswith("running"):
        actions.append("attach")
    if cwd_exists:
        actions.append("claim")
        actions.append("fork")
    actions.append("claim-here")
    actions.append("fork-here")
    return actions


def _format_tail(tail: list[tuple[str, str]]) -> list[str]:
    """Format conversation tail with visual hierarchy.

    User messages prefixed with ``>>> ``, assistant messages indented with
    ``    ``.  Up to 8 lines per message; overflow shows a count.
    """
    if not tail:
        return ["", "(no messages)"]
    lines = ["", f"--- last {len(tail)} messages ---", ""]
    for role, text in tail:
        prefix = ">>> " if role == "user" else "    "
        msg_lines = text.split("\n")
        for i, ml in enumerate(msg_lines[:_MAX_LINES_PER_MSG]):
            if i == 0:
                lines.append(f"{prefix}{ml}")
            else:
                lines.append(f"    {ml}")
        overflow = len(msg_lines) - _MAX_LINES_PER_MSG
        if overflow > 0:
            lines.append(f"    ... ({overflow} more lines)")
        lines.append("")
    return lines


def _try_mirror_transcript(
    sid: str,
    owner: str,
    cwd_normalized: str,
    config: object | None,
    home: Path,
    state_root: Path,
) -> list[tuple[str, str]] | None:
    """Try reading a transcript from the syncthing mirror directory.

    Returns parsed tail or None if no mirror exists.
    """
    from croam.config import Config
    from croam.paths import denormalize_cwd, encode_cwd

    owner_home = home
    if isinstance(config, Config):
        host_entry = config.hosts.get(owner)
        if host_entry is not None and host_entry.home is not None:
            owner_home = host_entry.home

    try:
        cwd_abs = denormalize_cwd(cwd_normalized, owner_home)
        encoded = encode_cwd(cwd_abs)
    except (ValueError, Exception) as exc:
        logger.debug("_try_mirror_transcript: path resolution failed: {}", exc)
        return None

    mirror_path = state_root / owner / "projects" / encoded / f"{sid}.jsonl"
    if not mirror_path.exists():
        return None

    return extract_conversation_tail(mirror_path)


# ---------------------------------------------------------------------------
# Preview renderer
# ---------------------------------------------------------------------------


def render_preview(sid: str, home: Path) -> str:
    """Build the full preview pane text for a session.

    Handles both local sessions (transcript in ~/.claude/projects/) and
    remote sessions (transcript fetched via SSH from the owning host).
    """
    from croam.config import load_config
    from croam.picker import fish_truncate_path

    try:
        config = load_config()
    except Exception:
        config = None

    state_root = config.storage.state_root if config else home / ".local" / "share" / "croam"

    # Try local transcript first.
    transcript_path = _find_transcript(sid, home)

    if transcript_path is not None:
        return _render_local(sid, home, state_root, transcript_path, config)

    # No local transcript. Check assertions for remote session info.
    assertion = _find_assertion(sid, state_root)
    if assertion is None:
        return f"sid: {sid}\n(session not found)"

    owner, cwd_normalized = assertion
    cwd_display = fish_truncate_path(
        cwd_normalized.replace("~", str(home), 1) if cwd_normalized.startswith("~") else cwd_normalized,
        str(home),
    )
    meta = _find_session_metadata(sid, home)
    status = _derive_status(meta)
    cwd_raw = cwd_normalized.replace("~", str(home), 1) if cwd_normalized.startswith("~") else cwd_normalized
    cwd_exists = Path(cwd_raw).is_dir()
    actions = _derive_actions(status, cwd_exists)

    lines = [
        f"Owner:   {owner}",
        f"Status:  {status}",
        f"CWD:     {cwd_display}",
        f"Actions: {', '.join(actions)}",
    ]

    # If owner is this host, the transcript simply doesn't exist locally.
    self_hostname = config.self_hostname if config else None
    is_local_owner = self_hostname is not None and owner == self_hostname

    if is_local_owner:
        lines.append("")
        lines.append("(no transcript)")
        return "\n".join(lines)

    # Remote owner: try SSH, then syncthing mirror.
    ssh_alias = _resolve_ssh_alias(owner, config)
    if ssh_alias is not None:
        raw = _read_remote_transcript(sid, ssh_alias)
        if raw is not None:
            tail = _extract_tail_from_text(raw)
            lines.extend(_format_tail(tail))
            return "\n".join(lines)

    mirror_tail = _try_mirror_transcript(sid, owner, cwd_normalized, config, home, state_root)
    if mirror_tail is not None:
        lines.extend(_format_tail(mirror_tail))
        return "\n".join(lines)

    lines.append("")
    lines.append(f"(transcript on {owner}, not reachable)")
    return "\n".join(lines)


def _render_local(
    sid: str,
    home: Path,
    state_root: Path,
    transcript_path: Path,
    config: object | None,
) -> str:
    from croam.paths import decode_cwd
    from croam.picker import fish_truncate_path

    assertion = _find_assertion(sid, state_root)
    owner = assertion[0] if assertion else "local"
    meta = _find_session_metadata(sid, home)
    status = _derive_status(meta)

    try:
        cwd_raw = str(decode_cwd(transcript_path.parent.name, host_home=home))
    except Exception:
        cwd_raw = str(transcript_path.parent.name)

    cwd_display = fish_truncate_path(cwd_raw, str(home))
    cwd_exists = Path(cwd_raw).is_dir()
    actions = _derive_actions(status, cwd_exists)

    lines = [
        f"Owner:   {owner}",
        f"Status:  {status}",
        f"CWD:     {cwd_display}",
        f"Actions: {', '.join(actions)}",
    ]

    tail = extract_conversation_tail(transcript_path)
    lines.extend(_format_tail(tail))
    return "\n".join(lines)


def _resolve_ssh_alias(hostname: str, config: object | None) -> str | None:
    """Get the SSH alias for a hostname from config. Returns None if unknown."""
    if config is None:
        return None
    from croam.config import Config
    if not isinstance(config, Config):
        return None
    entry = config.hosts.get(hostname)
    if entry is None:
        return None
    return entry.ssh
