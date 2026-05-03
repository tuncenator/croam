"""Tests for src/croam/commands/claim.py -- full claim handshake."""

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
    """Write a minimal config with stormtree + vicar."""
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.write_text(
        '[self]\nhostname = "stormtree"\n\n'
        '[hosts.stormtree]\nssh = "stormtree"\n\n'
        '[hosts.vicar]\nssh = "vicar"\n\n'
        '[ownership]\nclaim_verify = "ssh-strict"\n'
    )
    return cfg


@pytest.fixture
def _config_local_only(home: Path):
    """Config with claim_verify = local (skip SSH verification)."""
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.write_text(
        '[self]\nhostname = "stormtree"\n\n'
        '[hosts.stormtree]\nssh = "stormtree"\n\n'
        '[hosts.vicar]\nssh = "vicar"\n\n'
        '[ownership]\nclaim_verify = "local"\n'
    )
    return cfg


class TestClaimSelfOwned:
    """S1: shortcut when session is already self-owned."""

    def test_self_owned_returns_zero(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        """Claiming a session we already own should be a no-op, return 0."""
        from croam.commands.claim import run

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "mine"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd)
        assertion = build_assertion(
            sid, "stormtree", datetime.now(UTC), cwd_normalized="~/projects/mine"
        )
        write_assertions_file(state_root, "stormtree", {sid: assertion})

        rc = run(sid, state_root=state_root, hostname="stormtree", home=home, config_path=home / ".config" / "croam" / "config.toml")
        assert rc == 0


class TestClaimLocalVerify:
    """claim_verify=local: skip SSH pre-check, use syncthing mirror."""

    def test_claim_from_peer_local_verify(
        self, home: Path, state_root: Path, _config_local_only: Path, ssh_shim: object
    ) -> None:
        """Claim with local verify copies JSONL from syncthing mirror."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "theirs"
        cwd.mkdir(parents=True)

        # Simulate vicar's JSONL in the syncthing mirror (state_root/vicar/...)
        # For local-verify, the JSONL must exist locally (syncthing mirror)
        build_jsonl(home, sid, cwd, n_user=3)

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/theirs"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        assert rc == 0

        # Verify claim assertion was written
        assertions = read_local_assertions(state_root, "stormtree")
        assert sid in assertions
        assert assertions[sid].action == "claim"
        assert assertions[sid].owner == "stormtree"
        assert assertions[sid].previous_owner == "vicar"


class TestClaimSshStrict:
    """S2/S3: ssh-strict verification and cooperative release."""

    def test_claim_ssh_strict_cooperative(
        self, home: Path, state_root: Path, _config_file: Path, ssh_shim: object
    ) -> None:
        """Claim with ssh-strict: probe owner, release on origin, copy JSONL."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "remote"
        cwd.mkdir(parents=True)
        jsonl_path = build_jsonl(home, sid, cwd, n_user=2)
        jsonl_content = jsonl_path.read_text()

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/remote"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        # Register SSH responses for the shim:
        # 1. Reachability probe (ssh vicar true)
        ssh_shim.register("vicar", ["true"], exit_code=0)
        # 2. emit-state fetch for ssh-strict pre-verify
        emit_payload = json.dumps({
            "hostname": "vicar",
            "ownership": {
                sid: {
                    "owner": "vicar",
                    "asserted_at": assertion.asserted_at.isoformat(),
                    "action": "create",
                    "cwd_normalized": "~/projects/remote",
                    "previous_owner": None,
                }
            },
            "lineage": None,
            "host_cache": None,
            "sessions": [],
        })
        ssh_shim.register("vicar", ["croam", "emit-state", "--json"], stdout=emit_payload)
        # 3. Release on origin
        ssh_shim.register("vicar", ["croam", "release", sid], exit_code=0)
        # 4. JSONL fetch (cat over SSH)
        ssh_shim.register("vicar", ["cat", f".claude/projects/{jsonl_path.parent.name}/{sid}.jsonl"], stdout=jsonl_content)

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        assert rc == 0

        # Verify claim assertion
        assertions = read_local_assertions(state_root, "stormtree")
        assert sid in assertions
        assert assertions[sid].action == "claim"
        assert assertions[sid].previous_owner == "vicar"

    def test_claim_ssh_strict_cooperative_remote_fetch(
        self, home: Path, state_root: Path, _config_file: Path, ssh_shim: object
    ) -> None:
        """Claim when JSONL not local: fetches from remote."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions
        from croam.paths import encode_cwd

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "remotefetch"
        cwd.mkdir(parents=True)
        encoded = encode_cwd(cwd)

        # Create JSONL content but DON'T put it locally
        jsonl_content = '{"type":"last-prompt","sessionId":"' + sid + '"}\n{"type":"permission-mode","permissionMode":"default","sessionId":"' + sid + '"}\n'

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/remotefetch"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        # Register SSH responses
        ssh_shim.register("vicar", ["true"], exit_code=0)
        emit_payload = json.dumps({
            "hostname": "vicar",
            "ownership": {
                sid: {
                    "owner": "vicar",
                    "asserted_at": assertion.asserted_at.isoformat(),
                    "action": "create",
                    "cwd_normalized": "~/projects/remotefetch",
                    "previous_owner": None,
                }
            },
            "lineage": None,
            "host_cache": None,
            "sessions": [],
        })
        ssh_shim.register("vicar", ["croam", "emit-state", "--json"], stdout=emit_payload)
        ssh_shim.register("vicar", ["croam", "release", sid], exit_code=0)
        ssh_shim.register("vicar", ["cat", f".claude/projects/{encoded}/{sid}.jsonl"], stdout=jsonl_content)

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        assert rc == 0

        # Verify claim assertion and JSONL was fetched
        assertions = read_local_assertions(state_root, "stormtree")
        assert sid in assertions
        assert assertions[sid].action == "claim"

        # JSONL should now exist locally
        local_jsonl = home / ".claude" / "projects" / encoded / f"{sid}.jsonl"
        assert local_jsonl.exists()

    def test_claim_ssh_strict_conflict_warning(
        self, home: Path, state_root: Path, _config_file: Path, ssh_shim: object
    ) -> None:
        """Claim proceeds despite conflict warning when remote disagrees on owner."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "conflict"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=2)

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/conflict"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        ssh_shim.register("vicar", ["true"], exit_code=0)
        # Remote says owner is corpsefire (conflict)
        emit_payload = json.dumps({
            "hostname": "vicar",
            "ownership": {
                sid: {
                    "owner": "corpsefire",
                    "asserted_at": assertion.asserted_at.isoformat(),
                    "action": "claim",
                    "cwd_normalized": "~/projects/conflict",
                    "previous_owner": "vicar",
                }
            },
            "lineage": None,
            "host_cache": None,
            "sessions": [],
        })
        ssh_shim.register("vicar", ["croam", "emit-state", "--json"], stdout=emit_payload)
        ssh_shim.register("vicar", ["croam", "release", sid], exit_code=0)

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        # Should still proceed despite conflict warning
        assert rc == 0
        assertions = read_local_assertions(state_root, "stormtree")
        assert sid in assertions

    def test_claim_ssh_strict_unreachable_forced(
        self, home: Path, state_root: Path, _config_file: Path, ssh_shim: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claim when origin unreachable: forced claim with user confirmation."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "offline"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=2)

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/offline"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        # Vicar unreachable
        ssh_shim.register("vicar", ["true"], exit_code=255, stderr="Connection refused")

        # Simulate user confirming forced claim
        monkeypatch.setattr("builtins.input", lambda _: "y")

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        assert rc == 0

        assertions = read_local_assertions(state_root, "stormtree")
        assert sid in assertions
        assert assertions[sid].action == "claim"

    def test_claim_ssh_strict_unreachable_refused(
        self, home: Path, state_root: Path, _config_file: Path, ssh_shim: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claim when origin unreachable: user refuses forced claim."""
        from croam.commands.claim import run

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "refused"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=2)

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/refused"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        # Vicar unreachable
        ssh_shim.register("vicar", ["true"], exit_code=255, stderr="Connection refused")

        # Simulate user refusing
        monkeypatch.setattr("builtins.input", lambda _: "n")

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        assert rc == 1


class TestClaimSnapshot:
    """S6: claim writes snapshot."""

    def test_claim_writes_snapshot(
        self, home: Path, state_root: Path, _config_local_only: Path, ssh_shim: object
    ) -> None:
        """After claim, snapshot should record the JSONL line count."""
        from croam.commands.claim import run
        from croam.snapshots import get_snapshot_line_count

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "snap"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd, n_user=5)

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/snap"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        assert rc == 0

        # 2 header + 5 user = 7 lines
        lc = get_snapshot_line_count(state_root, "stormtree", sid)
        assert lc == 7


class TestClaimHere:
    """S5: --here rewrite."""

    def test_claim_here_moves_jsonl(
        self, home: Path, state_root: Path, _config_local_only: Path, ssh_shim: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claim with --here should move JSONL to CWD's encoded path."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions
        from croam.paths import encode_cwd

        sid = str(uuid.uuid4())
        source_cwd = home / "projects" / "source"
        source_cwd.mkdir(parents=True)
        build_jsonl(home, sid, source_cwd, n_user=2)

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/source"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        # CWD is different
        target_cwd = home / "projects" / "target"
        target_cwd.mkdir(parents=True)
        monkeypatch.chdir(target_cwd)

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
            here=True,
        )
        assert rc == 0

        # JSONL should be under target_cwd's encoding
        encoded_target = encode_cwd(target_cwd)
        new_path = home / ".claude" / "projects" / encoded_target / f"{sid}.jsonl"
        assert new_path.exists()

        # Old path should be gone
        encoded_source = encode_cwd(source_cwd)
        old_path = home / ".claude" / "projects" / encoded_source / f"{sid}.jsonl"
        assert not old_path.exists()

        # Assertion should have updated cwd
        assertions = read_local_assertions(state_root, "stormtree")
        assert assertions[sid].cwd_normalized == "~/projects/target"


class TestClaimMissingJsonl:
    """Claim proceeds even without local JSONL (with warning)."""

    def test_claim_without_jsonl_succeeds(
        self, home: Path, state_root: Path, _config_local_only: Path, ssh_shim: object
    ) -> None:
        """Claim for a session with no local JSONL still writes assertion."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        sid = str(uuid.uuid4())
        # No JSONL, just the assertion
        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/gone"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        assert rc == 0

        assertions = read_local_assertions(state_root, "stormtree")
        assert sid in assertions
        assert assertions[sid].action == "claim"


class TestClaimEofRefused:
    """EOFError on input() defaults to refusing forced claim."""

    def test_eof_on_input_returns_1(
        self, home: Path, state_root: Path, _config_file: Path, ssh_shim: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EOFError from input() should default to refusing."""
        from croam.commands.claim import run

        sid = str(uuid.uuid4())
        cwd = home / "projects" / "eof"
        cwd.mkdir(parents=True)
        build_jsonl(home, sid, cwd)

        assertion = build_assertion(
            sid, "vicar", datetime.now(UTC), cwd_normalized="~/projects/eof"
        )
        write_assertions_file(state_root, "vicar", {sid: assertion})

        ssh_shim.register("vicar", ["true"], exit_code=255)

        def raise_eof(_prompt: str) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)

        rc = run(
            sid,
            state_root=state_root,
            hostname="stormtree",
            home=home,
            config_path=home / ".config" / "croam" / "config.toml",
        )
        assert rc == 1


class TestClaimHelpers:
    """Unit tests for claim helper functions."""

    def test_find_jsonl_no_projects_dir(self, home: Path) -> None:
        """_find_jsonl returns None when .claude/projects doesn't exist."""
        # Remove the projects dir
        import shutil

        from croam.commands.claim import _find_jsonl

        shutil.rmtree(home / ".claude" / "projects")
        assert _find_jsonl(home, "any-sid") is None

    def test_count_lines_empty_file(self, home: Path) -> None:
        """_count_lines returns 0 for empty file."""
        from croam.commands.claim import _count_lines

        f = home / "empty.jsonl"
        f.write_bytes(b"")
        assert _count_lines(f) == 0

    def test_count_lines_no_trailing_newline(self, home: Path) -> None:
        """_count_lines handles file without trailing newline."""
        from croam.commands.claim import _count_lines

        f = home / "notrail.jsonl"
        f.write_bytes(b"line1\nline2")
        assert _count_lines(f) == 2


class TestClaimSessionNotFound:
    """Claim for unknown sid raises SessionNotFound."""

    def test_unknown_sid_raises(
        self, home: Path, state_root: Path, _config_file: Path
    ) -> None:
        from croam.commands.claim import run
        from croam.errors import SessionNotFound

        with pytest.raises(SessionNotFound):
            run(
                "nonexistent-sid",
                state_root=state_root,
                hostname="stormtree",
                home=home,
                config_path=home / ".config" / "croam" / "config.toml",
            )
