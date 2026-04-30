"""Per-host session ownership assertions: read, write, merge, flatten.

Phase 4 deliverable. This stub satisfies Phase 5's import contract.
The real implementation (Phase 4) will replace this at checkpoint merge.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Assertion:
    """A single ownership assertion for one session on one host."""

    sid: str
    owner: str
    asserted_at: datetime
    action: Literal["create", "claim", "release"]
    cwd_normalized: str
    previous_owner: str | None


def _assertion_to_dict(a: Assertion) -> dict:
    """Serialize an Assertion to a JSON-compatible dict."""
    return {
        "owner": a.owner,
        "asserted_at": a.asserted_at.isoformat(),
        "action": a.action,
        "cwd_normalized": a.cwd_normalized,
        "previous_owner": a.previous_owner,
    }


def _read_ownership_json(path: Path) -> dict:
    """Read ownership.json; return {} if file missing."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def read_local_assertions(state_root: Path, hostname: str) -> dict[str, Assertion]:
    """Read all assertions for hostname from <state_root>/<hostname>/ownership.json."""
    path = state_root / hostname / "ownership.json"
    raw = _read_ownership_json(path)
    result: dict[str, Assertion] = {}
    for sid, entry in raw.items():
        result[sid] = Assertion(
            sid=sid,
            owner=entry["owner"],
            asserted_at=datetime.fromisoformat(entry["asserted_at"]),
            action=entry["action"],
            cwd_normalized=entry["cwd_normalized"],
            previous_owner=entry.get("previous_owner"),
        )
    return result


def write_local_assertions(
    state_root: Path, hostname: str, assertions: dict[str, Assertion]
) -> None:
    """Atomically write all assertions for hostname to <state_root>/<hostname>/ownership.json."""
    host_dir = state_root / hostname
    host_dir.mkdir(parents=True, exist_ok=True)
    path = host_dir / "ownership.json"
    data = {sid: _assertion_to_dict(a) for sid, a in assertions.items()}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def write_local_assertion(state_root: Path, hostname: str, assertion: Assertion) -> None:
    """Insert or update a single assertion atomically in <state_root>/<hostname>/ownership.json."""
    existing = read_local_assertions(state_root, hostname)
    existing[assertion.sid] = assertion
    write_local_assertions(state_root, hostname, existing)


def merge_assertions(
    per_host: dict[str, dict[str, Assertion]],
) -> dict[str, Assertion]:
    """Merge per-host assertion dicts; most-recent asserted_at wins per sid."""
    merged: dict[str, Assertion] = {}
    for _host, assertions in per_host.items():
        for sid, a in assertions.items():
            if sid not in merged or a.asserted_at > merged[sid].asserted_at:
                merged[sid] = a
    return merged


def flatten_local(
    state_root: Path, hostname: str, merged: dict[str, Assertion]
) -> None:
    """Rewrite our own ownership.json to keep only entries we currently own."""
    ours = {sid: a for sid, a in merged.items() if a.owner == hostname}
    write_local_assertions(state_root, hostname, ours)
