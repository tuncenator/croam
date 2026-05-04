"""Tests for src/croam/commands/release.py -- receiving side of claim handshake."""

from __future__ import annotations

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


class TestRelease:
    def test_noop_when_not_owned(self, home: Path, state_root: Path, _config_file: Path) -> None:
        """Release for a sid we don't own should log no-op, return 0."""
        from croam.commands.release import run

        # sid owned by vicar, not stormtree
        sid = str(uuid.uuid4())
        assertion = build_assertion(sid, "vicar", datetime.now(UTC))
        write_assertions_file(state_root, "vicar", {sid: assertion})

        rc = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0

    def test_noop_when_sid_unknown(self, home: Path, state_root: Path, _config_file: Path) -> None:
        """Release for a sid not in any ownership file should return 0."""
        from croam.commands.release import run

        rc = run("nonexistent-sid", state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0

    def test_release_writes_assertion_and_removes_jsonl(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """Release for a self-owned sid writes release assertion, removes JSONL."""
        from croam.commands.release import run
        from croam.ownership import read_local_assertions

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "foo"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/foo"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        rc = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc == 0

        # Assertion should now be action="release"
        assertions = read_local_assertions(state_root, "stormtree")
        assert sid in assertions
        assert assertions[sid].action == "release"
        assert assertions[sid].owner == "stormtree"

    def test_release_is_idempotent(self, home: Path, state_root: Path, _config_file: Path) -> None:
        """Calling release twice for the same sid should succeed both times."""
        from croam.commands.release import run

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "bar"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/bar"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        rc1 = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc1 == 0
        rc2 = run(sid, state_root=state_root, hostname="stormtree", home=home)
        assert rc2 == 0

    def test_release_returns_jsonl_content(
        self, home: Path, state_root: Path, _config_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Release with emit_jsonl=True prints the JSONL content to stdout."""
        from croam.commands.release import run

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "baz"
        cwd.mkdir(parents=True)
        jsonl_path = build_jsonl(home, sid, cwd, n_user=3)
        original_content = jsonl_path.read_bytes()

        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/baz"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        rc = run(sid, state_root=state_root, hostname="stormtree", home=home, emit_jsonl=True)
        assert rc == 0

        captured = capsys.readouterr()
        # The emitted content should match the original JSONL bytes decoded
        assert captured.out == original_content.decode("utf-8")
