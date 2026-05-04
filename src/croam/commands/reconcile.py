"""croam reconcile: detect outclaimed sessions and prompt fork-or-discard.

When this host returns online after a peer has claimed one of its sessions,
reconcile detects the outclaim, compares snapshot line count vs current JSONL
line count, and either auto-discards (no new work) or prompts the user to
fork or discard.

All prompts use input(), NOT typer.prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from loguru import logger

from croam.commands import fork as fork_mod
from croam.ownership import (
    detect_outclaim,
    merge_assertions,
    read_all_assertions,
    read_local_assertions,
    write_local_assertions,
)
from croam.snapshots import get_snapshot_line_count


def _find_jsonl(home: Path, sid: str) -> Path | None:
    """Locate the JSONL transcript for sid under ~/.claude/projects/."""
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


def _count_lines(path: Path) -> int:
    """Count lines in a file using bytes."""
    data = path.read_bytes()
    if not data:
        return 0
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        return len(lines) - 1
    return len(lines)


def detect_outclaimed(state_root: Path, hostname: str) -> list[str]:
    """Return sids that were claimed away by a peer.

    Wraps ownership.detect_outclaim with the full read-all-merge pipeline.
    """
    per_host = read_all_assertions(state_root)
    merged = merge_assertions(per_host)
    return detect_outclaim(state_root, hostname, merged)


def _discard(sid: str, state_root: Path, hostname: str, home: Path) -> None:
    """Discard a session: remove local assertion and optionally the JSONL."""
    local = read_local_assertions(state_root, hostname)
    local = {s: a for s, a in local.items() if s != sid}
    write_local_assertions(state_root, hostname, local)
    logger.info("reconcile: discarded sid={}", sid)

    # Optionally remove the orphaned JSONL.
    jsonl_path = _find_jsonl(home, sid)
    if jsonl_path is not None and jsonl_path.exists():
        jsonl_path.unlink()
        logger.info("reconcile: removed orphaned JSONL at {}", jsonl_path)


def reconcile_one(
    sid: str,
    *,
    state_root: Path,
    hostname: str,
    home: Path,
) -> Literal["fork", "discard"]:
    """Reconcile a single outclaimed session.

    Compares snapshot line_count vs current JSONL:
    - If no new lines (or no JSONL): auto-discard.
    - If new lines (or no snapshot): prompt fork-or-discard.

    Returns the action taken.
    """
    snapshot_lc = get_snapshot_line_count(state_root, hostname, sid)
    jsonl_path = _find_jsonl(home, sid)

    if jsonl_path is None or not jsonl_path.exists():
        # No JSONL: auto-discard.
        _discard(sid, state_root, hostname, home)
        return "discard"

    current_lc = _count_lines(jsonl_path)

    if snapshot_lc is not None and current_lc <= snapshot_lc:
        # No new work since claim: auto-discard.
        _discard(sid, state_root, hostname, home)
        return "discard"

    # New lines exist (or no snapshot to compare against): prompt.
    new_lines = current_lc - (snapshot_lc or 0)
    logger.info(
        "reconcile: sid={} has {} new lines since claim (current={}, snapshot={})",
        sid,
        new_lines,
        current_lc,
        snapshot_lc,
    )

    try:
        answer = input(
            f"Session {sid[:8]}... has {new_lines} new lines since it was claimed away. "
            f"[f]ork or [d]iscard? "
        )
    except EOFError:
        answer = "d"

    if answer.strip().lower() == "f":
        # Fork the session.
        fork_mod.run(sid, state_root=state_root, hostname=hostname, home=home)
        _discard(sid, state_root, hostname, home)
        return "fork"
    else:
        _discard(sid, state_root, hostname, home)
        return "discard"


def reconcile_all(
    *,
    state_root: Path,
    hostname: str,
    home: Path,
) -> list[tuple[str, Literal["fork", "discard"]]]:
    """Reconcile all outclaimed sessions. Returns list of (sid, action)."""
    outclaimed = detect_outclaimed(state_root, hostname)
    if not outclaimed:
        return []

    results: list[tuple[str, Literal["fork", "discard"]]] = []
    for sid in outclaimed:
        action = reconcile_one(sid, state_root=state_root, hostname=hostname, home=home)
        results.append((sid, action))
    return results
