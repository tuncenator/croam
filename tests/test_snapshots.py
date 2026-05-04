"""Tests for src/croam/snapshots.py -- snapshot-line-count sidecar store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from croam.snapshots import get_snapshot_line_count, read_snapshots, write_snapshot


class TestReadSnapshots:
    def test_returns_empty_when_file_missing(self, state_root: Path) -> None:
        result = read_snapshots(state_root, "stormtree")
        assert result == {}

    def test_reads_existing_file(self, state_root: Path) -> None:
        d = state_root / "stormtree"
        d.mkdir(parents=True, exist_ok=True)
        payload = {"sid-1": {"line_count": 42}, "sid-2": {"line_count": 7}}
        (d / "snapshots.json").write_text(json.dumps(payload))
        result = read_snapshots(state_root, "stormtree")
        assert result == {"sid-1": 42, "sid-2": 7}

    def test_raises_on_malformed_json(self, state_root: Path) -> None:
        d = state_root / "stormtree"
        d.mkdir(parents=True, exist_ok=True)
        (d / "snapshots.json").write_text("{invalid json")
        with pytest.raises(Exception, match="Malformed"):
            read_snapshots(state_root, "stormtree")

    def test_raises_on_non_object_top_level(self, state_root: Path) -> None:
        d = state_root / "stormtree"
        d.mkdir(parents=True, exist_ok=True)
        (d / "snapshots.json").write_text(json.dumps([1, 2, 3]))
        with pytest.raises(Exception, match="Expected"):
            read_snapshots(state_root, "stormtree")


class TestWriteSnapshot:
    def test_creates_file_when_missing(self, state_root: Path) -> None:
        write_snapshot(state_root, "stormtree", "sid-abc", 55)
        result = read_snapshots(state_root, "stormtree")
        assert result == {"sid-abc": 55}

    def test_updates_existing_entry(self, state_root: Path) -> None:
        write_snapshot(state_root, "stormtree", "sid-1", 10)
        write_snapshot(state_root, "stormtree", "sid-1", 20)
        result = read_snapshots(state_root, "stormtree")
        assert result == {"sid-1": 20}

    def test_preserves_other_entries(self, state_root: Path) -> None:
        write_snapshot(state_root, "stormtree", "sid-1", 10)
        write_snapshot(state_root, "stormtree", "sid-2", 20)
        result = read_snapshots(state_root, "stormtree")
        assert result == {"sid-1": 10, "sid-2": 20}

    def test_creates_parent_dirs(self, home: Path) -> None:
        sr = home / "nonexist" / "state"
        write_snapshot(sr, "host-x", "sid-z", 3)
        result = read_snapshots(sr, "host-x")
        assert result == {"sid-z": 3}


class TestReadSnapshotsEdgeCases:
    def test_reads_bare_int_format(self, state_root: Path) -> None:
        """Backward compat: accepts {sid: int} format."""
        import json

        d = state_root / "stormtree"
        d.mkdir(parents=True, exist_ok=True)
        (d / "snapshots.json").write_text(json.dumps({"sid-old": 99}))
        result = read_snapshots(state_root, "stormtree")
        assert result == {"sid-old": 99}

    def test_ignores_malformed_entry(self, state_root: Path) -> None:
        """Malformed entry (non-dict, non-int) is skipped with warning."""
        import json

        d = state_root / "stormtree"
        d.mkdir(parents=True, exist_ok=True)
        (d / "snapshots.json").write_text(json.dumps({"good": {"line_count": 5}, "bad": "string"}))
        result = read_snapshots(state_root, "stormtree")
        assert result == {"good": 5}


class TestWriteSnapshotCorrupt:
    def test_write_over_corrupt_file(self, state_root: Path) -> None:
        """write_snapshot on corrupt existing file resets to just the new entry."""
        d = state_root / "stormtree"
        d.mkdir(parents=True, exist_ok=True)
        (d / "snapshots.json").write_text("{bad json")
        write_snapshot(state_root, "stormtree", "new-sid", 10)
        result = read_snapshots(state_root, "stormtree")
        assert result == {"new-sid": 10}


class TestGetSnapshotLineCount:
    def test_returns_none_when_no_snapshot(self, state_root: Path) -> None:
        assert get_snapshot_line_count(state_root, "stormtree", "sid-nope") is None

    def test_returns_line_count_when_present(self, state_root: Path) -> None:
        write_snapshot(state_root, "stormtree", "sid-x", 77)
        assert get_snapshot_line_count(state_root, "stormtree", "sid-x") == 77
