"""Per-host ownership assertion read/write/merge/flatten and lineage tracking.

On-disk format: <state_root>/<hostname>/ownership.json and lineage.json.
All writes use os.replace atomic rename with fsync. All datetimes are UTC-aware.

Concurrent writes: two writers racing on the same file; the last os.replace wins.
This is intentional -- the most-recent assertion wins semantics means the last
writer's data prevails. The atomic rename prevents partial reads.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from loguru import logger

from croam.errors import OwnershipConflict

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_iso_utc(s: str) -> datetime:
    """Parse ISO8601 datetime. Accepts 'Z' suffix as UTC. Rejects naive."""
    # Python 3.11+ handles 'Z' natively, but be defensive:
    normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as e:
        raise OwnershipConflict(f"Cannot parse asserted_at={s!r} as ISO8601: {e}") from e
    if dt.tzinfo is None:
        raise OwnershipConflict(f"asserted_at={s!r} is naive (no timezone offset)")
    # Normalize to UTC for downstream comparison; preserves the instant.
    return dt.astimezone(UTC)


def ensure_projects_symlink(state_root: Path, hostname: str, home: Path) -> None:
    """Ensure ~/.claude/projects is a symlink into state_root/<hostname>/projects.

    On first run, moves existing contents into the synced directory and
    replaces the original with a symlink. Syncthing then replicates the
    real files so peers can read transcripts offline.

    Layout after migration:
        state_root/<hostname>/projects/   (real dir, inside ~/Sync)
        ~/.claude/projects -> state_root/<hostname>/projects/
    """
    real_dir = state_root / hostname / "projects"
    claude_dir = home / ".claude" / "projects"

    # Already correct.
    if claude_dir.is_symlink() and claude_dir.resolve() == real_dir.resolve():
        return

    real_dir.mkdir(parents=True, exist_ok=True)

    if claude_dir.is_symlink():
        # Symlink pointing elsewhere; fix it.
        claude_dir.unlink()
    elif claude_dir.is_dir():
        # First migration: move contents into synced dir, then replace with symlink.
        import shutil

        for child in claude_dir.iterdir():
            dest = real_dir / child.name
            if dest.exists():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            else:
                shutil.move(str(child), str(dest))
        claude_dir.rmdir()
        logger.info("ensure_projects_symlink: migrated {} -> {}", claude_dir, real_dir)

    # ~/.claude/ must exist for the symlink.
    claude_dir.parent.mkdir(parents=True, exist_ok=True)
    claude_dir.symlink_to(real_dir)
    logger.info("ensure_projects_symlink: {} -> {}", claude_dir, real_dir)


def _atomic_write_json(path: Path, payload: dict) -> None:  # type: ignore[type-arg]
    """Write payload to path atomically: tempfile -> fsync -> os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = secrets.token_hex(4)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{suffix}"
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # On any failure, remove the tempfile. Original `path` is untouched.
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


def _dict_to_assertions(hostname: str, payload: object) -> dict[str, Assertion]:
    """Validate a parsed JSON payload and return a dict of Assertions.

    Raises OwnershipConflict for any schema violation, missing field,
    naive datetime, or invalid action value.
    """
    if not isinstance(payload, dict):
        raise OwnershipConflict(
            f"Expected top-level object for hostname={hostname!r}, got {type(payload).__name__}"
        )
    result: dict[str, Assertion] = {}
    for sid, entry in payload.items():
        if not isinstance(entry, dict):
            raise OwnershipConflict(
                f"Entry for sid={sid!r} in hostname={hostname!r} is not an object"
            )
        # Validate required keys.
        for key in ("owner", "asserted_at", "action", "cwd_normalized"):
            if key not in entry:
                raise OwnershipConflict(
                    f"Entry for sid={sid!r} in hostname={hostname!r} missing required field {key!r}"
                )
        owner = entry["owner"]
        if not isinstance(owner, str):
            raise OwnershipConflict(
                f"Entry for sid={sid!r} in hostname={hostname!r}: "
                f"owner must be str, got {type(owner).__name__}"
            )
        cwd_normalized = entry["cwd_normalized"]
        if not isinstance(cwd_normalized, str):
            raise OwnershipConflict(
                f"Entry for sid={sid!r} in hostname={hostname!r}: "
                f"cwd_normalized must be str, got {type(cwd_normalized).__name__}"
            )
        asserted_at = _parse_iso_utc(entry["asserted_at"])
        action = entry["action"]
        if action not in ("create", "claim", "release"):
            raise OwnershipConflict(
                f"Entry for sid={sid!r} in hostname={hostname!r}: "
                f"action={action!r} is not one of create/claim/release"
            )
        previous_owner = entry.get("previous_owner")
        # Assertion.__post_init__ enforces the claim/previous_owner invariant.
        result[sid] = Assertion(
            sid=sid,
            owner=owner,
            asserted_at=asserted_at,
            action=action,  # type: ignore[arg-type]
            cwd_normalized=cwd_normalized,
            previous_owner=previous_owner,
        )
    return result


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Assertion:
    """A single ownership assertion for a session id (sid)."""

    sid: str
    owner: str
    asserted_at: datetime  # MUST be tz-aware; constructor enforces this
    action: Literal["create", "claim", "release"]
    cwd_normalized: str
    previous_owner: str | None = None

    def __post_init__(self) -> None:
        if self.asserted_at.tzinfo is None:
            raise OwnershipConflict(
                f"Assertion.asserted_at must be tz-aware, got naive datetime for sid={self.sid!r}"
            )
        if self.action == "claim" and self.previous_owner is None:
            raise OwnershipConflict(
                f"Assertion with action='claim' must have previous_owner "
                f"(sid={self.sid!r}, owner={self.owner!r})"
            )
        if self.action != "claim" and self.previous_owner is not None:
            raise OwnershipConflict(
                f"Assertion with action={self.action!r} must NOT have "
                f"previous_owner (sid={self.sid!r})"
            )


@dataclass(frozen=True)
class LineageEntry:
    """Tracks fork relationships between sessions."""

    fork_sid: str
    parent_sid: str
    fork_n: int


# ---------------------------------------------------------------------------
# Read functions
# ---------------------------------------------------------------------------


def read_local_assertions(state_root: Path, hostname: str) -> dict[str, Assertion]:
    """Read <state_root>/<hostname>/ownership.json. Returns {} if absent.

    Raises OwnershipConflict if file is present but malformed (corrupt JSON,
    missing required fields, naive datetime, invalid action enum).
    """
    path = state_root / hostname / "ownership.json"
    if not path.exists():
        return {}
    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise OwnershipConflict(f"Malformed JSON in {path}: {e}") from e
    result = _dict_to_assertions(hostname, payload)
    logger.debug("ownership.read_local_assertions: hostname={} count={}", hostname, len(result))
    return result


def read_all_assertions(
    state_root: Path,
    peer_states: dict[str, dict] | None = None,  # type: ignore[type-arg]
) -> dict[str, dict[str, Assertion]]:
    """Read all hosts' ownership.json under state_root.

    If peer_states is provided (from Phase 8 ssh-strict fanout), it overrides
    the on-disk read for those peers. Schema of peer_states[hostname] matches
    the JSON of ownership.json.
    """
    result: dict[str, dict[str, Assertion]] = {}
    if state_root.exists():
        for child in state_root.iterdir():
            if not child.is_dir():
                continue
            ownership_file = child / "ownership.json"
            if not ownership_file.exists():
                continue
            try:
                assertions = read_local_assertions(state_root, child.name)
                result[child.name] = assertions
            except OwnershipConflict as e:
                logger.warning(
                    "ownership.read_all_assertions: skipping corrupt peer hostname={} error={}",
                    child.name,
                    str(e),
                )
    if peer_states is not None:
        for hostname, dict_payload in peer_states.items():
            try:
                result[hostname] = _dict_to_assertions(hostname, dict_payload)
            except OwnershipConflict as e:
                logger.warning(
                    "ownership.read_all_assertions: skipping invalid peer_states "
                    "hostname={} error={}",
                    hostname,
                    str(e),
                )
    return result


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_assertions(
    per_host: dict[str, dict[str, Assertion]],
) -> dict[str, Assertion]:
    """Most-recent-asserted_at wins per sid. Tiebreaker: alphabetical-by-owner, smaller wins.

    Rationale for tiebreaker: identical timestamps are extremely rare but possible
    (clock sync to the second, two hosts asserting in the same wall-clock second).
    Alphabetical-by-owner is deterministic across all hosts that run the merge, so all
    hosts converge on the same answer without coordination.
    """
    winners: dict[str, Assertion] = {}
    for _hostname, host_assertions in per_host.items():
        for sid, assertion in host_assertions.items():
            current = winners.get(sid)
            if current is None:
                winners[sid] = assertion
                continue
            if assertion.asserted_at > current.asserted_at:
                winners[sid] = assertion
            elif assertion.asserted_at == current.asserted_at and assertion.owner < current.owner:
                # Deterministic tiebreaker: alphabetical-by-owner, smaller wins.
                winners[sid] = assertion
    return winners


# ---------------------------------------------------------------------------
# Write functions
# ---------------------------------------------------------------------------


def write_local_assertions(
    state_root: Path,
    hostname: str,
    assertions: dict[str, Assertion],
) -> None:
    """Atomic write of <state_root>/<hostname>/ownership.json.

    Uses tempfile + fsync + os.replace. The original file remains intact if
    the process is killed mid-write.
    """
    path = state_root / hostname / "ownership.json"
    payload = {
        sid: {
            "owner": a.owner,
            "asserted_at": a.asserted_at.isoformat(),
            "action": a.action,
            "cwd_normalized": a.cwd_normalized,
            "previous_owner": a.previous_owner,  # may be None -> JSON null
        }
        for sid, a in sorted(assertions.items())
    }
    _atomic_write_json(path, payload)
    logger.debug(
        "ownership.write_local_assertions: hostname={} count={}",
        hostname,
        len(assertions),
    )


def write_local_assertion(state_root: Path, hostname: str, assertion: Assertion) -> None:
    """Insert/update a single assertion in <state_root>/<hostname>/ownership.json."""
    existing = read_local_assertions(state_root, hostname)
    existing = dict(existing)
    existing[assertion.sid] = assertion
    write_local_assertions(state_root, hostname, existing)


# ---------------------------------------------------------------------------
# Flatten and detect outclaim
# ---------------------------------------------------------------------------


def flatten_local(
    state_root: Path,
    hostname: str,
    merged: dict[str, Assertion],
) -> None:
    """Rewrite our own ownership.json keeping only entries we currently own.

    `merged` is the output of merge_assertions across all hosts. After this
    call, our ownership.json contains exactly {sid: assertion for sid in merged
    where merged[sid].owner == hostname AND assertion came from us}.
    """
    local = read_local_assertions(state_root, hostname)
    kept = {
        sid: assertion
        for sid, assertion in local.items()
        if sid in merged and merged[sid].owner == hostname
    }
    write_local_assertions(state_root, hostname, kept)
    if len(kept) < len(local):
        logger.info(
            "ownership.flatten: hostname={} dropped={} kept={}",
            hostname,
            len(local) - len(kept),
            len(kept),
        )
    else:
        logger.debug("ownership.flatten: hostname={} kept={} (no drops)", hostname, len(kept))


def detect_outclaim(
    state_root: Path,
    hostname: str,
    merged: dict[str, Assertion],
) -> list[str]:
    """Returns sids where local has an assertion but merged[sid].owner != hostname."""
    local = read_local_assertions(state_root, hostname)
    return sorted([sid for sid in local if sid in merged and merged[sid].owner != hostname])


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------


def read_lineage(state_root: Path, hostname: str) -> dict[str, LineageEntry]:
    """Read <state_root>/<hostname>/lineage.json. Returns {} if absent.

    Raises OwnershipConflict on malformed JSON.
    """
    path = state_root / hostname / "lineage.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise OwnershipConflict(f"Malformed JSON in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise OwnershipConflict(f"Expected object in {path}, got {type(raw).__name__}")
    result: dict[str, LineageEntry] = {}
    for fork_sid, entry in raw.items():
        if not isinstance(entry, dict):
            raise OwnershipConflict(f"Lineage entry for {fork_sid} is not an object")
        try:
            parent_sid = entry["parent_sid"]
            fork_n = entry["fork_n"]
        except KeyError as e:
            raise OwnershipConflict(f"Lineage entry {fork_sid} missing required field {e}") from e
        if not isinstance(fork_n, int):
            raise OwnershipConflict(
                f"Lineage entry {fork_sid}.fork_n must be int, got {type(fork_n).__name__}"
            )
        result[fork_sid] = LineageEntry(
            fork_sid=fork_sid,
            parent_sid=parent_sid,
            fork_n=fork_n,
        )
    return result


def write_lineage(state_root: Path, hostname: str, lineage: dict[str, LineageEntry]) -> None:
    """Atomic write of <state_root>/<hostname>/lineage.json."""
    path = state_root / hostname / "lineage.json"
    payload = {
        fork_sid: {"parent_sid": entry.parent_sid, "fork_n": entry.fork_n}
        for fork_sid, entry in sorted(lineage.items())
    }
    _atomic_write_json(path, payload)


def add_lineage(state_root: Path, hostname: str, fork_sid: str, parent_sid: str) -> int:
    """Append a lineage entry; compute fork_n = max(fork_n for parent_sid) + 1.

    First fork of a parent yields fork_n=1.
    """
    lineage = read_lineage(state_root, hostname)
    existing_n = [e.fork_n for e in lineage.values() if e.parent_sid == parent_sid]
    fork_n = max(existing_n) + 1 if existing_n else 1
    lineage = dict(lineage)
    lineage[fork_sid] = LineageEntry(
        fork_sid=fork_sid,
        parent_sid=parent_sid,
        fork_n=fork_n,
    )
    write_lineage(state_root, hostname, lineage)
    return fork_n
