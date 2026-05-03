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
