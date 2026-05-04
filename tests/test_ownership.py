"""Tests for src/croam/ownership.py -- all 22 cases from the phase plan."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from croam.errors import OwnershipConflict
from croam.ownership import (
    Assertion,
    add_lineage,
    detect_outclaim,
    flatten_local,
    merge_assertions,
    read_all_assertions,
    read_lineage,
    read_local_assertions,
    write_local_assertions,
)
from tests._helpers.synth_assertions import build_assertion, write_assertions_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Test 1: read_empty
# ---------------------------------------------------------------------------


def test_read_empty(state_root: Path) -> None:
    """read_local_assertions returns {} when ownership.json does not exist."""
    result = read_local_assertions(state_root, "stormtree")
    assert result == {}


# ---------------------------------------------------------------------------
# Test 2: read_one
# ---------------------------------------------------------------------------


def test_read_one(state_root: Path) -> None:
    """Write a synthetic ownership.json with one create-action entry; read; assert fields."""
    ts = _utc(2026, 4, 30, 10, 0)
    a = build_assertion("sid-1", "stormtree", ts, action="create", cwd_normalized="~/Programs/foo")
    write_assertions_file(state_root, "stormtree", {"sid-1": a})

    result = read_local_assertions(state_root, "stormtree")
    assert set(result.keys()) == {"sid-1"}
    got = result["sid-1"]
    assert got.sid == "sid-1"
    assert got.owner == "stormtree"
    assert got.asserted_at == ts
    assert got.action == "create"
    assert got.cwd_normalized == "~/Programs/foo"
    assert got.previous_owner is None


# ---------------------------------------------------------------------------
# Test 3: Z suffix accepted
# ---------------------------------------------------------------------------


def test_read_z_suffix_accepted(state_root: Path) -> None:
    """asserted_at with 'Z' suffix parses correctly with tzinfo == UTC."""
    raw = {
        "sid-z": {
            "owner": "stormtree",
            "asserted_at": "2026-04-30T10:00:00Z",
            "action": "create",
            "cwd_normalized": "~/x",
            "previous_owner": None,
        }
    }
    (state_root / "stormtree" / "ownership.json").write_text(json.dumps(raw), encoding="utf-8")
    result = read_local_assertions(state_root, "stormtree")
    assert result["sid-z"].asserted_at.tzinfo == UTC


# ---------------------------------------------------------------------------
# Test 4: naive datetime rejected
# ---------------------------------------------------------------------------


def test_read_naive_datetime_rejected(state_root: Path) -> None:
    """asserted_at without timezone offset raises OwnershipConflict."""
    raw = {
        "sid-naive": {
            "owner": "stormtree",
            "asserted_at": "2026-04-30T10:00:00",
            "action": "create",
            "cwd_normalized": "~/x",
            "previous_owner": None,
        }
    }
    (state_root / "stormtree" / "ownership.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(OwnershipConflict):
        read_local_assertions(state_root, "stormtree")


# ---------------------------------------------------------------------------
# Test 5: malformed JSON / non-object top-level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_content",
    ["{not json", '"a string"', "[]", "42"],
)
def test_read_malformed(state_root: Path, bad_content: str) -> None:
    """Malformed JSON or non-dict top-level raises OwnershipConflict."""
    (state_root / "stormtree" / "ownership.json").write_text(bad_content, encoding="utf-8")
    with pytest.raises(OwnershipConflict):
        read_local_assertions(state_root, "stormtree")


# ---------------------------------------------------------------------------
# Test 6: previous_owner missing vs explicit null
# ---------------------------------------------------------------------------


def test_read_previous_owner_missing_or_null(state_root: Path) -> None:
    """previous_owner missing or explicit null both parse as None."""
    raw = {
        "sid-missing": {
            "owner": "stormtree",
            "asserted_at": "2026-04-30T10:00:00+00:00",
            "action": "create",
            "cwd_normalized": "~/x",
            # no previous_owner key
        },
        "sid-null": {
            "owner": "stormtree",
            "asserted_at": "2026-04-30T10:00:00+00:00",
            "action": "create",
            "cwd_normalized": "~/y",
            "previous_owner": None,
        },
    }
    (state_root / "stormtree" / "ownership.json").write_text(json.dumps(raw), encoding="utf-8")
    result = read_local_assertions(state_root, "stormtree")
    assert result["sid-missing"].previous_owner is None
    assert result["sid-null"].previous_owner is None


# ---------------------------------------------------------------------------
# Test 7: claim without previous_owner rejected
# ---------------------------------------------------------------------------


def test_claim_without_previous_owner_rejected(home: Path) -> None:
    """Assertion(action='claim', previous_owner=None) raises OwnershipConflict."""
    with pytest.raises(OwnershipConflict, match="previous_owner"):
        Assertion(
            sid="x",
            owner="a",
            asserted_at=_now_utc(),
            action="claim",
            cwd_normalized="~/x",
            previous_owner=None,
        )


# ---------------------------------------------------------------------------
# Test 8: create with previous_owner rejected
# ---------------------------------------------------------------------------


def test_create_with_previous_owner_rejected(home: Path) -> None:
    """Assertion(action='create', previous_owner='b') raises OwnershipConflict."""
    with pytest.raises(OwnershipConflict, match="previous_owner"):
        Assertion(
            sid="x",
            owner="a",
            asserted_at=_now_utc(),
            action="create",
            cwd_normalized="~/x",
            previous_owner="b",
        )


# ---------------------------------------------------------------------------
# Test 9: merge two hosts no overlap
# ---------------------------------------------------------------------------


def test_merge_two_hosts_no_overlap(state_root: Path) -> None:
    """Hosts A and B own disjoint sids; merge returns union."""
    ts = _utc(2026, 4, 30, 10)
    a1 = build_assertion("sid-a", "stormtree", ts)
    b1 = build_assertion("sid-b", "vicar", ts)
    per_host = {
        "stormtree": {"sid-a": a1},
        "vicar": {"sid-b": b1},
    }
    merged = merge_assertions(per_host)
    assert set(merged.keys()) == {"sid-a", "sid-b"}
    assert merged["sid-a"].owner == "stormtree"
    assert merged["sid-b"].owner == "vicar"


# ---------------------------------------------------------------------------
# Test 10: merge overlap, A wins (later asserted_at)
# ---------------------------------------------------------------------------


def test_merge_overlap_a_wins(state_root: Path) -> None:
    """Both A and B claim sid X; A.asserted_at > B.asserted_at; merge picks A."""
    ts_a = _utc(2026, 4, 30, 11)
    ts_b = _utc(2026, 4, 30, 10)
    a = build_assertion("sid-x", "stormtree", ts_a)
    b = build_assertion("sid-x", "vicar", ts_b)
    merged = merge_assertions({"stormtree": {"sid-x": a}, "vicar": {"sid-x": b}})
    assert merged["sid-x"].owner == "stormtree"


# ---------------------------------------------------------------------------
# Test 11: merge timezone aware
# ---------------------------------------------------------------------------


def test_merge_timezone_aware(state_root: Path) -> None:
    """Mixed offsets compared correctly as UTC instants.

    A asserts at 10:00+00:00 (10:00 UTC).
    B asserts at 04:00-05:00 (09:00 UTC).
    A wins (later absolute instant).
    """
    ts_a = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
    tz_minus5 = timezone(timedelta(hours=-5))
    ts_b = datetime(2026, 4, 30, 4, 0, tzinfo=tz_minus5)  # 09:00 UTC

    a = build_assertion("sid-tz", "stormtree", ts_a)
    b = build_assertion("sid-tz", "vicar", ts_b)
    merged = merge_assertions({"stormtree": {"sid-tz": a}, "vicar": {"sid-tz": b}})
    assert merged["sid-tz"].owner == "stormtree"


# ---------------------------------------------------------------------------
# Test 12: merge tiebreaker alphabetical
# ---------------------------------------------------------------------------


def test_merge_tiebreaker_alphabetical(state_root: Path) -> None:
    """Identical asserted_at: alphabetical-by-owner, smaller wins (a < b)."""
    ts = _utc(2026, 4, 30, 10)
    a = build_assertion("sid-tie", "alpha", ts)
    b = build_assertion("sid-tie", "bravo", ts)
    merged = merge_assertions({"alpha": {"sid-tie": a}, "bravo": {"sid-tie": b}})
    assert merged["sid-tie"].owner == "alpha"


# ---------------------------------------------------------------------------
# Test 13: atomic crash preserves original
# ---------------------------------------------------------------------------


def test_write_atomic_crash_preserves_original(
    state_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mid-write crash leaves original file untouched; no .tmp. files remain."""
    ts = _utc(2026, 4, 30, 10)
    original = build_assertion("sid-orig", "stormtree", ts)
    write_local_assertions(state_root, "stormtree", {"sid-orig": original})

    # Verify original written correctly.
    check = read_local_assertions(state_root, "stormtree")
    assert "sid-orig" in check

    # Inject failure at os.replace.
    def boom(src: str, dst: str) -> None:
        raise OSError("simulated disk full")

    monkeypatch.setattr("os.replace", boom)

    new_assertion = build_assertion("sid-new", "stormtree", _utc(2026, 4, 30, 11))
    with pytest.raises(OSError, match="simulated"):
        write_local_assertions(state_root, "stormtree", {"sid-new": new_assertion})

    monkeypatch.undo()

    # Original content must be unchanged.
    after = read_local_assertions(state_root, "stormtree")
    assert set(after.keys()) == {"sid-orig"}

    # No leftover .tmp. files.
    dir_path = state_root / "stormtree"
    tmp_files = list(dir_path.glob(".ownership.json.tmp.*"))
    assert tmp_files == [], f"leftover tmp files: {tmp_files}"


# ---------------------------------------------------------------------------
# Test 14: stable bytes
# ---------------------------------------------------------------------------


def test_write_stable_bytes(state_root: Path) -> None:
    """Two writes of identical dict produce byte-identical files."""
    ts = _utc(2026, 4, 30, 10)
    assertions = {
        "sid-b": build_assertion("sid-b", "vicar", ts),
        "sid-a": build_assertion("sid-a", "stormtree", ts),
    }
    path = state_root / "stormtree" / "ownership.json"
    write_local_assertions(state_root, "stormtree", assertions)
    first = path.read_bytes()
    write_local_assertions(state_root, "stormtree", assertions)
    second = path.read_bytes()
    assert first == second


# ---------------------------------------------------------------------------
# Test 15: flatten drops outclaimed sids
# ---------------------------------------------------------------------------


def test_flatten_drops_outclaimed(state_root: Path) -> None:
    """flatten_local removes sids where merged says another host is owner."""
    ts = _utc(2026, 4, 30, 10)
    sx = build_assertion("sid-x", "stormtree", ts)
    sy = build_assertion("sid-y", "stormtree", ts)
    write_local_assertions(state_root, "stormtree", {"sid-x": sx, "sid-y": sy})

    # merged says stormtree owns X, vicar owns Y
    merged = {
        "sid-x": build_assertion("sid-x", "stormtree", ts),
        "sid-y": build_assertion("sid-y", "vicar", _utc(2026, 4, 30, 11)),
    }
    flatten_local(state_root, "stormtree", merged)

    result = read_local_assertions(state_root, "stormtree")
    assert set(result.keys()) == {"sid-x"}


# ---------------------------------------------------------------------------
# Test 16: detect_outclaim
# ---------------------------------------------------------------------------


def test_detect_outclaim(state_root: Path) -> None:
    """detect_outclaim returns sorted list of sids claimed by another host."""
    ts = _utc(2026, 4, 30, 10)
    sx = build_assertion("sid-x", "stormtree", ts)
    sy = build_assertion("sid-y", "stormtree", ts)
    sz = build_assertion("sid-z", "stormtree", ts)
    write_local_assertions(state_root, "stormtree", {"sid-x": sx, "sid-y": sy, "sid-z": sz})

    merged = {
        "sid-x": build_assertion("sid-x", "stormtree", ts),
        "sid-y": build_assertion("sid-y", "vicar", _utc(2026, 4, 30, 11)),
        "sid-z": build_assertion("sid-z", "stormtree", ts),
    }
    result = detect_outclaim(state_root, "stormtree", merged)
    assert result == ["sid-y"]


# ---------------------------------------------------------------------------
# Test 17: read_all skips dirs without ownership.json
# ---------------------------------------------------------------------------


def test_read_all_skips_dirs_without_ownership(state_root: Path) -> None:
    """Subdirectory without ownership.json is silently skipped."""
    (state_root / "foo").mkdir(exist_ok=True)
    result = read_all_assertions(state_root)
    assert "foo" not in result


# ---------------------------------------------------------------------------
# Test 18: read_all continues past corrupt peer
# ---------------------------------------------------------------------------


def test_read_all_continues_past_corrupt_peer(state_root: Path) -> None:
    """Corrupt peer ownership.json is skipped with WARNING; valid peer returned."""
    from loguru import logger

    ts = _utc(2026, 4, 30, 10)
    good = build_assertion("sid-good", "stormtree", ts)
    write_assertions_file(state_root, "stormtree", {"sid-good": good})

    # Write corrupt JSON for vicar.
    (state_root / "vicar" / "ownership.json").write_text("{not json", encoding="utf-8")

    captured: list[str] = []
    sink_id = logger.add(lambda msg: captured.append(msg), level="WARNING")
    try:
        result = read_all_assertions(state_root)
    finally:
        logger.remove(sink_id)

    assert "stormtree" in result
    assert "vicar" not in result
    assert any("vicar" in msg for msg in captured)


# ---------------------------------------------------------------------------
# Test 19: read_all peer_states override
# ---------------------------------------------------------------------------


def test_read_all_peer_states_override(state_root: Path) -> None:
    """peer_states overrides on-disk read for that hostname (live SSH wins)."""
    ts_disk = _utc(2026, 4, 30, 10)
    ts_live = _utc(2026, 4, 30, 11)

    on_disk = build_assertion("sid-x", "stormtree", ts_disk)
    write_assertions_file(state_root, "stormtree", {"sid-x": on_disk})

    live_payload = {
        "sid-x": {
            "owner": "stormtree",
            "asserted_at": ts_live.isoformat(),
            "action": "create",
            "cwd_normalized": "~/x",
            "previous_owner": None,
        }
    }
    result = read_all_assertions(state_root, peer_states={"stormtree": live_payload})
    assert result["stormtree"]["sid-x"].asserted_at == ts_live


# ---------------------------------------------------------------------------
# Test 20: lineage increments
# ---------------------------------------------------------------------------


def test_lineage_increments(state_root: Path) -> None:
    """add_lineage returns 1, 2, 3 for successive forks of same parent."""
    n1 = add_lineage(state_root, "stormtree", "fork-1", "parent-a")
    n2 = add_lineage(state_root, "stormtree", "fork-2", "parent-a")
    n3 = add_lineage(state_root, "stormtree", "fork-3", "parent-a")
    assert (n1, n2, n3) == (1, 2, 3)

    lineage = read_lineage(state_root, "stormtree")
    assert lineage["fork-1"].fork_n == 1
    assert lineage["fork-2"].fork_n == 2
    assert lineage["fork-3"].fork_n == 3


# ---------------------------------------------------------------------------
# Test 21: lineage independent parents
# ---------------------------------------------------------------------------


def test_lineage_independent_parents(state_root: Path) -> None:
    """Different parents have independent fork_n counters starting at 1."""
    n1 = add_lineage(state_root, "stormtree", "f1", "parent-1")
    n2 = add_lineage(state_root, "stormtree", "f2", "parent-2")
    assert n1 == 1
    assert n2 == 1


# ---------------------------------------------------------------------------
# Test 22: e2e outclaim recovery
# ---------------------------------------------------------------------------


def test_e2e_outclaim_recovery(state_root: Path) -> None:
    """End-to-end: A asserts X at T1; B asserts X at T2>T1; A detects outclaim; flatten removes X."""
    t1 = _utc(2026, 4, 30, 10)
    t2 = _utc(2026, 4, 30, 11)

    a_assertion = build_assertion("sid-x", "stormtree", t1)
    b_assertion = build_assertion("sid-x", "vicar", t2, action="claim", previous_owner="stormtree")

    write_assertions_file(state_root, "stormtree", {"sid-x": a_assertion})
    write_assertions_file(state_root, "vicar", {"sid-x": b_assertion})

    per_host = read_all_assertions(state_root)
    merged = merge_assertions(per_host)

    assert merged["sid-x"].owner == "vicar"

    outclaimed = detect_outclaim(state_root, "stormtree", merged)
    assert outclaimed == ["sid-x"]

    flatten_local(state_root, "stormtree", merged)

    final = read_local_assertions(state_root, "stormtree")
    assert final == {}


# ---------------------------------------------------------------------------
# Coverage gap tests (validation branches not hit by the 22 main tests)
# ---------------------------------------------------------------------------


def test_parse_iso_utc_bad_format(home: Path) -> None:
    """_parse_iso_utc raises OwnershipConflict for a completely invalid datetime string."""
    from croam.ownership import _parse_iso_utc

    with pytest.raises(OwnershipConflict, match="Cannot parse"):
        _parse_iso_utc("not-a-date")


def test_dict_to_assertions_non_dict_entry(state_root: Path) -> None:
    """Entry that is not a dict raises OwnershipConflict."""
    raw = '{"sid-bad": "string-not-object"}'
    (state_root / "stormtree" / "ownership.json").write_text(raw, encoding="utf-8")
    with pytest.raises(OwnershipConflict, match="not an object"):
        read_local_assertions(state_root, "stormtree")


def test_dict_to_assertions_missing_required_field(state_root: Path) -> None:
    """Entry missing a required field raises OwnershipConflict."""
    raw = {
        "sid-bad": {
            "owner": "stormtree",
            # missing asserted_at, action, cwd_normalized
        }
    }
    (state_root / "stormtree" / "ownership.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(OwnershipConflict, match="missing required field"):
        read_local_assertions(state_root, "stormtree")


def test_dict_to_assertions_non_str_owner(state_root: Path) -> None:
    """Non-string owner raises OwnershipConflict."""
    raw = {
        "sid-bad": {
            "owner": 42,
            "asserted_at": "2026-04-30T10:00:00+00:00",
            "action": "create",
            "cwd_normalized": "~/x",
        }
    }
    (state_root / "stormtree" / "ownership.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(OwnershipConflict, match="owner must be str"):
        read_local_assertions(state_root, "stormtree")


def test_dict_to_assertions_non_str_cwd_normalized(state_root: Path) -> None:
    """Non-string cwd_normalized raises OwnershipConflict."""
    raw = {
        "sid-bad": {
            "owner": "stormtree",
            "asserted_at": "2026-04-30T10:00:00+00:00",
            "action": "create",
            "cwd_normalized": 99,
        }
    }
    (state_root / "stormtree" / "ownership.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(OwnershipConflict, match="cwd_normalized must be str"):
        read_local_assertions(state_root, "stormtree")


def test_dict_to_assertions_invalid_action(state_root: Path) -> None:
    """Invalid action value raises OwnershipConflict."""
    raw = {
        "sid-bad": {
            "owner": "stormtree",
            "asserted_at": "2026-04-30T10:00:00+00:00",
            "action": "destroy",
            "cwd_normalized": "~/x",
        }
    }
    (state_root / "stormtree" / "ownership.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(OwnershipConflict, match="action="):
        read_local_assertions(state_root, "stormtree")


def test_read_all_peer_states_invalid_skipped(state_root: Path) -> None:
    """Invalid peer_states payload is logged as WARNING and skipped."""
    from loguru import logger

    captured: list[str] = []
    sink_id = logger.add(lambda msg: captured.append(msg), level="WARNING")
    try:
        result = read_all_assertions(
            state_root,
            peer_states={"bad-host": "not-a-dict"},  # type: ignore[arg-type]
        )
    finally:
        logger.remove(sink_id)

    assert "bad-host" not in result
    assert any("bad-host" in msg for msg in captured)


def test_merge_tiebreaker_loser_not_selected(state_root: Path) -> None:
    """Tiebreaker: when b < a alphabetically, b wins (a is the loser branch)."""
    ts = _utc(2026, 4, 30, 10)
    # "alpha" < "bravo" so alpha should win
    alpha = build_assertion("sid-t", "alpha", ts)
    bravo = build_assertion("sid-t", "bravo", ts)
    # Feed bravo first so alpha must displace it via tiebreaker
    merged = merge_assertions({"bravo": {"sid-t": bravo}, "alpha": {"sid-t": alpha}})
    assert merged["sid-t"].owner == "alpha"


def test_write_local_assertion_singular(state_root: Path) -> None:
    """write_local_assertion (singular) inserts into existing file correctly."""
    from croam.ownership import write_local_assertion

    ts = _utc(2026, 4, 30, 10)
    a = build_assertion("sid-a", "stormtree", ts)
    write_local_assertions(state_root, "stormtree", {"sid-a": a})

    b = build_assertion("sid-b", "stormtree", ts)
    write_local_assertion(state_root, "stormtree", b)

    result = read_local_assertions(state_root, "stormtree")
    assert set(result.keys()) == {"sid-a", "sid-b"}


def test_flatten_no_drops_debug_branch(state_root: Path) -> None:
    """flatten_local when nothing is dropped takes the debug (no INFO) path."""
    ts = _utc(2026, 4, 30, 10)
    a = build_assertion("sid-x", "stormtree", ts)
    write_local_assertions(state_root, "stormtree", {"sid-x": a})

    merged = {"sid-x": build_assertion("sid-x", "stormtree", ts)}
    flatten_local(state_root, "stormtree", merged)  # no drops

    result = read_local_assertions(state_root, "stormtree")
    assert "sid-x" in result


def test_read_lineage_malformed_json(state_root: Path) -> None:
    """Malformed lineage.json raises OwnershipConflict."""
    (state_root / "stormtree" / "lineage.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(OwnershipConflict, match="Malformed JSON"):
        read_lineage(state_root, "stormtree")


def test_read_lineage_non_object(state_root: Path) -> None:
    """Non-object top-level in lineage.json raises OwnershipConflict."""
    (state_root / "stormtree" / "lineage.json").write_text("[]", encoding="utf-8")
    with pytest.raises(OwnershipConflict, match="Expected object"):
        read_lineage(state_root, "stormtree")


def test_read_lineage_entry_not_dict(state_root: Path) -> None:
    """Non-dict entry in lineage.json raises OwnershipConflict."""
    (state_root / "stormtree" / "lineage.json").write_text('{"f1": "bad"}', encoding="utf-8")
    with pytest.raises(OwnershipConflict, match="not an object"):
        read_lineage(state_root, "stormtree")


def test_read_lineage_missing_field(state_root: Path) -> None:
    """Missing parent_sid or fork_n in lineage entry raises OwnershipConflict."""
    (state_root / "stormtree" / "lineage.json").write_text(
        '{"f1": {"parent_sid": "p"}}', encoding="utf-8"
    )
    with pytest.raises(OwnershipConflict, match="missing required field"):
        read_lineage(state_root, "stormtree")


def test_read_lineage_fork_n_not_int(state_root: Path) -> None:
    """Non-int fork_n in lineage entry raises OwnershipConflict."""
    (state_root / "stormtree" / "lineage.json").write_text(
        '{"f1": {"parent_sid": "p", "fork_n": "one"}}', encoding="utf-8"
    )
    with pytest.raises(OwnershipConflict, match="fork_n must be int"):
        read_lineage(state_root, "stormtree")


def test_assertion_naive_asserted_at_rejected(home: Path) -> None:
    """Assertion.__post_init__ raises OwnershipConflict for naive asserted_at."""
    naive = datetime(2026, 4, 30, 10, 0)  # no tzinfo
    with pytest.raises(OwnershipConflict, match="tz-aware"):
        Assertion(
            sid="x",
            owner="stormtree",
            asserted_at=naive,
            action="create",
            cwd_normalized="~/x",
        )


def test_read_all_skips_non_dir_children(state_root: Path) -> None:
    """Non-directory children in state_root are skipped silently."""
    # Place a plain file (not a dir) directly in state_root.
    (state_root / "stale-file.json").write_text("{}", encoding="utf-8")
    result = read_all_assertions(state_root)
    assert "stale-file.json" not in result


def test_merge_later_assertion_displaces_earlier(state_root: Path) -> None:
    """When first host's assertion is older, second host's later assertion wins at line 258."""
    ts_early = _utc(2026, 4, 30, 9)
    ts_late = _utc(2026, 4, 30, 10)
    # vicar inserted first with EARLY time, then stormtree with LATE time
    vicar_early = build_assertion("sid-race", "vicar", ts_early)
    storm_late = build_assertion("sid-race", "stormtree", ts_late)
    # Dict insertion order: vicar first so it becomes current, then stormtree displaces via >
    merged = merge_assertions(
        {"vicar": {"sid-race": vicar_early}, "stormtree": {"sid-race": storm_late}}
    )
    assert merged["sid-race"].owner == "stormtree"
