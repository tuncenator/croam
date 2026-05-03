"""Tests for src/croam/commands/reconcile.py -- outclaim detection + fork-or-discard."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests._helpers.synth_assertions import build_assertion, write_assertions_file
from tests._helpers.synth_jsonl import build_jsonl


@pytest.fixture
def _config_file(home: Path):
    """Write a minimal config for stormtree."""
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.write_text(
        '[self]\nhostname = "stormtree"\n\n'
        '[hosts.stormtree]\nssh = "stormtree"\n\n'
        '[hosts.vicar]\nssh = "vicar"\n'
    )
    return cfg


class TestDetectOutclaimed:
    """Test the detection of sessions that were claimed away by a peer."""

    def test_no_outclaimed_returns_empty(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """No outclaimed sessions means empty list."""
        from croam.commands.reconcile import detect_outclaimed

        sid = str(uuid.uuid4())
        assertion = build_assertion(sid, "stormtree", datetime.now(UTC))
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        result = detect_outclaimed(state_root, "stormtree")
        assert result == []

    def test_detects_outclaimed_session(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """A session where peer has a later assertion should be detected."""
        from croam.commands.reconcile import detect_outclaimed

        sid = str(uuid.uuid4())
        t1 = datetime.now(UTC) - timedelta(hours=1)
        t2 = datetime.now(UTC)

        # stormtree created it earlier
        our_assertion = build_assertion(sid, "stormtree", t1)
        write_assertions_file(state_root, "stormtree", {sid: our_assertion})

        # vicar claimed it later
        their_assertion = build_assertion(
            sid, "vicar", t2, action="claim", previous_owner="stormtree"
        )
        write_assertions_file(state_root, "vicar", {sid: their_assertion})

        result = detect_outclaimed(state_root, "stormtree")
        assert sid in result


class TestReconcileAutoDiscard:
    """Auto-discard when no new lines were added since snapshot."""

    def test_auto_discard_no_new_lines(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """If JSONL line count matches snapshot, auto-discard (no prompt)."""
        from croam.commands.reconcile import reconcile_one
        from croam.ownership import read_local_assertions
        from croam.snapshots import write_snapshot

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "discardme"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=3)  # 2 header + 3 user = 5 lines

        # Snapshot matches current line count
        write_snapshot(state_root, "stormtree", sid, 5)

        assertion = build_assertion(sid, "stormtree", datetime.now(UTC))
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        # Peer claimed it
        t2 = datetime.now(UTC) + timedelta(seconds=1)
        their = build_assertion(
            sid, "vicar", t2, action="claim", previous_owner="stormtree"
        )
        write_assertions_file(state_root, "vicar", {sid: their})

        action = reconcile_one(
            sid, state_root=state_root, hostname="stormtree", home=home
        )
        assert action == "discard"

        # Our local assertion should be removed (flattened out)
        assertions = read_local_assertions(state_root, "stormtree")
        assert sid not in assertions


class TestReconcilePromptFork:
    """Prompt fork-or-discard when new lines exist."""

    def test_prompt_fork_when_new_lines(
        self, home: Path, state_root: Path, _config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If JSONL has more lines than snapshot, prompt; user chooses fork."""
        from croam.commands.reconcile import reconcile_one

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "forkme"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=5)  # 2 + 5 = 7 lines

        # Snapshot was taken at 5 lines (before 2 new user lines)
        from croam.snapshots import write_snapshot

        write_snapshot(state_root, "stormtree", sid, 5)

        assertion = build_assertion(sid, "stormtree", datetime.now(UTC))
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        # Peer claimed
        t2 = datetime.now(UTC) + timedelta(seconds=1)
        their = build_assertion(
            sid, "vicar", t2, action="claim", previous_owner="stormtree"
        )
        write_assertions_file(state_root, "vicar", {sid: their})

        # User chooses fork
        monkeypatch.setattr("builtins.input", lambda _: "f")

        action = reconcile_one(
            sid, state_root=state_root, hostname="stormtree", home=home
        )
        assert action == "fork"

    def test_prompt_discard_when_new_lines(
        self, home: Path, state_root: Path, _config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If user chooses discard, session is discarded."""
        from croam.commands.reconcile import reconcile_one
        from croam.ownership import read_local_assertions

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "discardnew"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=5)  # 7 lines

        from croam.snapshots import write_snapshot

        write_snapshot(state_root, "stormtree", sid, 5)

        assertion = build_assertion(sid, "stormtree", datetime.now(UTC))
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        t2 = datetime.now(UTC) + timedelta(seconds=1)
        their = build_assertion(
            sid, "vicar", t2, action="claim", previous_owner="stormtree"
        )
        write_assertions_file(state_root, "vicar", {sid: their})

        monkeypatch.setattr("builtins.input", lambda _: "d")

        action = reconcile_one(
            sid, state_root=state_root, hostname="stormtree", home=home
        )
        assert action == "discard"

        assertions = read_local_assertions(state_root, "stormtree")
        assert sid not in assertions


class TestReconcileNoSnapshot:
    """No snapshot: treat as if new lines exist (prompt)."""

    def test_no_snapshot_prompts(
        self, home: Path, state_root: Path, _config_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a snapshot, assume lines may have been added and prompt."""
        from croam.commands.reconcile import reconcile_one

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "nosnap"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=3)

        assertion = build_assertion(sid, "stormtree", datetime.now(UTC))
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        t2 = datetime.now(UTC) + timedelta(seconds=1)
        their = build_assertion(
            sid, "vicar", t2, action="claim", previous_owner="stormtree"
        )
        write_assertions_file(state_root, "vicar", {sid: their})

        monkeypatch.setattr("builtins.input", lambda _: "f")

        action = reconcile_one(
            sid, state_root=state_root, hostname="stormtree", home=home
        )
        assert action == "fork"


class TestReconcileAll:
    """Test reconcile_all orchestration."""

    def test_reconcile_all_empty(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """No outclaimed sessions returns empty list."""
        from croam.commands.reconcile import reconcile_all

        result = reconcile_all(state_root=state_root, hostname="stormtree", home=home)
        assert result == []

    def test_reconcile_all_processes_multiple(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """Multiple outclaimed sessions are all processed (auto-discard)."""
        from croam.commands.reconcile import reconcile_all
        from croam.snapshots import write_snapshot

        sids = []
        for i in range(3):
            sid = str(uuid.uuid4())
            sids.append(sid)
            cwd = home / "projects" / f"multi{i}"
            cwd.mkdir(parents=True)
            build_jsonl(home, sid, cwd, n_user=2)  # 4 lines
            write_snapshot(state_root, "stormtree", sid, 4)

        # Write our assertions
        our_assertions = {
            sid: build_assertion(sid, "stormtree", datetime.now(UTC))
            for sid in sids
        }
        write_assertions_file(state_root, "stormtree", our_assertions)

        # Vicar claims all of them
        t2 = datetime.now(UTC) + timedelta(seconds=1)
        their_assertions = {
            sid: build_assertion(sid, "vicar", t2, action="claim", previous_owner="stormtree")
            for sid in sids
        }
        write_assertions_file(state_root, "vicar", their_assertions)

        result = reconcile_all(state_root=state_root, hostname="stormtree", home=home)
        assert len(result) == 3
        for _sid, action in result:
            assert action == "discard"


class TestReconcileNoJsonl:
    """Reconcile with no JSONL auto-discards."""

    def test_no_jsonl_auto_discards(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """If JSONL doesn't exist, auto-discard without prompting."""
        from croam.commands.reconcile import reconcile_one

        sid = str(uuid.uuid4())
        # No JSONL, just assertions
        assertion = build_assertion(sid, "stormtree", datetime.now(UTC))
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        t2 = datetime.now(UTC) + timedelta(seconds=1)
        their = build_assertion(
            sid, "vicar", t2, action="claim", previous_owner="stormtree"
        )
        write_assertions_file(state_root, "vicar", {sid: their})

        action = reconcile_one(
            sid, state_root=state_root, hostname="stormtree", home=home
        )
        assert action == "discard"
