"""Test helper: construct synthetic Assertion objects and seed ownership.json files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from croam.ownership import Assertion


def build_assertion(
    sid: str,
    owner: str,
    asserted_at: datetime,
    *,
    action: str = "create",
    cwd_normalized: str = "~/x",
    previous_owner: str | None = None,
) -> Assertion:
    """Construct an Assertion with sensible defaults for tests."""
    return Assertion(
        sid=sid,
        owner=owner,
        asserted_at=asserted_at,
        action=action,  # type: ignore[arg-type]
        cwd_normalized=cwd_normalized,
        previous_owner=previous_owner,
    )


def write_assertions_file(
    state_root: Path,
    hostname: str,
    assertions: dict[str, Assertion],
) -> Path:
    """Write a synthetic ownership.json directly (without atomic semantics).

    Used by tests to seed peer states. Bypasses write_local_assertions so
    tests can deliberately craft malformed payloads when needed.
    """
    d = state_root / hostname
    d.mkdir(parents=True, exist_ok=True)
    path = d / "ownership.json"
    payload = {
        sid: {
            "owner": a.owner,
            "asserted_at": a.asserted_at.isoformat(),
            "action": a.action,
            "cwd_normalized": a.cwd_normalized,
            "previous_owner": a.previous_owner,
        }
        for sid, a in assertions.items()
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
