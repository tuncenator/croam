"""SSH reachability probes and inter-host state wire format."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from croam import proc
from croam.sessions import ClaudeSession, discover_local_sessions


@dataclass(frozen=True)
class HostStatus:
    """SSH reachability result for a single host."""

    name: str
    reachable: bool
    last_probed: datetime  # tz-aware UTC
    error: str | None  # None when reachable; populated otherwise


def _probe_one(host: str, timeout_s: float, now: datetime) -> HostStatus:
    """Probe a single host via SSH and return its reachability status."""
    argv = [
        "ssh",
        "-o",
        f"ConnectTimeout={int(timeout_s)}",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        host,
        "true",
    ]
    try:
        result = proc.run(argv, timeout=timeout_s + 1.0)
    except proc.CroamTimeoutError:
        return HostStatus(name=host, reachable=False, last_probed=now, error="timeout")
    if result.returncode == 0:
        return HostStatus(name=host, reachable=True, last_probed=now, error=None)
    err = (result.stderr or "").strip() or f"ssh exited {result.returncode}"
    return HostStatus(name=host, reachable=False, last_probed=now, error=err)


def probe_reachability(hosts: list[str], timeout_s: float = 2.0) -> dict[str, HostStatus]:
    """Probe SSH reachability for all hosts in parallel.

    Returns a dict mapping hostname to HostStatus. Empty dict for empty input.
    """
    if not hosts:
        return {}
    now = datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=min(8, len(hosts))) as executor:
        futures = {host: executor.submit(_probe_one, host, timeout_s, now) for host in hosts}
    return {host: future.result() for host, future in futures.items()}


def _read_json_or_none(path: Path) -> dict | None:
    """Read and parse a JSON file, returning None if missing or malformed."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        logger.warning("Malformed JSON in {}; ignoring: {}", path, e)
        return None


def _session_to_wire(s: ClaudeSession) -> dict:
    """Serialize a ClaudeSession to a JSON-safe dict for the wire format."""
    return {
        "sid": s.sid,
        "cwd": str(s.cwd),
        "transcript_path": str(s.transcript_path),
        "pid": s.pid,
        "status": s.status,
        "started_at_ms": s.started_at_ms,
        "updated_at_ms": s.updated_at_ms,
        "name": s.name,
        "version": s.version,
    }


def emit_state(home: Path, state_root: Path, hostname: str) -> dict:
    """Build the JSON wire payload for croam emit-state."""
    host_dir = state_root / hostname
    return {
        "hostname": hostname,
        "ownership": _read_json_or_none(host_dir / "ownership.json"),
        "lineage": _read_json_or_none(host_dir / "lineage.json"),
        "host_cache": _read_json_or_none(host_dir / "host-cache.json"),
        "sessions": [_session_to_wire(s) for s in discover_local_sessions(home)],
    }


def fetch_remote_state(host: str, ssh_alias: str, timeout_s: float = 5.0) -> dict | None:
    """Fetch the emit-state payload from a remote host via SSH.

    Returns parsed dict on success, None on timeout/error/bad JSON.
    """
    argv = [
        "ssh",
        "-o",
        "ConnectTimeout=2",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        ssh_alias,
        "croam",
        "emit-state",
        "--json",
    ]
    try:
        result = proc.run(argv, timeout=timeout_s)
    except proc.CroamTimeoutError:
        logger.warning("fetch_remote_state {} timeout", host)
        return None
    if result.returncode != 0:
        logger.warning(
            "fetch_remote_state {} rc={} stderr={!r}", host, result.returncode, result.stderr
        )
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.warning("fetch_remote_state {} bad JSON: {}", host, e)
        return None
