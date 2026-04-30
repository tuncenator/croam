"""Synthesize a parseable claude conversation transcript for tests.

Used by Phases 3, 4, 7, 8. Phase 1 owns this helper; later phases must NOT
reimplement the schema.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


def _encode_cwd(cwd: Path) -> str:
    """Local copy of paths.encode_cwd for use before Phase 2 lands.

    Each `/` and each leading `.` of a path component becomes `-`.
    Phase 2 implements the canonical version in src/croam/paths.py.
    Phase 2's tests verify these match.
    """
    parts = [p for p in str(cwd).split("/") if p != ""]
    enc = ""
    for part in parts:
        enc += "-"
        if part.startswith("."):
            enc += "-" + part[1:]
        else:
            enc += part
    return enc


def build_jsonl(
    home: Path,
    sid: str,
    cwd: Path,
    *,
    n_user: int = 1,
    version: str = "2.1.123",
) -> Path:
    """Write a synthetic claude transcript to ~/.claude/projects/<encoded>/<sid>.jsonl.

    Returns the full path. Format follows the schema observed in the dummy:
        - line 1: last-prompt
        - line 2: permission-mode
        - lines 3..n: user entries

    `home` is the test's redirected HOME. `cwd` is the conversation's recorded cwd
    (absolute path on the originating host).
    """
    encoded = _encode_cwd(cwd)
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    out = proj_dir / f"{sid}.jsonl"
    now_ms = int(time.time() * 1000)

    lines: list[dict] = [
        {"type": "last-prompt", "leafUuid": str(uuid.uuid4()), "sessionId": sid},
        {"type": "permission-mode", "permissionMode": "default", "sessionId": sid},
    ]
    parent_uuid = str(uuid.uuid4())
    for i in range(n_user):
        msg_uuid = str(uuid.uuid4())
        lines.append(
            {
                "parentUuid": parent_uuid,
                "isSidechain": False,
                "promptId": str(uuid.uuid4()),
                "type": "user",
                "message": {"role": "user", "content": f"synthetic prompt {i}"},
                "uuid": msg_uuid,
                "timestamp": now_ms + i,
                "permissionMode": "default",
                "userType": "external",
                "entrypoint": "cli",
                "cwd": str(cwd),
                "sessionId": sid,
                "version": version,
                "gitBranch": "master",
            }
        )
        parent_uuid = msg_uuid

    with out.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return out
