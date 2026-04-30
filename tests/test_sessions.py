"""Tests for src/croam/sessions.py: discover_local_sessions and tmux_attached."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from croam.sessions import discover_local_sessions, tmux_attached
from tests._helpers.synth_jsonl import build_jsonl
from tests._helpers.synth_session import build_session_metadata


def _make_sid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# discover_local_sessions tests
# ---------------------------------------------------------------------------


def test_discover_empty_home(home: Path) -> None:
    """No ~/.claude/projects directory -> empty list."""
    # home fixture creates ~/.claude/projects, so remove it
    import shutil

    shutil.rmtree(home / ".claude" / "projects")
    result = discover_local_sessions(home)
    assert result == []


def test_discover_with_running_session(home: Path) -> None:
    """One jsonl + one session metadata -> ClaudeSession with live fields populated."""
    sid = _make_sid()
    cwd = home / "my-project"
    cwd.mkdir(parents=True)
    transcript = build_jsonl(home, sid, cwd)
    pid = 12345
    build_session_metadata(home, pid, sid, cwd, status="idle")

    result = discover_local_sessions(home)

    assert len(result) == 1
    s = result[0]
    assert s.sid == sid
    assert s.cwd == cwd
    assert s.transcript_path == transcript
    assert s.pid == pid
    assert s.status in ("idle", "busy")
    assert isinstance(s.started_at_ms, int) and s.started_at_ms > 0
    assert isinstance(s.updated_at_ms, int) and s.updated_at_ms > 0


def test_discover_archived_session(home: Path) -> None:
    """Jsonl with no matching session metadata -> archived (all live fields None)."""
    sid = _make_sid()
    cwd = home / "old-project"
    cwd.mkdir(parents=True)
    build_jsonl(home, sid, cwd)

    result = discover_local_sessions(home)

    assert len(result) == 1
    s = result[0]
    assert s.pid is None
    assert s.status is None
    assert s.started_at_ms is None
    assert s.updated_at_ms is None


def test_discover_multiple_pids_same_sid(home: Path) -> None:
    """Two session metadata files with same sessionId -> highest updatedAt wins."""
    sid = _make_sid()
    cwd = home / "shared-project"
    cwd.mkdir(parents=True)
    build_jsonl(home, sid, cwd)

    now = int(time.time() * 1000)
    old_updated = now - 10000
    new_updated = now

    # Write old entry with higher PID
    sessions_dir = home / ".claude" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    old_meta = {
        "pid": 9999,
        "sessionId": sid,
        "cwd": str(cwd),
        "startedAt": old_updated - 5000,
        "updatedAt": old_updated,
        "status": "idle",
        "version": "2.1.123",
    }
    (sessions_dir / "9999.json").write_text(json.dumps(old_meta))

    # Write new entry with lower PID
    new_meta = {
        "pid": 1111,
        "sessionId": sid,
        "cwd": str(cwd),
        "startedAt": new_updated - 5000,
        "updatedAt": new_updated,
        "status": "idle",
        "version": "2.1.123",
    }
    (sessions_dir / "1111.json").write_text(json.dumps(new_meta))

    result = discover_local_sessions(home)

    assert len(result) == 1
    assert result[0].pid == 1111
    assert result[0].updated_at_ms == new_updated


def test_discover_skips_malformed_jsonl(home: Path) -> None:
    """Corrupt sessions/<PID>.json -> logged WARNING, transcript still returned as archived."""
    from loguru import logger

    sid = _make_sid()
    cwd = home / "some-project"
    cwd.mkdir(parents=True)
    build_jsonl(home, sid, cwd)

    # Write corrupt JSON
    sessions_dir = home / ".claude" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    bad_file = sessions_dir / "161066.json"
    bad_file.write_text("{this is not valid json")

    warnings: list[str] = []
    sink_id = logger.add(lambda msg: warnings.append(msg), level="WARNING")
    try:
        result = discover_local_sessions(home)
    finally:
        logger.remove(sink_id)

    assert len(result) == 1
    assert result[0].pid is None  # archived -- the corrupt file was skipped
    assert any("161066" in w or "Malformed" in w for w in warnings)


def test_discover_unknown_status_coerced_to_idle(home: Path) -> None:
    """Session metadata with unknown status -> coerced to 'idle'."""
    sid = _make_sid()
    cwd = home / "weird-project"
    cwd.mkdir(parents=True)
    build_jsonl(home, sid, cwd)
    build_session_metadata(home, 42, sid, cwd, status="weird")

    result = discover_local_sessions(home)

    assert len(result) == 1
    assert result[0].status == "idle"


def test_discover_no_status_field_defaults_idle(home: Path) -> None:
    """Session metadata without status key -> defaults to 'idle'."""
    sid = _make_sid()
    cwd = home / "nostatus-project"
    cwd.mkdir(parents=True)
    build_jsonl(home, sid, cwd)

    # Write a metadata file without the 'status' key
    sessions_dir = home / ".claude" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "pid": 55,
        "sessionId": sid,
        "cwd": str(cwd),
        "startedAt": int(time.time() * 1000),
        "updatedAt": int(time.time() * 1000),
        "version": "2.1.123",
    }
    (sessions_dir / "55.json").write_text(json.dumps(meta))

    result = discover_local_sessions(home)

    assert len(result) == 1
    assert result[0].status == "idle"


def test_discover_no_projects_dir_returns_empty(home: Path) -> None:
    """Only ~/.claude/sessions exists, no projects dir -> empty list."""
    import shutil

    shutil.rmtree(home / ".claude" / "projects")
    # sessions dir still exists from home fixture
    build_session_metadata(home, 77, _make_sid(), home / "x")

    result = discover_local_sessions(home)
    assert result == []


def test_discover_orphan_session_meta_ignored(home: Path) -> None:
    """sessions/<PID>.json with no matching transcript -> not included in results."""
    sid = _make_sid()
    cwd = home / "orphan-project"
    cwd.mkdir(parents=True)
    # Only metadata, no JSONL
    build_session_metadata(home, 999, sid, cwd)

    result = discover_local_sessions(home)
    assert result == []


def test_discover_orders_deterministic(home: Path) -> None:
    """Results sorted: updated_at_ms desc, then sid asc for ties."""
    now = int(time.time() * 1000)

    cwd_a = home / "project-a"
    cwd_b = home / "project-b"
    cwd_c = home / "project-c"
    for d in (cwd_a, cwd_b, cwd_c):
        d.mkdir(parents=True)

    # Use fixed sids so we can control alphabetical order for tie-breaking
    sid_a = "aaaa0000-0000-0000-0000-000000000001"
    sid_b = "bbbb0000-0000-0000-0000-000000000002"
    sid_c = "cccc0000-0000-0000-0000-000000000003"

    build_jsonl(home, sid_a, cwd_a)
    build_jsonl(home, sid_b, cwd_b)
    build_jsonl(home, sid_c, cwd_c)

    # sid_b gets newest updated_at, sid_a and sid_c same (tie -> sid_a first)
    sessions_dir = home / ".claude" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    for pid, sid, cwd, updated_at in [
        (1, sid_a, cwd_a, now - 1000),
        (2, sid_b, cwd_b, now),
        (3, sid_c, cwd_c, now - 1000),
    ]:
        meta = {
            "pid": pid,
            "sessionId": sid,
            "cwd": str(cwd),
            "startedAt": updated_at - 5000,
            "updatedAt": updated_at,
            "status": "idle",
            "version": "2.1.123",
        }
        (sessions_dir / f"{pid}.json").write_text(json.dumps(meta))

    result = discover_local_sessions(home)

    assert len(result) == 3
    assert result[0].sid == sid_b  # newest
    assert result[1].sid == sid_a  # tie, alphabetically first
    assert result[2].sid == sid_c  # tie, alphabetically second


# ---------------------------------------------------------------------------
# tmux_attached tests
# ---------------------------------------------------------------------------


def test_tmux_attached_no_server(home: Path, tmux_socket: Path) -> None:
    """Non-existent socket -> (False, False) without raising."""
    # tmux_socket fixture returns a path that doesn't exist yet
    result = tmux_attached("any-sid", sock=tmux_socket)
    assert result == (False, False)


def test_tmux_attached_session_present(home: Path, tmux_socket: Path) -> None:
    """Real tmux session exists -> (True, False) when not attached."""
    import subprocess

    # Start a real background tmux session on private socket
    subprocess.run(
        [
            "tmux",
            "-S", str(tmux_socket),
            "new-session",
            "-d",
            "-s", "claude-test-sid",
            "--",
            "sleep", "10",
        ],
        check=True,
    )
    try:
        has_session, attached = tmux_attached("test-sid", sock=tmux_socket)
        assert has_session is True
        assert attached is False  # daemon session, not attached
    finally:
        subprocess.run(
            ["tmux", "-S", str(tmux_socket), "kill-server"],
            capture_output=True,
        )


# ---------------------------------------------------------------------------
# Tier 2: real dummy discovery
# ---------------------------------------------------------------------------


def test_e2e_dummy_discovery(e2e_dummy: tuple[Path, str]) -> None:
    """Tier 2: discover the real dummy session; read-only."""
    _cwd, sid = e2e_dummy
    real_home = Path.home()
    before_files = set(real_home.glob(".claude/**/*"))

    result = discover_local_sessions(real_home)

    after_files = set(real_home.glob(".claude/**/*"))
    assert before_files == after_files, "discover_local_sessions mutated ~/.claude"

    matching = [s for s in result if s.sid == sid]
    assert len(matching) >= 1, f"Expected sid {sid} in results"
    s = matching[0]
    assert s.cwd == Path("/tmp/croam-e2e")
