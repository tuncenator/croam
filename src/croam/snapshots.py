"""Snapshot-line-count sidecar store.

Stores <state_root>/<hostname>/snapshots.json with the line count of each
session's JSONL at claim/fork time. Used by reconcile to detect whether new
work was added after a session was claimed away.

Separate from ownership.json to avoid coupling the Assertion dataclass.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from croam.errors import OwnershipConflict

# Re-use the same atomic write helper from ownership.
from croam.ownership import _atomic_write_json


def read_snapshots(state_root: Path, hostname: str) -> dict[str, int]:
    """Read <state_root>/<hostname>/snapshots.json. Returns {} if absent.

    Returns a dict mapping sid -> line_count.
    Raises OwnershipConflict on malformed JSON or unexpected schema.
    """
    path = state_root / hostname / "snapshots.json"
    if not path.exists():
        return {}
    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise OwnershipConflict(f"Malformed JSON in {path}: {e}") from e
    if not isinstance(payload, dict):
        raise OwnershipConflict(
            f"Expected object in {path}, got {type(payload).__name__}"
        )
    result: dict[str, int] = {}
    for sid, entry in payload.items():
        if isinstance(entry, dict):
            lc = entry.get("line_count", 0)
            result[sid] = int(lc)
        elif isinstance(entry, int):
            result[sid] = entry
        else:
            logger.warning("snapshots: ignoring malformed entry for sid={}", sid)
    return result


def write_snapshot(state_root: Path, hostname: str, sid: str, line_count: int) -> None:
    """Write or update a single snapshot entry atomically."""
    existing = {}
    path = state_root / hostname / "snapshots.json"
    if path.exists():
        try:
            existing = read_snapshots(state_root, hostname)
        except OwnershipConflict:
            existing = {}
    existing[sid] = line_count
    # Serialize as {"sid": {"line_count": N}} for future extensibility.
    payload = {s: {"line_count": lc} for s, lc in sorted(existing.items())}
    _atomic_write_json(path, payload)
    logger.debug("snapshots.write_snapshot: hostname={} sid={} line_count={}", hostname, sid, line_count)


def get_snapshot_line_count(state_root: Path, hostname: str, sid: str) -> int | None:
    """Return the snapshot line count for a sid, or None if not present."""
    snapshots = read_snapshots(state_root, hostname)
    if sid in snapshots:
        return snapshots[sid]
    return None
