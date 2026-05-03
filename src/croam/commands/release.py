"""croam release: receiving side of the claim handshake.

Called on the origin host (the current owner) during a remote claim.
Writes a release assertion, optionally emits JSONL content to stdout,
and removes the local JSONL file.

Idempotent: if called for a sid we don't own or that's already released,
logs no-op and returns 0.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from croam.ownership import Assertion, read_local_assertions, write_local_assertion


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


def run(
    sid: str,
    *,
    state_root: Path,
    hostname: str,
    home: Path,
    emit_jsonl: bool = False,
) -> int:
    """Release ownership of a session.

    Steps:
    1. Check local ownership. If we don't own it, log no-op and return 0.
    2. If emit_jsonl=True, print the JSONL content to stdout (for remote copy).
    3. Write a release assertion (action="release").
    4. Remove the local JSONL file.

    Returns 0 on success.
    """
    local_assertions = read_local_assertions(state_root, hostname)
    current = local_assertions.get(sid)

    if current is None or current.owner != hostname:
        logger.info("release: no-op; sid={} not owned by {}", sid, hostname)
        return 0

    if current.action == "release":
        logger.info("release: no-op; sid={} already released by {}", sid, hostname)
        return 0

    # Locate JSONL before writing assertion.
    jsonl_path = _find_jsonl(home, sid)

    # Emit JSONL content if requested (for remote claim to copy).
    if emit_jsonl and jsonl_path is not None and jsonl_path.exists():
        content = jsonl_path.read_bytes()
        sys.stdout.buffer.write(content)
        sys.stdout.buffer.flush()

    # Write release assertion.
    release_assertion = Assertion(
        sid=sid,
        owner=hostname,
        asserted_at=datetime.now(UTC),
        action="release",
        cwd_normalized=current.cwd_normalized,
    )
    write_local_assertion(state_root, hostname, release_assertion)
    logger.info("release: wrote release assertion for sid={} hostname={}", sid, hostname)

    # Remove local JSONL.
    if jsonl_path is not None and jsonl_path.exists():
        jsonl_path.unlink()
        logger.info("release: removed JSONL at {}", jsonl_path)

    return 0
