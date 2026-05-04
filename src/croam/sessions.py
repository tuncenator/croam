"""Local claude-code session discovery and tmux attachment queries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

from croam import proc
from croam.paths import decode_cwd


@dataclass(frozen=True)
class ClaudeSession:
    """Represents a single claude-code conversation session."""

    sid: str  # uuid string from filename stem
    cwd: Path  # decoded from <encoded-cwd> dir name; absolute
    transcript_path: Path  # absolute path to <sid>.jsonl
    pid: int | None  # None when no live ~/.claude/sessions/*.json found
    status: Literal["idle", "busy"] | None  # None when archived; coerce unknown -> "idle"
    started_at_ms: int | None  # epoch ms, from sessions/<PID>.json startedAt
    updated_at_ms: int | None  # epoch ms, from sessions/<PID>.json updatedAt
    name: str | None  # autoname or /rename; absent in many sessions
    version: str | None  # claude version, e.g. "2.1.123"


def discover_local_sessions(home: Path) -> list[ClaudeSession]:
    """Discover all claude-code sessions in the given home directory."""
    projects_dir = home / ".claude" / "projects"
    if not projects_dir.exists():
        return []

    sessions_dir = home / ".claude" / "sessions"

    # Build sid -> best metadata mapping
    sid_to_meta: dict[str, dict] = {}
    if sessions_dir.exists():
        for json_path in sorted(sessions_dir.glob("*.json")):
            try:
                with json_path.open() as f:
                    meta = json.load(f)
            except json.JSONDecodeError:
                logger.warning("Malformed session metadata; skipping {}", json_path)
                continue

            sid = meta.get("sessionId")
            if not isinstance(sid, str) or not sid:
                continue

            # Keep the entry with the highest updatedAt; tie-break by lower PID
            existing = sid_to_meta.get(sid)
            if existing is None:
                sid_to_meta[sid] = meta
            else:
                existing_updated = existing.get("updatedAt") or 0
                new_updated = meta.get("updatedAt") or 0
                if new_updated > existing_updated:
                    sid_to_meta[sid] = meta
                elif new_updated == existing_updated:
                    # Tie: lower PID wins
                    existing_pid = existing.get("pid") or float("inf")
                    new_pid = meta.get("pid") or float("inf")
                    if new_pid < existing_pid:
                        sid_to_meta[sid] = meta

    sessions: list[ClaudeSession] = []
    for subdir in projects_dir.iterdir():
        if not subdir.is_dir():
            continue
        try:
            cwd = decode_cwd(subdir.name, host_home=home)
        except (OSError, ValueError, Exception) as e:
            logger.debug("Could not decode cwd for {}; skipping: {}", subdir.name, e)
            continue

        for jsonl_path in subdir.glob("*.jsonl"):
            sid = jsonl_path.stem
            meta = sid_to_meta.get(sid)

            if meta is not None:
                raw_status = meta.get("status")
                if raw_status not in ("idle", "busy"):
                    status: Literal["idle", "busy"] | None = "idle"
                else:
                    status = raw_status  # type: ignore[assignment]

                sessions.append(
                    ClaudeSession(
                        sid=sid,
                        cwd=cwd,
                        transcript_path=jsonl_path,
                        pid=meta.get("pid"),
                        status=status,
                        started_at_ms=meta.get("startedAt"),
                        updated_at_ms=meta.get("updatedAt"),
                        name=meta.get("name"),
                        version=meta.get("version"),
                    )
                )
            else:
                sessions.append(
                    ClaudeSession(
                        sid=sid,
                        cwd=cwd,
                        transcript_path=jsonl_path,
                        pid=None,
                        status=None,
                        started_at_ms=None,
                        updated_at_ms=None,
                        name=None,
                        version=None,
                    )
                )

    # Sort: updated_at_ms desc (nulls last), then sid asc
    sessions.sort(key=lambda s: (0 if s.updated_at_ms is None else -s.updated_at_ms, s.sid))
    return sessions


def tmux_attached(sid: str, sock: Path | None = None) -> tuple[bool, bool]:
    """Query whether a claude-<sid> tmux session exists and is attached.

    Returns (has_session, attached). Both False means no tmux server or session not found.
    """
    prefix = ["tmux"]
    if sock is not None:
        prefix = ["tmux", "-S", str(sock)]

    try:
        result = proc.run([*prefix, "has-session", "-t", f"claude-{sid}"], timeout=2.0)
    except proc.CroamTimeoutError:
        logger.warning("tmux has-session timed out for sid={}", sid)
        return (False, False)

    if result.returncode != 0:
        return (False, False)

    try:
        list_result = proc.run(
            [*prefix, "list-sessions", "-F", "#{session_name}:#{session_attached}"],
            timeout=2.0,
        )
    except proc.CroamTimeoutError:
        logger.warning("tmux list-sessions timed out for sid={}", sid)
        return (True, False)

    if list_result.returncode != 0:
        logger.warning("tmux list-sessions failed for sid={}", sid)
        return (True, False)

    target_name = f"claude-{sid}"
    for line in (list_result.stdout or "").splitlines():
        parts = line.split(":", 1)
        if len(parts) == 2:
            name = parts[0].strip()
            attached_flag = parts[1].strip()
            if name == target_name:
                return (True, attached_flag != "0")

    return (True, False)
