"""Syncthing mirror read helpers (filesystem-only, no syncthing API calls).

All functions are pure: they read from the filesystem and return data. They
never write. Syncthing manages the actual sync; we only read what it produces.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger


def read_peer_state_from_mirror(state_root: Path, peer_hostname: str) -> dict[str, Any] | None:
    """Read <state_root>/<peer>/{ownership.json,lineage.json,host-cache.json}.

    Returns dict with keys 'ownership', 'lineage', 'host_cache' (parsed JSON
    or {} when absent). Returns None if peer subdir itself does not exist.
    """
    peer_dir = state_root / peer_hostname
    if not peer_dir.exists():
        return None

    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[return-value]
        except json.JSONDecodeError as e:
            logger.warning("sync: malformed JSON in {}: {}", path, e)
            return {}

    return {
        "ownership": _read_json(peer_dir / "ownership.json"),
        "lineage": _read_json(peer_dir / "lineage.json"),
        "host_cache": _read_json(peer_dir / "host-cache.json"),
    }


def detect_conflict_files(state_root: Path) -> list[Path]:
    """Glob '*.sync-conflict-*' at any depth under state_root. Sorted. Empty if none."""
    if not state_root.exists():
        return []
    return sorted(state_root.rglob("*.sync-conflict-*"))


def mirror_freshness(state_root: Path, peer_hostname: str) -> timedelta | None:
    """Time since most recent mtime under <state_root>/<peer>.

    Returns None if subdir is missing or empty.
    """
    peer_dir = state_root / peer_hostname
    if not peer_dir.exists():
        return None

    latest_mtime: float | None = None
    for path in peer_dir.rglob("*"):
        if path.is_file():
            mtime = path.stat().st_mtime
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime

    if latest_mtime is None:
        return None

    now = datetime.now(UTC)
    file_dt = datetime.fromtimestamp(latest_mtime, tz=UTC)
    return now - file_dt


def mirror_jsonl_path(
    state_root: Path,
    peer_hostname: str,
    encoded_cwd: str,
    sid: str,
) -> Path | None:
    """Return path to peer's mirrored JSONL or None if not present.

    Looks for <state_root>/<peer>/projects/<encoded_cwd>/<sid>.jsonl
    following claude-code's project layout convention.
    """
    candidate = state_root / peer_hostname / "projects" / encoded_cwd / f"{sid}.jsonl"
    if candidate.exists():
        return candidate
    return None
