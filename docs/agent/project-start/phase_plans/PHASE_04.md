# Phase 4: Ownership state

**Feature**: project-start
**Estimated Context Budget**: ~70k tokens

**Difficulty**: medium
**Visual**: no
**Functional**: yes

**Execution Mode**: parallel
**Batch**: 3 (parallel with Phase 3, Phase 5; depends on Phase 1, 2)

---

## Objective

Ship `src/croam/ownership.py`: per-host `ownership.json` read/write/merge/flatten with most-recent-`asserted_at`-wins semantics, plus `lineage.json` tracking. All writes use `os.replace` atomic rename with fsync. All datetimes are UTC-aware. The on-disk format defined here IS the inter-host wire contract (Surface 4 in `FUNCTIONAL_QA_STRATEGY.md`); peer hosts running croam MUST be able to parse what we write, so the schema stays minimal and stable.

This phase does NOT manage transcript-line snapshots. Phase 8's reconciliation (fork-or-discard prompt) needs "JSONL line count at time of assertion" but storing that in `Assertion` would expand the wire format and force version coordination across hosts. Decision: snapshots live in a separate `<state_root>/<HOSTNAME>/snapshots.json` file owned by Phase 8. Phase 4 keeps `Assertion` minimal.

---

## Deliverables

1. **`src/croam/ownership.py`** -- module containing:
   - `Assertion` frozen dataclass
   - `LineageEntry` frozen dataclass
   - `read_local_assertions(state_root, hostname) -> dict[str, Assertion]`
   - `read_all_assertions(state_root, peer_states=None) -> dict[str, dict[str, Assertion]]`
   - `merge_assertions(per_host) -> dict[str, Assertion]`
   - `write_local_assertions(state_root, hostname, assertions) -> None` (atomic)
   - `flatten_local(state_root, hostname, merged) -> None`
   - `detect_outclaim(state_root, hostname, merged) -> list[str]`
   - `read_lineage(state_root, hostname) -> dict[str, LineageEntry]`
   - `write_lineage(state_root, hostname, lineage) -> None` (atomic)
   - `add_lineage(state_root, hostname, fork_sid, parent_sid) -> int`
2. **`tests/_helpers/synth_assertions.py`** -- test helper (declared in `FUNCTIONAL_QA_STRATEGY.md` as a Phase 4 deliverable used by Phase 7, 8, 9, 10):
   - `build_assertion(sid, owner, asserted_at, action="create", cwd_normalized="~/x", previous_owner=None) -> Assertion`
   - `write_assertions_file(state_root, hostname, assertions) -> Path` -- writes the synthetic ownership.json directly with the canonical JSON shape (used by tests to seed peer states without going through `write_local_assertions`).
3. **`tests/test_ownership.py`** -- 11 unit tests covering read/write/merge/flatten/detect_outclaim/lineage plus atomic-write fault injection.

**Files this phase MUST NOT touch** (owned by other phases):
- `src/croam/cli.py`, `src/croam/sessions.py`, `src/croam/hosts.py`, `src/croam/tmux.py`, `src/croam/shim.py`, `src/croam/picker.py`, `src/croam/commands/*`, `src/croam/sync.py`, `src/croam/doctor.py`
- `src/croam/log.py`, `src/croam/errors.py`, `src/croam/proc.py`, `src/croam/config.py`, `src/croam/paths.py` (Phases 1-2)
- `tests/conftest.py` (Phase 1)
- `pyproject.toml` (Phase 1; if a missing dep needs to be added, document it in your phase summary -- do NOT edit pyproject.toml here)

---

## Detailed Requirements

### Module header

`src/croam/ownership.py` starts with:

```python
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from loguru import logger

from croam.errors import OwnershipConflict
```

If `OwnershipConflict` does not exist in `src/croam/errors.py` after Phase 1, raise `ConfigError` instead and note the missing class in your phase summary. Do NOT add new exception classes from this phase.

### Dataclasses

```python
@dataclass(frozen=True)
class Assertion:
    sid: str
    owner: str
    asserted_at: datetime  # MUST be tz-aware; constructor enforces this
    action: Literal["create", "claim", "release"]
    cwd_normalized: str
    previous_owner: str | None = None

    def __post_init__(self) -> None:
        if self.asserted_at.tzinfo is None:
            raise OwnershipConflict(
                f"Assertion.asserted_at must be tz-aware, got naive datetime "
                f"for sid={self.sid!r}"
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
    fork_sid: str
    parent_sid: str
    fork_n: int
```

`Assertion.__post_init__` is the only invariant enforcement. The validation runs both for in-memory construction (tests) and for assertions reconstructed from JSON.

### JSON schema (the wire format)

`<state_root>/<hostname>/ownership.json`:

```json
{
  "<sid>": {
    "owner": "<hostname>",
    "asserted_at": "2026-04-30T10:00:00+00:00",
    "action": "create" | "claim" | "release",
    "cwd_normalized": "~/Programs/foo",
    "previous_owner": "<hostname>" | null
  }
}
```

Top-level object is a dict keyed by sid. The `previous_owner` key is ALWAYS present in the on-disk JSON (set to `null` for non-claim entries) for forward-compatibility. `asserted_at` is ISO8601 with explicit UTC offset (`+00:00`, not `Z` -- `datetime.isoformat()` produces `+00:00`; tolerate `Z` on read).

`<state_root>/<hostname>/lineage.json`:

```json
{
  "<fork_sid>": {
    "parent_sid": "<sid>",
    "fork_n": 1
  }
}
```

### `read_local_assertions(state_root, hostname)`

```python
def read_local_assertions(
    state_root: Path, hostname: str
) -> dict[str, Assertion]:
    """Read <state_root>/<hostname>/ownership.json. Returns {} if absent.

    Raises OwnershipConflict if file is present but malformed (corrupt JSON,
    missing required fields, naive datetime, invalid action enum).
    """
```

Behavior:
1. `path = state_root / hostname / "ownership.json"`
2. If `not path.exists()`: return `{}`
3. Read with `path.read_text(encoding="utf-8")`
4. Parse with `json.loads`. On `json.JSONDecodeError`, raise `OwnershipConflict(f"Malformed JSON in {path}: {e}")` chained from the original.
5. Validate top-level is a dict; else `OwnershipConflict("Expected top-level object in {path}, got {type}")`.
6. For each `(sid, entry)` in the dict:
   - Validate `entry` is a dict.
   - Required keys: `owner` (str), `asserted_at` (str), `action` (str), `cwd_normalized` (str). `previous_owner` may be missing or null.
   - Parse `asserted_at` via `_parse_iso_utc(entry["asserted_at"])` (helper below). If naive, raise `OwnershipConflict`.
   - Validate `action in {"create", "claim", "release"}`.
   - Construct `Assertion(sid=sid, owner=..., asserted_at=..., action=..., cwd_normalized=..., previous_owner=entry.get("previous_owner"))`. The dataclass `__post_init__` enforces the claim/previous_owner invariant.
7. Return `{sid: Assertion}`.

Helper:

```python
def _parse_iso_utc(s: str) -> datetime:
    """Parse ISO8601 datetime. Accepts 'Z' suffix as UTC. Rejects naive."""
    # Python 3.11+ handles 'Z' natively, but be defensive:
    normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as e:
        raise OwnershipConflict(
            f"Cannot parse asserted_at={s!r} as ISO8601: {e}"
        ) from e
    if dt.tzinfo is None:
        raise OwnershipConflict(
            f"asserted_at={s!r} is naive (no timezone offset)"
        )
    # Normalize to UTC for downstream comparison; preserves the instant.
    return dt.astimezone(timezone.utc)
```

Logging: `logger.debug("ownership.read_local_assertions: hostname={} count={}", hostname, len(result))` after successful read.

### `read_all_assertions(state_root, peer_states=None)`

```python
def read_all_assertions(
    state_root: Path,
    peer_states: dict[str, dict] | None = None,
) -> dict[str, dict[str, Assertion]]:
    """Read all hosts' ownership.json under state_root.

    If peer_states is provided (from Phase 8 ssh-strict fanout), it overrides
    the on-disk read for those peers. Schema of peer_states[hostname] matches
    the JSON of ownership.json.
    """
```

Behavior:
1. Result: `dict[str, dict[str, Assertion]]` keyed by hostname.
2. If `state_root.exists()`: iterate `state_root.iterdir()`. For each child that is a dir AND has an `ownership.json` file, call `read_local_assertions(state_root, child.name)`. Skip non-directories silently. Log `logger.warning(...)` for any subdir whose ownership.json fails to parse, but do NOT propagate -- continue with the remaining hosts. (Rationale: a corrupt peer file should not block our own croam invocation.)
3. If `peer_states` is not None: for each `(hostname, dict_payload)` in peer_states, parse the dict_payload through the same validation path (extract a helper `_dict_to_assertions(hostname: str, payload: dict) -> dict[str, Assertion]` from `read_local_assertions` so both call sites share validation). The peer_states entry OVERRIDES any on-disk entry for that hostname (live SSH wins over potentially-stale syncthing mirror).
4. Return the merged map.

### `merge_assertions(per_host)`

```python
def merge_assertions(
    per_host: dict[str, dict[str, Assertion]],
) -> dict[str, Assertion]:
    """Most-recent-asserted_at wins per sid. Tiebreaker: alphabetical-by-owner."""
```

Algorithm:
1. Collect all `(sid, Assertion)` pairs from all hosts.
2. For each sid, pick the assertion with the latest `asserted_at`. Tiebreaker on identical `asserted_at`: pick the one whose `owner` sorts FIRST alphabetically (deterministic; documented). Document this choice in the function docstring.
3. Empty input returns `{}`.

Rationale for tiebreaker: identical timestamps are extremely rare but possible (clock sync to the second, two hosts asserting in the same wall-clock second). Picking alphabetical-by-owner is deterministic across all hosts that run the merge, so all hosts converge on the same answer without coordination.

```python
def merge_assertions(per_host):
    winners: dict[str, Assertion] = {}
    for hostname, host_assertions in per_host.items():
        for sid, assertion in host_assertions.items():
            current = winners.get(sid)
            if current is None:
                winners[sid] = assertion
                continue
            if assertion.asserted_at > current.asserted_at:
                winners[sid] = assertion
            elif assertion.asserted_at == current.asserted_at:
                # Deterministic tiebreaker: alphabetical-by-owner, smaller wins.
                if assertion.owner < current.owner:
                    winners[sid] = assertion
    return winners
```

### `write_local_assertions(state_root, hostname, assertions)` -- atomic

```python
def write_local_assertions(
    state_root: Path,
    hostname: str,
    assertions: dict[str, Assertion],
) -> None:
    """Atomic write of <state_root>/<hostname>/ownership.json.

    Uses tempfile + fsync + os.replace. The original file remains intact if
    the process is killed mid-write.
    """
```

Recipe (DO NOT deviate -- the atomicity invariant is the whole point of this module):

```python
def _atomic_write_json(path: Path, payload: dict) -> None:
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
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
```

Then:

```python
def write_local_assertions(state_root, hostname, assertions):
    path = state_root / hostname / "ownership.json"
    payload = {
        sid: {
            "owner": a.owner,
            "asserted_at": a.asserted_at.isoformat(),
            "action": a.action,
            "cwd_normalized": a.cwd_normalized,
            "previous_owner": a.previous_owner,  # may be None
        }
        for sid, a in sorted(assertions.items())
    }
    _atomic_write_json(path, payload)
    logger.debug(
        "ownership.write_local_assertions: hostname={} count={}",
        hostname, len(assertions),
    )
```

Notes:
- `sort_keys=True` and `sorted(assertions.items())` produce a stable byte-for-byte output for identical input. This matters for syncthing: identical content -> no replication churn.
- `indent=2` matches the design spec's example layout.
- `previous_owner=None` is preserved as JSON `null`. `json.dumps` handles this natively.
- The tempfile name starts with `.` (hidden) and includes pid + 4-byte hex suffix to prevent collisions across parallel `croam` invocations on the same host.

### `flatten_local(state_root, hostname, merged)`

```python
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
```

Behavior:
1. `local = read_local_assertions(state_root, hostname)`
2. `kept = {sid: assertion for sid, assertion in local.items() if sid in merged and merged[sid].owner == hostname}`
3. `write_local_assertions(state_root, hostname, kept)`
4. Log at INFO level if `len(kept) < len(local)`: `logger.info("ownership.flatten: hostname={} dropped={} kept={}", hostname, len(local) - len(kept), len(kept))`. Otherwise DEBUG.

Edge case: if `local` is empty (no file), this is a no-op (`write_local_assertions` writes `{}` to disk, creating the file, but with no entries). Acceptable.

Edge case: if a sid is in `local` but NOT in `merged`, drop it (defensive: should not happen, but if `merged` was computed from a stricter peer view, the local entry is stale).

### `detect_outclaim(state_root, hostname, merged)`

```python
def detect_outclaim(
    state_root: Path,
    hostname: str,
    merged: dict[str, Assertion],
) -> list[str]:
    """Returns sids where local has an assertion but `merged[sid].owner != hostname`."""
```

Behavior:
1. `local = read_local_assertions(state_root, hostname)`
2. Return `sorted([sid for sid in local if sid in merged and merged[sid].owner != hostname])`.

Sorted output is for deterministic test assertions. Phase 8 will iterate this list to drive the fork-or-discard prompt.

### Lineage functions

```python
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
            raise OwnershipConflict(
                f"Lineage entry {fork_sid} missing required field {e}"
            ) from e
        if not isinstance(fork_n, int):
            raise OwnershipConflict(
                f"Lineage entry {fork_sid}.fork_n must be int, got {type(fork_n).__name__}"
            )
        result[fork_sid] = LineageEntry(
            fork_sid=fork_sid, parent_sid=parent_sid, fork_n=fork_n,
        )
    return result


def write_lineage(
    state_root: Path, hostname: str, lineage: dict[str, LineageEntry]
) -> None:
    """Atomic write of <state_root>/<hostname>/lineage.json."""
    path = state_root / hostname / "lineage.json"
    payload = {
        fork_sid: {"parent_sid": entry.parent_sid, "fork_n": entry.fork_n}
        for fork_sid, entry in sorted(lineage.items())
    }
    _atomic_write_json(path, payload)


def add_lineage(
    state_root: Path, hostname: str, fork_sid: str, parent_sid: str
) -> int:
    """Append a lineage entry; compute fork_n = max(fork_n for parent_sid) + 1.

    First fork of a parent yields fork_n=1.
    """
    lineage = read_lineage(state_root, hostname)
    existing_n = [
        e.fork_n for e in lineage.values() if e.parent_sid == parent_sid
    ]
    fork_n = max(existing_n) + 1 if existing_n else 1
    lineage[fork_sid] = LineageEntry(
        fork_sid=fork_sid, parent_sid=parent_sid, fork_n=fork_n,
    )
    write_lineage(state_root, hostname, lineage)
    return fork_n
```

### Test helper: `tests/_helpers/synth_assertions.py`

```python
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
        sid=sid, owner=owner, asserted_at=asserted_at,
        action=action, cwd_normalized=cwd_normalized,
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
```

### Step-by-step implementation order

1. Create `src/croam/ownership.py` with imports + `_parse_iso_utc` helper + `_atomic_write_json` helper.
2. Add `Assertion` and `LineageEntry` dataclasses with `__post_init__` validation on `Assertion`.
3. Implement `_dict_to_assertions(hostname, payload)` private helper that takes a parsed JSON dict and returns `dict[str, Assertion]` (extracting the validation loop so it can be reused).
4. Implement `read_local_assertions` using `_dict_to_assertions`.
5. Implement `read_all_assertions` (iterate state_root subdirs + apply peer_states overrides).
6. Implement `merge_assertions` with the alphabetical-owner tiebreaker.
7. Implement `write_local_assertions` (uses `_atomic_write_json`).
8. Implement `flatten_local`.
9. Implement `detect_outclaim`.
10. Implement `read_lineage`, `write_lineage`, `add_lineage`.
11. Create `tests/_helpers/__init__.py` (empty) if it does not yet exist, and `tests/_helpers/synth_assertions.py`.
12. Write `tests/test_ownership.py` covering the 11 cases below.
13. Run `uv run pytest tests/test_ownership.py -v` -- all green.
14. Run `uv run pyright src/croam/ownership.py` -- no errors.
15. Run `uv run ruff check src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py` -- no errors.
16. Run `uv run pytest tests/test_ownership.py --cov=src/croam/ownership --cov-report=term-missing` and verify >= 95%.

---

## Edge cases (explicit)

1. **Naive datetime in JSON**: `asserted_at = "2026-04-30T10:00:00"` (no offset). `_parse_iso_utc` raises `OwnershipConflict`. Test: `test_read_naive_datetime_rejected`.
2. **`Z` suffix**: `asserted_at = "2026-04-30T10:00:00Z"`. Accept; coerce to `+00:00`. Test: `test_read_z_suffix_accepted`.
3. **Mixed offsets**: one assertion with `+00:00`, another with `-05:00`. Merge correctly orders by absolute instant. Test: `test_merge_timezone_aware`.
4. **Identical `asserted_at`**: tiebreaker is alphabetical-by-owner, smaller wins. Test: `test_merge_tiebreaker_alphabetical`.
5. **Empty state_root**: `read_all_assertions(empty_path)` returns `{}` not error. Test: covered in `test_read_empty`.
6. **Subdir without ownership.json**: silently skipped. Test in `test_read_all_skips_dirs_without_ownership`.
7. **Corrupt peer ownership.json**: logged at WARNING, skipped, does not block local read. Test: `test_read_all_continues_past_corrupt_peer`.
8. **Crash mid-write**: original file intact. Verified by injecting an exception inside `_atomic_write_json` AFTER the tempfile is written but BEFORE `os.replace`. Test: `test_write_atomic_crash_preserves_original`.
9. **Concurrent writes**: two writers race; the last `os.replace` wins. NOT explicitly tested (race conditions are flaky); documented in module docstring.
10. **`action="claim"` without `previous_owner`**: dataclass `__post_init__` raises `OwnershipConflict`. Test: `test_claim_without_previous_owner_rejected`.
11. **`action="create"` WITH `previous_owner`**: dataclass raises. Test: `test_create_with_previous_owner_rejected`.
12. **Malformed JSON**: `OwnershipConflict` chained from `JSONDecodeError`. Test: `test_read_malformed`.
13. **Top-level not an object**: `OwnershipConflict`. Test: covered in `test_read_malformed` (parametrize with `"[]"`, `'"string"'`, `"42"`).
14. **`previous_owner` missing key vs explicit null**: both treated as `None`. Test: `test_read_previous_owner_missing_or_null`.
15. **Outclaimed sid not in merged**: `detect_outclaim` ignores it (only reports sids present in both local and merged). Documented above.
16. **Lineage `add_lineage` for new parent**: `fork_n = 1`. For 2nd fork: `fork_n = 2`. Test: `test_lineage_increments`.
17. **Atomic write produces stable bytes for identical input**: two consecutive `write_local_assertions` calls with the same `assertions` dict produce byte-identical files. Test: `test_write_stable_bytes`.

---

## Test list (`tests/test_ownership.py`)

Each test takes the `state_root` fixture from `tests/conftest.py` (Phase 1 deliverable). `state_root` is `tmp_path / "state"`, pre-created.

1. **`test_read_empty(state_root)`** -- `read_local_assertions(state_root, "stormtree")` returns `{}` (no file).
2. **`test_read_one(state_root)`** -- write a synthetic ownership.json with one create-action entry; read; assert dataclass field-by-field.
3. **`test_read_z_suffix_accepted(state_root)`** -- write with `"asserted_at": "2026-04-30T10:00:00Z"`; read; assert `tzinfo == timezone.utc`.
4. **`test_read_naive_datetime_rejected(state_root)`** -- write with `"asserted_at": "2026-04-30T10:00:00"` (no offset); `read_local_assertions` raises `OwnershipConflict`.
5. **`test_read_malformed(state_root)`** -- `pytest.parametrize` over: `"{not json"`, `'"a string"'`, `"[]"`, `"42"`. Each raises `OwnershipConflict`.
6. **`test_read_previous_owner_missing_or_null(state_root)`** -- write entries with action=create where one omits `previous_owner` and one has it explicitly `null`. Both parse with `previous_owner=None`.
7. **`test_claim_without_previous_owner_rejected()`** -- pure dataclass test: `Assertion(sid="x", owner="a", asserted_at=now_utc(), action="claim", cwd_normalized="~/x", previous_owner=None)` raises `OwnershipConflict`.
8. **`test_create_with_previous_owner_rejected()`** -- dataclass: `action="create"` + `previous_owner="b"` raises.
9. **`test_merge_two_hosts_no_overlap(state_root)`** -- hosts A and B own disjoint sids; merge returns union; verify owner field.
10. **`test_merge_overlap_a_wins(state_root)`** -- both A and B claim sid X; A.asserted_at > B.asserted_at; merge picks A.
11. **`test_merge_timezone_aware(state_root)`** -- A asserts at `2026-04-30T10:00:00+00:00`; B asserts at `2026-04-30T04:00:00-05:00` (which is 09:00 UTC). A wins (later UTC). Mixed offsets must NOT change the answer.
12. **`test_merge_tiebreaker_alphabetical(state_root)`** -- A and B identical asserted_at; A < B alphabetically; merge picks A.
13. **`test_write_atomic_crash_preserves_original(state_root, monkeypatch)`** -- pre-write a known-good ownership.json; `monkeypatch.setattr("os.replace", lambda src, dst: (_ for _ in ()).throw(OSError("simulated")))`; call `write_local_assertions` with new content; assert it raises OSError; assert original file content is unchanged via `read_local_assertions`. Then unset the monkeypatch and assert no `.tmp.` files remain in the directory.
14. **`test_write_stable_bytes(state_root)`** -- call `write_local_assertions` twice with the same dict; `path.read_bytes()` must be byte-identical between calls.
15. **`test_flatten_drops_outclaimed(state_root)`** -- A's local file has sids X and Y; merged says A owns X but B owns Y; `flatten_local("A", merged)` rewrites A's file to contain only X.
16. **`test_detect_outclaim(state_root)`** -- A's local has X, Y, Z; merged says A owns X, B owns Y, A owns Z; returns `["Y"]`.
17. **`test_read_all_skips_dirs_without_ownership(state_root)`** -- create `state_root/foo/` (empty dir); `read_all_assertions` returns `{}` without error.
18. **`test_read_all_continues_past_corrupt_peer(state_root, caplog)`** -- create A (valid) and B (corrupt JSON); `read_all_assertions` returns `{"A": ...}` only; assert WARNING log mentions B.
19. **`test_read_all_peer_states_override(state_root)`** -- write A on disk with sid X@10:00; pass `peer_states={"A": {"X": {... asserted_at "11:00" ...}}}`; assert returned assertion uses 11:00 (live SSH wins over disk).
20. **`test_lineage_increments(state_root)`** -- `add_lineage(state_root, "A", "fork1", "parent")` returns 1; second call with `fork2` returns 2; third with `fork3` returns 3. Verify lineage.json on disk has all three with correct `fork_n`.
21. **`test_lineage_independent_parents(state_root)`** -- `add_lineage("A", "f1", "p1")` -> 1; `add_lineage("A", "f2", "p2")` -> 1 (different parent restarts the count).
22. **`test_e2e_outclaim_recovery(state_root)`** -- end-to-end scenario: A asserts sid X at T1; B asserts sid X at T2 > T1; both files on disk; from A's POV: `merge_assertions` says B owns X; `detect_outclaim("A", merged)` returns `["X"]`; `flatten_local("A", merged)` removes X from A's file; subsequent `read_local_assertions("A")` returns empty.

The "11 tests" in the brief is a minimum; the list above is 22 to cover all edge cases. If context runs short, prioritize tests 1, 2, 5, 7, 9, 10, 11, 13, 15, 16, 20, 22.

---

## Helper functions (private)

Inside `src/croam/ownership.py`:

- `_parse_iso_utc(s: str) -> datetime` -- ISO8601 -> UTC-aware datetime; rejects naive.
- `_atomic_write_json(path: Path, payload: dict) -> None` -- the atomic write recipe.
- `_dict_to_assertions(hostname: str, payload: dict) -> dict[str, Assertion]` -- shared validation for read paths.

These are NOT exported via `__all__`. Tests can still reach them via direct import for white-box testing if absolutely necessary, but prefer black-box tests.

---

## Dependencies

**Requires**:
- **Phase 1**: `src/croam/errors.py` provides `OwnershipConflict` (and `CroamError` base). `tests/conftest.py` provides the `state_root` fixture and `home` fixture and the autouse HOME-redirect guard. `loguru` is configured via `src/croam/log.py`.
- **Phase 2**: not strictly required for compilation, but `cwd_normalized` strings should follow the format produced by `paths.normalize_cwd` (home-rooted `~/...` or absolute path string). Phase 4 does NOT validate the format -- treat `cwd_normalized` as opaque string. Phase 8/9 will produce values via Phase 2's helpers.

**Enables**:
- **Phase 5**: `commands/launch.py` calls `write_local_assertions` after a successful tmux launch.
- **Phase 7**: `attach`/`peek`/`ls` call `read_all_assertions` and `merge_assertions` to build the picker view.
- **Phase 8**: `claim` and `fork` use `Assertion`, `write_local_assertions`, `add_lineage`. Phase 8 also adds the separate `snapshots.json` file (NOT in this phase).
- **Phase 9**: `doctor` calls `read_all_assertions` to surface inconsistencies.

---

## Snapshot decision (recorded for Phase 8)

Phase 8's reconciliation needs "JSONL line count at time of assertion" to decide fork-or-discard when this host is outclaimed. Two options were considered:

1. Add `transcript_lines_at_assertion: int | None = None` to `Assertion`.
2. Store snapshots in a separate `<state_root>/<HOSTNAME>/snapshots.json` file owned by Phase 8.

**Decision: Option 2.**

Reasoning:
- `Assertion` IS the inter-host wire format (Surface 4). Peers MUST parse what we write. Adding a field forces a coordinated version bump across all hosts; old peers seeing the new field will still parse it (we tolerate unknown keys when reading -- see `_dict_to_assertions` which only requires the documented set of keys), but old peers writing will not include it, and code that depends on the field has to handle `None` everywhere anyway.
- A snapshot is local-only metadata: it answers "did MY local copy diverge after MY assertion was made," which only the local host can compute and only the local host needs to consult during outclaim recovery. Peer hosts have no use for it.
- Keeping `Assertion` minimal preserves the principle in section 5 of the design spec ("each host writes only entries asserting its own ownership claims") -- the wire format stays purely about ownership.
- Phase 8 owns `snapshots.json` schema. Suggested shape (NOT implemented here, documented for Phase 8): `{"<sid>": {"transcript_lines": int, "captured_at": "<ISO8601 UTC>"}}`.

This decision is binding: do NOT add `transcript_lines_at_assertion` to `Assertion` in this phase.

---

## Completion Criteria

- [ ] `src/croam/ownership.py` exists with all 11 public functions/classes listed under Deliverables.
- [ ] `tests/_helpers/synth_assertions.py` exists with `build_assertion` and `write_assertions_file`.
- [ ] `tests/test_ownership.py` covers the 22 test cases listed above (or at minimum the 12 prioritized cases).
- [ ] `uv run pytest tests/test_ownership.py -v` -- all green.
- [ ] `uv run pyright src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py` -- no errors.
- [ ] `uv run ruff check src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py` -- no errors.
- [ ] `uv run ruff format --check src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py` -- formatted.
- [ ] `uv run pytest tests/test_ownership.py --cov=src/croam/ownership --cov-report=term-missing` -- coverage >= 95% on `src/croam/ownership.py`.
- [ ] Atomic write fault injection test (`test_write_atomic_crash_preserves_original`) is present and passes.
- [ ] No new dependency added to `pyproject.toml`. (If you discover one is needed, document in summary; do NOT edit pyproject.toml.)
- [ ] `Assertion.__post_init__` validates: tz-aware `asserted_at`; `claim` requires `previous_owner`; non-claim forbids `previous_owner`.

---

## Testing Requirements

Test commands (run from `/home/tunc/Sync/Programs/croam`):

```bash
# Style + types
uv run ruff format --check src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py
uv run ruff check src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py
uv run pyright src/croam/ownership.py tests/test_ownership.py tests/_helpers/synth_assertions.py

# Tests with coverage
uv run pytest tests/test_ownership.py -v
uv run pytest tests/test_ownership.py --cov=src/croam/ownership --cov-report=term-missing

# Single high-stakes test (atomic write fault injection)
uv run pytest tests/test_ownership.py::test_write_atomic_crash_preserves_original -v
```

The conftest autouse HOME-redirect guard from Phase 1 is the safety net -- if your test code accidentally calls `Path.home()`, the guard will fail the test rather than touch the user's real `~/.claude`. Do NOT override the guard.

Use the `state_root` fixture (NOT `tmp_path` directly) so future Phase 1 changes to fixture layout propagate cleanly. If the `state_root` fixture is not yet available from Phase 1, add a small fixture in `tests/test_ownership.py` that yields `tmp_path / "state"` after `mkdir(parents=True)` -- and note it in your phase summary so Phase 1 can be retrofitted.

---

## Functional QA

> Surface 4: per-host state files (the inter-host wire format). All checks
> below correspond to FUNCTIONAL_QA_STRATEGY.md "Mechanism for Surface 4: per-host
> state files" -- pure JSON read/write/merge with synthetic state_root.

For each check below, run the command, capture the actual output, and paste it into your phase summary's "Functional QA Results" section with a pass/fail verdict.

- [ ] **(state-file surface, Loop C: Claim ownership)** Construct two synthetic ownership.json files: `state/stormtree/ownership.json` with sid `S1` asserted_at `2026-04-30T10:00:00+00:00` (action=create, owner=stormtree); `state/vicar/ownership.json` with the SAME sid `S1` asserted_at `2026-04-30T11:00:00+00:00` (action=claim, previous_owner=stormtree, owner=vicar). Call `merge_assertions(read_all_assertions(state_root))`. Expected: `merged["S1"].owner == "vicar"`. Capture: `python -c "from croam.ownership import read_all_assertions, merge_assertions; from pathlib import Path; m = merge_assertions(read_all_assertions(Path('state'))); print(m['S1'])"` and paste the output.

- [ ] **(state-file surface, Loop C)** Continuing from the previous setup, call `flatten_local(state_root, "stormtree", merged)`. Expected: `state/stormtree/ownership.json` is now `{}`. Capture: `cat state/stormtree/ownership.json` and paste the empty-object output. Then call `flatten_local(state_root, "vicar", merged)` -- expected: `state/vicar/ownership.json` still contains `S1` (vicar is the winner). Capture: `cat state/vicar/ownership.json`.

- [ ] **(state-file surface, anti-pattern E)** Mixed-timezone test: write A's assertion with `+00:00`, B's assertion with `-05:00`. The B time `2026-04-30T04:00:00-05:00` is 09:00 UTC (earlier than A's 10:00 UTC). Call `merge_assertions`. Expected: A wins. Run the test and verify `merged[sid].owner == "A"`. Paste the test output.

- [ ] **(state-file surface, atomicity)** Atomic write fault injection: pre-write `state/A/ownership.json` with content `{"S1": {...}}` (one assertion). Then monkeypatch `os.replace` to raise `OSError("disk full")`. Call `write_local_assertions(state_root, "A", new_assertions)`. Expected: `OSError` propagates, original file content is unchanged (re-read returns `{"S1": ...}`), no `.tmp.` files remain in `state/A/`. Capture: file content before, exception traceback, file content after, `ls -la state/A/`.

- [ ] **(state-file surface, fresh state)** Empty-directory test: create `state/A/` (empty), no ownership.json. Call `read_local_assertions(state_root, "A")`. Expected: returns `{}` without raising. Capture: REPL session.

- [ ] **(state-file surface, schema validation)** Malformed JSON test: write `state/A/ownership.json` with content `{not json`. Call `read_local_assertions(state_root, "A")`. Expected: raises `OwnershipConflict` whose message names the file path. Capture: traceback.

- [ ] **(state-file surface, lineage)** Three-fork lineage: in fresh state_root, call `add_lineage(state_root, "stormtree", "f1", "parent")`, `add_lineage(state_root, "stormtree", "f2", "parent")`, `add_lineage(state_root, "stormtree", "f3", "parent")`. Expected return values: 1, 2, 3. Capture: `cat state/stormtree/lineage.json`.

**Anti-patterns to watch for** (from `FUNCTIONAL_QA_STRATEGY.md`):
- **Anti-pattern E** (timezone-unaware datetimes): every comparison MUST go through tz-aware datetimes. The dataclass `__post_init__` enforces this at construction time. Tests must include a mixed-offset case.
- **Anti-pattern A** (HOME redirect): every test goes through the `state_root` fixture (which is rooted under `tmp_path`). Never call `Path.home()` or `os.path.expanduser("~")` in this phase's code or tests. The autouse conftest guard from Phase 1 will fail-fast if the redirect leaks.

---

## External Interfaces Consumed

- **`ownership.json` JSON schema** (croam-internal but documented as Surface 4 in `PROJECT_PLAN.md` Data Schemas and `CODEBASE_CONTEXT.md` Data Models)
  - **Consumed by**: `src/croam/ownership.py` (`read_local_assertions`, `_dict_to_assertions`).
  - **How to capture**: this phase is the FIRST AUTHOR of the on-disk schema (no real instance exists yet). Capture an example by constructing a synthetic Assertion in the REPL and serializing it through `write_local_assertions`, then `cat` the result:
    ```bash
    cd /home/tunc/Sync/Programs/croam
    uv run python -c "
    from datetime import datetime, timezone
    from pathlib import Path
    from croam.ownership import Assertion, write_local_assertions
    a = Assertion(
      sid='ff7afd8a-ea17-4183-a131-566e7bcb0758',
      owner='stormtree',
      asserted_at=datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc),
      action='create',
      cwd_normalized='~/Programs/croam',
      previous_owner=None,
    )
    write_local_assertions(Path('/tmp/croam-phase4-demo/state'), 'stormtree', {a.sid: a})
    "
    cat /tmp/croam-phase4-demo/state/stormtree/ownership.json
    ```
    Paste the resulting JSON into your phase summary's "Evidence Captured" section. This becomes the reference example for Phase 7, 8, 9 to consume.
  - **If not observable**: not applicable. We are the author.

- **ISO8601 datetime strings** (RFC 3339 / Python `datetime.isoformat()` output)
  - **Consumed by**: `_parse_iso_utc` helper in `src/croam/ownership.py`.
  - **How to capture**:
    ```bash
    uv run python -c "
    import datetime
    print('aware UTC:    ', datetime.datetime.now(datetime.timezone.utc).isoformat())
    print('aware -05:00: ', datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5))).isoformat())
    print('naive:        ', datetime.datetime.now().isoformat())
    print('Z form:       ', datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    "
    ```
    Paste the four sample strings into your phase summary's "Evidence Captured" section. Verify your `_parse_iso_utc` accepts the first two and the Z form, and rejects the naive form.
  - **If not observable**: not applicable. Standard library output.

---

## Notes

- **Order of writes is critical for outclaim recovery.** Phase 8's `claim` will: (a) write our new assertion locally, (b) flatten our local file, (c) trigger Phase 8-side cleanup of the old owner's transcript. Phase 4 only provides the primitives; Phase 8 sequences them. Do NOT add any cross-phase orchestration here.
- **Do NOT pre-create `<state_root>/<hostname>/projects/`** -- that subtree is for syncthing-mirrored claude transcripts and is owned by the user's syncthing config, not croam. Phase 4 only manages `ownership.json` and `lineage.json`.
- **Logging discipline**: log at DEBUG for every read/write of count/size; log at INFO when `flatten_local` drops entries (a state transition the user may want to see); log at WARNING when `read_all_assertions` skips a corrupt peer file. Never log assertion CONTENT (it includes cwd_normalized which may include user-private path components).
- **JSON sort order matters.** `sort_keys=True` and `sorted(assertions.items())` produce stable output. Without this, every write produces a permutation of the same data and syncthing replicates it again. Verify with `test_write_stable_bytes`.
- **The wire format is FROZEN by this phase.** Adding fields later requires coordinating across hosts. If you discover during implementation that a field is missing (e.g., for Phase 8's needs), add it to a SEPARATE file (e.g., snapshots.json) and document the choice in your phase summary -- do NOT widen `Assertion`.
- **Tempfile cleanup on success path**: `os.replace` MOVES the tempfile to the target path; the tempfile no longer exists after success. The `try/except BaseException` handles only the failure path. Do not add a `finally` that unlinks unconditionally -- that would race with the rename.
- **`asdict()` is NOT used to serialize Assertion** because `datetime` objects need explicit `.isoformat()`. The serialization in `write_local_assertions` is hand-written for that reason.
