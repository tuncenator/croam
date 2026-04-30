"""Synthesize a claude session-metadata JSON file for tests.

Schema observed in CODEBASE_CONTEXT.md "Data Models" section.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def build_session_metadata(
    home: Path,
    pid: int,
    sid: str,
    cwd: Path,
    *,
    status: str = "idle",
    started_at_ms: int | None = None,
    name: str | None = None,
    version: str = "2.1.123",
    kind: str = "interactive",
    entrypoint: str = "cli",
    proc_start: str = "98776537",
) -> Path:
    """Write ~/.claude/sessions/<pid>.json.

    The schema mirrors the captured dummy at /tmp/croam-e2e (claude 2.1.123).
    `name` is omitted from the JSON if None (consistent with claude's behavior:
    only set after /rename).
    """
    sessions_dir = home / ".claude" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    out = sessions_dir / f"{pid}.json"
    now_ms = int(time.time() * 1000)
    data: dict = {
        "pid": pid,
        "sessionId": sid,
        "cwd": str(cwd),
        "startedAt": started_at_ms if started_at_ms is not None else now_ms,
        "procStart": proc_start,
        "version": version,
        "peerProtocol": 1,
        "kind": kind,
        "entrypoint": entrypoint,
        "status": status,
        "updatedAt": now_ms,
    }
    if name is not None:
        data["name"] = name
    out.write_text(json.dumps(data, indent=2))
    return out
