"""Tests for src/croam/sync.py -- syncthing mirror read helpers."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from croam.sync import (
    detect_conflict_files,
    mirror_freshness,
    mirror_jsonl_path,
    read_peer_state_from_mirror,
)

# ---------------------------------------------------------------------------
# read_peer_state_from_mirror
# ---------------------------------------------------------------------------


class TestReadPeerStateFromMirror:
    def test_returns_none_when_peer_subdir_missing(self, state_root: Path) -> None:
        # state_root fixture pre-creates stormtree/vicar/corpsefire
        # request a totally unknown hostname
        result = read_peer_state_from_mirror(state_root, "unknownhost")
        assert result is None

    def test_returns_empty_dicts_when_json_files_absent(self, state_root: Path) -> None:
        # stormtree dir exists but no JSON files written
        result = read_peer_state_from_mirror(state_root, "stormtree")
        assert result is not None
        assert result["ownership"] == {}
        assert result["lineage"] == {}
        assert result["host_cache"] == {}

    def test_reads_ownership_json(self, state_root: Path) -> None:
        peer_dir = state_root / "vicar"
        payload = {"sid1": {"owner": "vicar", "action": "create"}}
        (peer_dir / "ownership.json").write_text(json.dumps(payload), encoding="utf-8")

        result = read_peer_state_from_mirror(state_root, "vicar")
        assert result is not None
        assert result["ownership"] == payload

    def test_reads_lineage_json(self, state_root: Path) -> None:
        peer_dir = state_root / "vicar"
        payload = {"fork1": {"parent_sid": "orig1", "fork_n": 1}}
        (peer_dir / "lineage.json").write_text(json.dumps(payload), encoding="utf-8")

        result = read_peer_state_from_mirror(state_root, "vicar")
        assert result is not None
        assert result["lineage"] == payload

    def test_reads_host_cache_json(self, state_root: Path) -> None:
        peer_dir = state_root / "vicar"
        payload = {"last_seen": "2026-01-01T00:00:00Z"}
        (peer_dir / "host-cache.json").write_text(json.dumps(payload), encoding="utf-8")

        result = read_peer_state_from_mirror(state_root, "vicar")
        assert result is not None
        assert result["host_cache"] == payload

    def test_malformed_json_returns_empty_dict_and_logs_warning(
        self, state_root: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        peer_dir = state_root / "corpsefire"
        (peer_dir / "ownership.json").write_text("{invalid json}", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="croam.sync"):
            result = read_peer_state_from_mirror(state_root, "corpsefire")

        assert result is not None
        assert result["ownership"] == {}
        # lineage and host_cache still work
        assert result["lineage"] == {}

    def test_reads_all_three_files_simultaneously(self, state_root: Path) -> None:
        peer_dir = state_root / "stormtree"
        ownership = {"sid1": {"owner": "stormtree"}}
        lineage = {"fsid": {"parent_sid": "sid1", "fork_n": 1}}
        host_cache = {"updated": "2026-01-01T00:00:00Z"}
        (peer_dir / "ownership.json").write_text(json.dumps(ownership), encoding="utf-8")
        (peer_dir / "lineage.json").write_text(json.dumps(lineage), encoding="utf-8")
        (peer_dir / "host-cache.json").write_text(json.dumps(host_cache), encoding="utf-8")

        result = read_peer_state_from_mirror(state_root, "stormtree")
        assert result is not None
        assert result["ownership"] == ownership
        assert result["lineage"] == lineage
        assert result["host_cache"] == host_cache

    def test_stray_non_hostname_dir_is_readable(self, state_root: Path) -> None:
        # Create a stray dir that doesn't map to a known hostname
        stray = state_root / "stray-dir"
        stray.mkdir()
        payload = {"k": "v"}
        (stray / "ownership.json").write_text(json.dumps(payload), encoding="utf-8")

        result = read_peer_state_from_mirror(state_root, "stray-dir")
        assert result is not None
        assert result["ownership"] == payload


# ---------------------------------------------------------------------------
# detect_conflict_files
# ---------------------------------------------------------------------------


class TestDetectConflictFiles:
    def test_returns_empty_when_no_conflict_files(self, state_root: Path) -> None:
        result = detect_conflict_files(state_root)
        assert result == []

    def test_finds_single_conflict_file(self, state_root: Path) -> None:
        conflict = state_root / "vicar" / "ownership.sync-conflict-20260101-120000-ABCDEF.json"
        conflict.write_text("{}", encoding="utf-8")

        result = detect_conflict_files(state_root)
        assert result == [conflict]

    def test_finds_multiple_conflict_files_sorted(self, state_root: Path) -> None:
        c1 = state_root / "stormtree" / "a.sync-conflict-111.json"
        c2 = state_root / "vicar" / "b.sync-conflict-222.json"
        c1.write_text("{}", encoding="utf-8")
        c2.write_text("{}", encoding="utf-8")

        result = detect_conflict_files(state_root)
        assert len(result) == 2
        # sorted means lexicographic by full path
        assert result == sorted([c1, c2])

    def test_finds_nested_conflict_files(self, state_root: Path) -> None:
        subdir = state_root / "vicar" / "nested"
        subdir.mkdir()
        conflict = subdir / "deep.sync-conflict-xyz.json"
        conflict.write_text("{}", encoding="utf-8")

        result = detect_conflict_files(state_root)
        assert conflict in result

    def test_ignores_non_conflict_files(self, state_root: Path) -> None:
        normal = state_root / "vicar" / "ownership.json"
        normal.write_text("{}", encoding="utf-8")

        result = detect_conflict_files(state_root)
        assert result == []

    def test_returns_empty_when_state_root_missing(self, home: Path) -> None:
        missing = home / "does-not-exist"
        result = detect_conflict_files(missing)
        assert result == []


# ---------------------------------------------------------------------------
# mirror_freshness
# ---------------------------------------------------------------------------


class TestMirrorFreshness:
    def test_returns_none_when_peer_subdir_missing(self, state_root: Path) -> None:
        result = mirror_freshness(state_root, "unknownhost")
        assert result is None

    def test_returns_none_when_peer_subdir_empty(self, state_root: Path) -> None:
        # stormtree dir exists (created by fixture) but no files
        result = mirror_freshness(state_root, "stormtree")
        assert result is None

    def test_returns_timedelta_for_single_file(self, state_root: Path) -> None:
        f = state_root / "vicar" / "ownership.json"
        f.write_text("{}", encoding="utf-8")
        # Set mtime to exactly 30 minutes ago
        past = datetime.now(UTC) - timedelta(minutes=30)
        os.utime(f, (past.timestamp(), past.timestamp()))

        result = mirror_freshness(state_root, "vicar")
        assert result is not None
        # Should be approximately 30 minutes; allow some clock drift
        assert timedelta(minutes=28) < result < timedelta(minutes=32)

    def test_uses_most_recent_mtime_across_files(self, state_root: Path) -> None:
        peer_dir = state_root / "corpsefire"
        f1 = peer_dir / "ownership.json"
        f2 = peer_dir / "lineage.json"
        f1.write_text("{}", encoding="utf-8")
        f2.write_text("{}", encoding="utf-8")

        old_time = datetime.now(UTC) - timedelta(hours=5)
        recent_time = datetime.now(UTC) - timedelta(minutes=10)

        os.utime(f1, (old_time.timestamp(), old_time.timestamp()))
        os.utime(f2, (recent_time.timestamp(), recent_time.timestamp()))

        result = mirror_freshness(state_root, "corpsefire")
        assert result is not None
        # Most recent is 10 minutes ago; old one is 5 hours ago -- we use recent
        assert timedelta(minutes=8) < result < timedelta(minutes=12)

    def test_freshness_for_very_old_file(self, state_root: Path) -> None:
        f = state_root / "vicar" / "host-cache.json"
        f.write_text("{}", encoding="utf-8")
        # Set mtime to 25 hours ago
        past = datetime.now(UTC) - timedelta(hours=25)
        os.utime(f, (past.timestamp(), past.timestamp()))

        result = mirror_freshness(state_root, "vicar")
        assert result is not None
        assert result > timedelta(hours=24)

    def test_directories_not_counted_in_freshness(self, state_root: Path) -> None:
        peer_dir = state_root / "vicar"
        # Create a subdirectory (no files)
        subdir = peer_dir / "subdir"
        subdir.mkdir()

        # No files; should still return None
        result = mirror_freshness(state_root, "vicar")
        assert result is None


# ---------------------------------------------------------------------------
# mirror_jsonl_path
# ---------------------------------------------------------------------------


class TestMirrorJsonlPath:
    def test_returns_none_when_file_absent(self, state_root: Path) -> None:
        result = mirror_jsonl_path(state_root, "vicar", "-home-user-projects", "some-sid")
        assert result is None

    def test_returns_path_when_file_exists(self, state_root: Path) -> None:
        encoded_cwd = "-home-user-projects"
        sid = "abc12345-6789-abcd-ef01-23456789abcd"
        projects_dir = state_root / "vicar" / "projects" / encoded_cwd
        projects_dir.mkdir(parents=True)
        jsonl_file = projects_dir / f"{sid}.jsonl"
        jsonl_file.write_text('{"type": "assistant"}\n', encoding="utf-8")

        result = mirror_jsonl_path(state_root, "vicar", encoded_cwd, sid)
        assert result == jsonl_file
        assert result is not None and result.exists()

    def test_returns_none_for_wrong_sid(self, state_root: Path) -> None:
        encoded_cwd = "-home-user-projects"
        sid = "abc12345-6789-abcd-ef01-23456789abcd"
        projects_dir = state_root / "vicar" / "projects" / encoded_cwd
        projects_dir.mkdir(parents=True)
        (projects_dir / f"{sid}.jsonl").write_text("{}", encoding="utf-8")

        result = mirror_jsonl_path(state_root, "vicar", encoded_cwd, "wrong-sid")
        assert result is None

    def test_returns_none_when_peer_missing(self, state_root: Path) -> None:
        result = mirror_jsonl_path(state_root, "ghosthost", "-home-x", "sid1")
        assert result is None
