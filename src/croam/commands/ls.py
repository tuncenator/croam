"""croam ls: list sessions in JSON or text format with filter support."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from croam.config import Config
from croam.ownership import merge_assertions, read_all_assertions, read_local_assertions
from croam.paths import denormalize_cwd
from croam.sessions import discover_local_sessions


def _session_row(
    sid: str,
    assertion: object,
    session: object,
    self_hostname: str,
    home: Path,
) -> dict[str, Any]:
    """Build a single JSON/text row dict from optional assertion + session objects."""
    from croam.ownership import Assertion
    from croam.sessions import ClaudeSession

    owner: str | None = None
    cwd: str | None = None
    last_activity: str | None = None
    is_orphan = False

    if isinstance(assertion, Assertion):
        owner = assertion.owner
        cwd = assertion.cwd_normalized
        last_activity = assertion.asserted_at.astimezone(UTC).isoformat()
    else:
        is_orphan = True

    status: str | None = None
    name: str | None = None

    if isinstance(session, ClaudeSession):
        if session.updated_at_ms is not None:
            last_activity = datetime.fromtimestamp(session.updated_at_ms / 1000, tz=UTC).isoformat()
        status = session.status
        name = session.name
        if cwd is None:
            cwd = str(session.cwd)

    host_reachable = owner == self_hostname if owner else None

    return {
        "sid": sid,
        "owner": owner,
        "host_reachable": host_reachable,
        "status": status,
        "cwd": cwd,
        "last_activity": last_activity,
        "is_orphan": is_orphan,
        "name": name,
    }


def run(
    ctx_obj: dict[str, Any],
    config: Config,
    home: Path,
) -> int:
    """List sessions: JSON or text, with --all, --host, --last, --orphans, PWD filters."""
    json_mode: bool = ctx_obj.get("json", False)
    all_mode: bool = ctx_obj.get("all", False)
    host_filter: str | None = ctx_obj.get("host")
    last_days: int | None = ctx_obj.get("last")
    orphans_only: bool = ctx_obj.get("orphans", False)

    logger.info(
        "ls: json={} all={} host={} last={} orphans={}",
        json_mode,
        all_mode,
        host_filter,
        last_days,
        orphans_only,
    )

    # 1. Discover local sessions.
    sessions = discover_local_sessions(home)
    sessions_by_sid = {s.sid: s for s in sessions}

    # 2. Read ownership assertions.
    if all_mode:
        per_host = read_all_assertions(config.storage.state_root)
    else:
        local = read_local_assertions(config.storage.state_root, config.self_hostname)
        per_host = {config.self_hostname: local}

    merged = merge_assertions(per_host)

    # 3. Build the combined set of sids to report.
    # All sids from assertions union all orphan sids (JSONLs with no assertion).
    all_sids: set[str] = set(merged.keys())
    orphan_sids: set[str] = set()
    for sid in sessions_by_sid:
        if sid not in merged:
            orphan_sids.add(sid)

    # 4. Apply filters.
    now_utc = datetime.now(UTC)

    # --host: filter by assertion owner
    if host_filter:
        all_sids = {sid for sid in all_sids if merged.get(sid) and merged[sid].owner == host_filter}

    # --orphans: show only orphans (hide from normal list; show in --orphans list)
    if orphans_only:
        working_sids: set[str] = orphan_sids
    else:
        working_sids = all_sids

    # --last: filter by last_activity within window
    if last_days is not None:
        cutoff = now_utc - timedelta(days=last_days)
        filtered: set[str] = set()
        for sid in working_sids:
            last_ms: int | None = None
            sess = sessions_by_sid.get(sid)
            if sess is not None:
                last_ms = sess.updated_at_ms
            if last_ms is None:
                assertion = merged.get(sid)
                if isinstance(assertion, object) and hasattr(assertion, "asserted_at"):
                    from croam.ownership import Assertion

                    if isinstance(assertion, Assertion):
                        last_ms = int(assertion.asserted_at.timestamp() * 1000)
            if last_ms is not None:
                last_dt = datetime.fromtimestamp(last_ms / 1000, tz=UTC)
                if last_dt >= cutoff:
                    filtered.add(sid)
        working_sids = filtered

    # PWD filter (when not --all and no --host): only sessions matching cwd
    if not all_mode and not host_filter and not orphans_only:
        pwd = Path.cwd()
        pwd_filtered: set[str] = set()
        for sid in working_sids:
            assertion = merged.get(sid)
            if assertion is not None:
                from croam.ownership import Assertion

                if isinstance(assertion, Assertion):
                    try:
                        session_cwd = denormalize_cwd(assertion.cwd_normalized, home)
                    except ValueError:
                        session_cwd = None
                    if session_cwd is not None and session_cwd == pwd:
                        pwd_filtered.add(sid)
                        continue
            # Also check local session cwd directly
            sess = sessions_by_sid.get(sid)
            if sess is not None and sess.cwd == pwd:
                pwd_filtered.add(sid)
        working_sids = pwd_filtered

    # 5. Build rows.
    rows: list[dict[str, Any]] = []
    for sid in sorted(working_sids):
        assertion = merged.get(sid)
        session = sessions_by_sid.get(sid)
        row = _session_row(sid, assertion, session, config.self_hostname, home)
        rows.append(row)

    # 6. Output.
    if json_mode:
        sys.stdout.write(json.dumps(rows, default=str) + "\n")
    else:
        if not rows:
            return 0
        for row in rows:
            owner = row["owner"] or "(orphan)"
            cwd = row["cwd"] or ""
            sid8 = row["sid"][:8]
            status = row["status"] or ""
            name = row["name"] or ""
            parts = [sid8, owner, status, cwd]
            if name:
                parts.append(name)
            sys.stdout.write("  ".join(parts) + "\n")

    return 0
