"""croam claim: transfer ownership to this host.

State machine:
  S0: Lookup sid in merged assertions -> determine current owner.
  S1: Self-owned shortcut -> return 0 (already ours).
  S2: ssh-strict pre-verify -> fetch emit-state from owner, confirm no conflict.
  S3: Cooperative if reachable (release on origin, copy JSONL), forced if not.
  S4: Write claim assertion locally.
  S5: --here rewrite (place JSONL under CWD encoding) if requested.
  S6: Flatten + snapshot.

Race window between S2 pass and S4 write is acknowledged, not fixed.
After successful claim, do NOT auto-attach.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from croam import proc
from croam.config import load_config
from croam.errors import SessionNotFound
from croam.ownership import (
    Assertion,
    flatten_local,
    merge_assertions,
    read_all_assertions,
    write_local_assertion,
)
from croam.paths import encode_cwd, normalize_cwd
from croam.snapshots import write_snapshot


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
    """Count lines in a file using bytes to avoid encoding issues."""
    data = path.read_bytes()
    if not data:
        return 0
    lines = data.split(b"\n")
    # Trailing newline produces an empty final element
    if lines and lines[-1] == b"":
        return len(lines) - 1
    return len(lines)


def _probe_reachable(ssh_alias: str) -> bool:
    """Check if a host is reachable via SSH."""
    argv = [
        "ssh",
        "-o", "ConnectTimeout=2",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        ssh_alias,
        "true",
    ]
    try:
        result = proc.run(argv, timeout=3.0)
    except proc.CroamTimeoutError:
        return False
    return result.returncode == 0


def _fetch_remote_state(ssh_alias: str) -> dict | None:
    """Fetch emit-state JSON from remote host."""
    argv = [
        "ssh",
        "-o", "ConnectTimeout=2",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        ssh_alias,
        "croam", "emit-state", "--json",
    ]
    try:
        result = proc.run(argv, timeout=5.0)
    except proc.CroamTimeoutError:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def _remote_release(ssh_alias: str, sid: str) -> bool:
    """Ask remote host to release a session."""
    argv = [
        "ssh",
        "-o", "ConnectTimeout=2",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        ssh_alias,
        "croam", "release", sid,
    ]
    try:
        result = proc.run(argv, timeout=5.0)
    except proc.CroamTimeoutError:
        return False
    return result.returncode == 0


def _remote_fetch_jsonl(ssh_alias: str, remote_path: str) -> bytes | None:
    """Fetch JSONL content from remote host via cat over SSH."""
    argv = [
        "ssh",
        "-o", "ConnectTimeout=2",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        ssh_alias,
        "cat", remote_path,
    ]
    try:
        result = proc.run(argv, timeout=10.0, capture=True)
    except proc.CroamTimeoutError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.encode("utf-8") if result.stdout else None


def _get_ssh_alias(owner: str, config_path: Path) -> str:
    """Get SSH alias for a host from config."""
    config = load_config(config_path)
    entry = config.hosts.get(owner)
    if entry is not None:
        return entry.ssh
    return owner


def run(
    sid: str,
    *,
    state_root: Path,
    hostname: str,
    home: Path,
    config_path: Path,
    here: bool = False,
) -> int:
    """Claim ownership of a session.

    State machine: S0 -> S1 -> S2 -> S3 -> S4 -> S5 -> S6.
    Returns 0 on success, 1 if user refuses forced claim.
    Raises SessionNotFound if sid is unknown.
    """
    config = load_config(config_path)

    # S0: Lookup.
    per_host = read_all_assertions(state_root)
    merged = merge_assertions(per_host)

    if sid not in merged:
        raise SessionNotFound(f"session {sid!r} not found in any ownership records")

    current_owner = merged[sid].owner
    cwd_normalized = merged[sid].cwd_normalized

    # S1: Self-owned shortcut.
    if current_owner == hostname:
        logger.info("claim: sid={} already owned by self; no-op", sid)
        return 0

    # Determine verification mode.
    claim_verify = config.ownership.claim_verify
    ssh_alias = _get_ssh_alias(current_owner, config_path)

    reachable = False
    if claim_verify == "ssh-strict":
        # S2: SSH-strict pre-verify.
        reachable = _probe_reachable(ssh_alias)

        if reachable:
            # Fetch remote state to confirm no conflict.
            remote_state = _fetch_remote_state(ssh_alias)
            if remote_state is not None:
                remote_ownership = remote_state.get("ownership")
                if isinstance(remote_ownership, dict) and sid in remote_ownership:
                    remote_entry = remote_ownership[sid]
                    if remote_entry.get("owner") != current_owner:
                        logger.warning(
                            "claim: ssh-strict conflict; remote says owner={}, local says owner={}",
                            remote_entry.get("owner"),
                            current_owner,
                        )
        else:
            # Origin unreachable: ask for confirmation.
            logger.warning("claim: origin {} unreachable", current_owner)
            try:
                answer = input(
                    f"Origin {current_owner} unreachable. Force claim? [y/N] "
                )
            except EOFError:
                answer = "n"
            if answer.strip().lower() != "y":
                return 1

    # S3: Cooperative release (if reachable) or forced (if not/local mode).
    jsonl_path = _find_jsonl(home, sid)

    if reachable and claim_verify == "ssh-strict":
        # Cooperative: release on origin, then fetch JSONL.
        _remote_release(ssh_alias, sid)

        # Try to fetch JSONL from remote if we don't have it locally.
        if jsonl_path is None:
            # Determine remote path from cwd_normalized.
            # The remote JSONL might already be gone (release removes it),
            # but try before it's cleaned up.
            remote_jsonl = _fetch_remote_jsonl_by_sid(ssh_alias, sid, cwd_normalized, home)
            if remote_jsonl is not None:
                # Write locally.
                if here:
                    target_cwd = Path.cwd()
                    encoded = encode_cwd(target_cwd)
                    cwd_normalized = normalize_cwd(target_cwd, home)
                else:
                    encoded = encode_cwd(home / cwd_normalized.replace("~/", "")) if cwd_normalized.startswith("~/") else encode_cwd(Path(cwd_normalized))
                dst_dir = home / ".claude" / "projects" / encoded
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst_path = dst_dir / f"{sid}.jsonl"
                dst_path.write_bytes(remote_jsonl)
                jsonl_path = dst_path
    elif jsonl_path is None:
        # Forced claim or local mode: JSONL must already exist locally (syncthing mirror).
        # If not, we still proceed with the claim but log a warning.
        logger.warning("claim: JSONL for sid={} not found locally; claim proceeds without transcript", sid)

    # S4: Write claim assertion.
    claim_assertion = Assertion(
        sid=sid,
        owner=hostname,
        asserted_at=datetime.now(UTC),
        action="claim",
        cwd_normalized=cwd_normalized,
        previous_owner=current_owner,
    )
    write_local_assertion(state_root, hostname, claim_assertion)
    logger.info("claim: wrote claim assertion for sid={} previous_owner={}", sid, current_owner)

    # S5: --here rewrite.
    if here and jsonl_path is not None:
        target_cwd = Path.cwd()
        target_encoded = encode_cwd(target_cwd)
        target_dir = home / ".claude" / "projects" / target_encoded
        target_path = target_dir / f"{sid}.jsonl"

        if jsonl_path != target_path:
            target_dir.mkdir(parents=True, exist_ok=True)
            # Move the JSONL to the new location.
            content = jsonl_path.read_bytes()
            target_path.write_bytes(content)
            jsonl_path.unlink()
            jsonl_path = target_path

            # Update assertion with new cwd.
            new_cwd_normalized = normalize_cwd(target_cwd, home)
            updated_assertion = Assertion(
                sid=sid,
                owner=hostname,
                asserted_at=claim_assertion.asserted_at,
                action="claim",
                cwd_normalized=new_cwd_normalized,
                previous_owner=current_owner,
            )
            write_local_assertion(state_root, hostname, updated_assertion)

    # S6: Flatten + snapshot.
    per_host_updated = read_all_assertions(state_root)
    merged_updated = merge_assertions(per_host_updated)
    flatten_local(state_root, hostname, merged_updated)

    if jsonl_path is not None and jsonl_path.exists():
        line_count = _count_lines(jsonl_path)
        write_snapshot(state_root, hostname, sid, line_count)

    return 0


def _fetch_remote_jsonl_by_sid(
    ssh_alias: str, sid: str, cwd_normalized: str, home: Path
) -> bytes | None:
    """Try to fetch JSONL from remote by constructing the path."""
    # Construct the remote relative path.
    if cwd_normalized.startswith("~/"):
        cwd_path = home / cwd_normalized[2:]
    else:
        cwd_path = Path(cwd_normalized)
    encoded = encode_cwd(cwd_path)
    remote_path = f".claude/projects/{encoded}/{sid}.jsonl"
    return _remote_fetch_jsonl(ssh_alias, remote_path)
