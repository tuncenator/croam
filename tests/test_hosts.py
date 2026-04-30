"""Tests for src/croam/hosts.py: probe_reachability, emit_state, fetch_remote_state."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path

from croam.commands.emit_state import emit_state_cmd
from croam.hosts import emit_state, fetch_remote_state, probe_reachability
from tests._helpers.synth_jsonl import build_jsonl
from tests._helpers.synth_session import build_session_metadata

# ---------------------------------------------------------------------------
# probe_reachability
# ---------------------------------------------------------------------------


def test_probe_empty_list(home: Path) -> None:
    """Empty host list returns empty dict without spinning up executor."""
    result = probe_reachability([])
    assert result == {}


def test_probe_reachable(home: Path, ssh_shim: object) -> None:
    """Shim exits 0 -> reachable=True, error=None."""
    ssh_shim.register("ok-host", ["true"], stdout="", stderr="", exit_code=0)  # type: ignore[attr-defined]
    result = probe_reachability(["ok-host"], timeout_s=2.0)
    assert result["ok-host"].reachable is True
    assert result["ok-host"].error is None


def test_probe_unreachable_timeout(home: Path, ssh_shim: object) -> None:
    """Shim sleeps longer than timeout -> reachable=False, error='timeout'."""
    ssh_shim.register("bad-host", ["true"], delay_s=5.0)  # type: ignore[attr-defined]
    result = probe_reachability(["bad-host"], timeout_s=0.5)
    assert result["bad-host"].reachable is False
    assert result["bad-host"].error == "timeout"


def test_probe_unreachable_resolution(home: Path, ssh_shim: object) -> None:
    """Shim exits 255 with DNS-failure stderr -> reachable=False, error contains message."""
    ssh_shim.register(  # type: ignore[attr-defined]
        "bogus-host",
        ["true"],
        stderr="ssh: Could not resolve hostname bogus-host: Name or service not known",
        exit_code=255,
    )
    result = probe_reachability(["bogus-host"], timeout_s=2.0)
    assert result["bogus-host"].reachable is False
    assert "Could not resolve" in (result["bogus-host"].error or "")


def test_probe_parallel(home: Path, ssh_shim: object) -> None:
    """8 hosts each with 0.2s delay; wall time must be < 1.0s (sequential = 1.6s)."""
    hosts = [f"host-{i}" for i in range(8)]
    for h in hosts:
        ssh_shim.register(h, ["true"], delay_s=0.2)  # type: ignore[attr-defined]
    t0 = time.monotonic()
    probe_reachability(hosts, timeout_s=2.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, f"Expected parallel execution, got {elapsed:.2f}s"


def test_probe_last_probed_utc(home: Path, ssh_shim: object) -> None:
    """last_probed is timezone-aware UTC."""
    ssh_shim.register("tz-host", ["true"], exit_code=0)  # type: ignore[attr-defined]
    result = probe_reachability(["tz-host"], timeout_s=2.0)
    status = result["tz-host"]
    assert status.last_probed.tzinfo is not None
    assert status.last_probed.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# emit_state
# ---------------------------------------------------------------------------


def test_emit_state_full(home: Path, state_root: Path) -> None:
    """Pre-populated state files + one session -> full payload."""
    hostname = "stormtree"
    host_dir = state_root / hostname

    ownership_data = {"host": hostname, "claimed_by": "tunc"}
    lineage_data = {"parent": None}
    host_cache_data = {"hosts": ["vicar"]}

    (host_dir / "ownership.json").write_text(json.dumps(ownership_data))
    (host_dir / "lineage.json").write_text(json.dumps(lineage_data))
    (host_dir / "host-cache.json").write_text(json.dumps(host_cache_data))

    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    cwd = home / "my-project"
    cwd.mkdir(parents=True)
    build_jsonl(home, sid, cwd)
    build_session_metadata(home, 12345, sid, cwd)

    payload = emit_state(home, state_root, hostname)

    assert set(payload.keys()) == {"hostname", "ownership", "lineage", "host_cache", "sessions"}
    assert payload["hostname"] == hostname
    assert payload["ownership"] == ownership_data
    assert payload["lineage"] == lineage_data
    assert payload["host_cache"] == host_cache_data
    assert len(payload["sessions"]) == 1
    assert payload["sessions"][0]["sid"] == sid


def test_emit_state_empty(home: Path, state_root: Path) -> None:
    """Nothing exists for hostname -> all state keys None, sessions empty."""
    payload = emit_state(home, state_root, "stormtree")
    assert payload == {
        "hostname": "stormtree",
        "ownership": None,
        "lineage": None,
        "host_cache": None,
        "sessions": [],
    }


def test_emit_state_corrupt_ownership(home: Path, state_root: Path) -> None:
    """Malformed ownership.json -> ownership key is None, WARNING logged."""
    from loguru import logger

    host_dir = state_root / "stormtree"
    (host_dir / "ownership.json").write_text("{bad json")

    warnings: list[str] = []
    sink_id = logger.add(lambda msg: warnings.append(msg), level="WARNING")
    try:
        payload = emit_state(home, state_root, "stormtree")
    finally:
        logger.remove(sink_id)

    assert payload["ownership"] is None
    assert any("ownership" in w or "Malformed" in w for w in warnings)


def test_emit_state_session_wire_shape(home: Path, state_root: Path) -> None:
    """Each session in wire format has exactly the required keys with JSON-serializable values."""
    sid = "11111111-2222-3333-4444-555555555555"
    cwd = home / "wire-project"
    cwd.mkdir(parents=True)
    build_jsonl(home, sid, cwd)
    build_session_metadata(home, 99, sid, cwd, name="my-session")

    payload = emit_state(home, state_root, "stormtree")

    assert len(payload["sessions"]) == 1
    wire = payload["sessions"][0]
    expected_keys = {
        "sid",
        "cwd",
        "transcript_path",
        "pid",
        "status",
        "started_at_ms",
        "updated_at_ms",
        "name",
        "version",
    }
    assert set(wire.keys()) == expected_keys
    # All values must be JSON-serializable (no Path, no datetime)
    json.dumps(wire)  # raises if not serializable


# ---------------------------------------------------------------------------
# fetch_remote_state
# ---------------------------------------------------------------------------

# fake_ssh strips all tokens starting with '-', so '--json' is dropped from the key
_EMIT_STATE_ARGV = ["croam", "emit-state"]


def test_fetch_remote_state_ok(home: Path, ssh_shim: object) -> None:
    """Shim prints valid JSON and exits 0 -> parsed dict returned."""
    expected = {
        "hostname": "some-host",
        "ownership": None,
        "lineage": None,
        "host_cache": None,
        "sessions": [],
    }
    ssh_shim.register(  # type: ignore[attr-defined]
        "some-host", _EMIT_STATE_ARGV, stdout=json.dumps(expected), exit_code=0
    )
    result = fetch_remote_state("some-host", "some-host")
    assert result == expected


def test_fetch_remote_state_timeout(home: Path, ssh_shim: object) -> None:
    """Shim sleeps -> timeout -> None with WARNING logged."""
    from loguru import logger

    ssh_shim.register("slow-host", _EMIT_STATE_ARGV, delay_s=5.0)  # type: ignore[attr-defined]

    warnings: list[str] = []
    sink_id = logger.add(lambda msg: warnings.append(msg), level="WARNING")
    try:
        result = fetch_remote_state("slow-host", "slow-host", timeout_s=0.5)
    finally:
        logger.remove(sink_id)

    assert result is None
    assert any("slow-host" in w or "timeout" in w for w in warnings)


def test_fetch_remote_state_bad_json(home: Path, ssh_shim: object) -> None:
    """Shim prints non-JSON -> None with WARNING logged."""
    from loguru import logger

    ssh_shim.register("bad-json-host", _EMIT_STATE_ARGV, stdout="not json", exit_code=0)  # type: ignore[attr-defined]

    warnings: list[str] = []
    sink_id = logger.add(lambda msg: warnings.append(msg), level="WARNING")
    try:
        result = fetch_remote_state("bad-json-host", "bad-json-host")
    finally:
        logger.remove(sink_id)

    assert result is None
    assert any("bad JSON" in w or "bad-json-host" in w for w in warnings)


def test_fetch_remote_state_nonzero_rc(home: Path, ssh_shim: object) -> None:
    """Shim exits 255 -> None with WARNING logged."""
    from loguru import logger

    ssh_shim.register(  # type: ignore[attr-defined]
        "fail-host", _EMIT_STATE_ARGV, stderr="connection refused", exit_code=255
    )

    warnings: list[str] = []
    sink_id = logger.add(lambda msg: warnings.append(msg), level="WARNING")
    try:
        result = fetch_remote_state("fail-host", "fail-host")
    finally:
        logger.remove(sink_id)

    assert result is None
    assert any("fail-host" in w or "rc=" in w for w in warnings)


# ---------------------------------------------------------------------------
# emit_state_cmd
# ---------------------------------------------------------------------------


def test_emit_state_cmd_writes_json(home: Path, state_root: Path, capsys: object) -> None:
    """emit_state_cmd returns 0 and writes valid JSON with correct hostname to stdout."""
    rc = emit_state_cmd(home, state_root, "stormtree")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert rc == 0
    parsed = json.loads(captured.out)
    assert parsed["hostname"] == "stormtree"
