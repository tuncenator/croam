"""Tests for src/croam/commands/fork.py -- fork a session from JSONL."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests._helpers.synth_assertions import build_assertion, write_assertions_file
from tests._helpers.synth_jsonl import build_jsonl


@pytest.fixture
def _config_file(home: Path):
    """Write a minimal config for stormtree."""
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.write_text('[self]\nhostname = "stormtree"\n\n[hosts.stormtree]\nssh = "stormtree"\n')
    return cfg


class TestFork:
    def test_fork_creates_new_jsonl(self, home: Path, state_root: Path, _config_file: Path) -> None:
        """Fork should create a new JSONL file with a new sid."""
        from croam.commands.fork import run

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "alpha"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=5)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/alpha"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        fork_sid, rc = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0
        assert fork_sid != sid
        # The new JSONL should exist
        from croam.paths import encode_cwd

        encoded = encode_cwd(cwd)
        fork_path = home / ".claude" / "projects" / encoded / f"{fork_sid}.jsonl"
        assert fork_path.exists()

    def test_fork_copies_jsonl_content(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """Forked JSONL should match original content."""
        from croam.commands.fork import run

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "beta"
        cwd.mkdir(parents=True)
        orig_path = build_jsonl(home, sid, cwd, n_user=3)
        original_lines = orig_path.read_text().splitlines()

        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/beta"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        fork_sid, rc = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0

        from croam.paths import encode_cwd

        encoded = encode_cwd(cwd)
        fork_path = home / ".claude" / "projects" / encoded / f"{fork_sid}.jsonl"
        fork_lines = fork_path.read_text().splitlines()
        # Same line count (no trailing partial trimming needed in clean case)
        assert len(fork_lines) == len(original_lines)

    def test_fork_writes_lineage(self, home: Path, state_root: Path, _config_file: Path) -> None:
        """Fork should write a lineage entry with fork_n=1."""
        from croam.commands.fork import run
        from croam.ownership import read_lineage

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "gamma"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/gamma"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        fork_sid, rc = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0

        lineage = read_lineage(state_root, "stormtree")
        assert fork_sid in lineage
        assert lineage[fork_sid].parent_sid == sid
        assert lineage[fork_sid].fork_n == 1

    def test_fork_increments_fork_n(self, home: Path, state_root: Path, _config_file: Path) -> None:
        """Second fork of same parent should get fork_n=2."""
        from croam.commands.fork import run
        from croam.ownership import read_lineage

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "delta"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/delta"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        fork_sid1, rc1 = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc1 == 0
        fork_sid2, rc2 = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc2 == 0

        lineage = read_lineage(state_root, "stormtree")
        assert lineage[fork_sid1].fork_n == 1
        assert lineage[fork_sid2].fork_n == 2

    def test_fork_writes_ownership_assertion(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """Fork should create an ownership assertion for the new sid."""
        from croam.commands.fork import run
        from croam.ownership import read_local_assertions

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "epsilon"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/epsilon"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        fork_sid, rc = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0

        assertions = read_local_assertions(state_root, "stormtree")
        assert fork_sid in assertions
        assert assertions[fork_sid].owner == "stormtree"
        assert assertions[fork_sid].action == "create"
        assert assertions[fork_sid].cwd_normalized == "~/projects/epsilon"

    def test_fork_writes_snapshot(self, home: Path, state_root: Path, _config_file: Path) -> None:
        """Fork should write a snapshot with the line count."""
        from croam.commands.fork import run
        from croam.snapshots import get_snapshot_line_count

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "zeta"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=4)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/zeta"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        fork_sid, rc = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0

        # n_user=4 gives 2 header lines + 4 user lines = 6 lines
        lc = get_snapshot_line_count(state_root, "stormtree", fork_sid)
        assert lc == 6

    def test_fork_trims_trailing_partial_json(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """Fork should trim a trailing incomplete JSON line."""
        from croam.commands.fork import run

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "eta"
        cwd.mkdir(parents=True)
        jsonl_path = build_jsonl(home, sid, cwd, n_user=2)
        # Append a partial JSON line (simulating a crash mid-write)
        with jsonl_path.open("a") as f:
            f.write('{"type": "user", "incomplete_key": ')

        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/eta"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        fork_sid, rc = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0

        from croam.paths import encode_cwd

        encoded = encode_cwd(cwd)
        fork_path = home / ".claude" / "projects" / encoded / f"{fork_sid}.jsonl"
        # The partial line should be trimmed; only complete lines remain
        for line in fork_path.read_text().splitlines():
            json.loads(line)  # should not raise

    def test_fork_fails_when_jsonl_missing(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """Fork should raise SessionNotFound if JSONL doesn't exist."""
        from croam.commands.fork import run
        from croam.errors import SessionNotFound

        sid = str(uuid.uuid4())
        assertion = build_assertion(sid, "stormtree", datetime.now(UTC), cwd_normalized="~/missing")
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        with pytest.raises(SessionNotFound):
            run(sid, state_root=state_root, hostname="stormtree", home=home)

    def test_fork_with_here_rebase(
        self, home: Path, state_root: Path, _config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fork with here=True should place JSONL under CWD's encoded path."""
        from croam.commands.fork import run

        sid = str(uuid.uuid4())
        # Original session is in ~/projects/source
        source_cwd = home / "projects" / "source"
        source_cwd.mkdir(parents=True)
        build_jsonl(home, sid, source_cwd, n_user=2)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/source"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        # CWD is different: ~/projects/target
        target_cwd = home / "projects" / "target"
        target_cwd.mkdir(parents=True)
        monkeypatch.chdir(target_cwd)

        fork_sid, rc = run(sid, state_root=state_root, hostname="stormtree", home=home, here=True)
        assert rc == 0

        from croam.paths import encode_cwd

        # Should be placed under target_cwd's encoding
        encoded_target = encode_cwd(target_cwd)
        fork_path = home / ".claude" / "projects" / encoded_target / f"{fork_sid}.jsonl"
        assert fork_path.exists()
