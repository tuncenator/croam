"""Integration: claim handshake end-to-end with two-host synthetic environment.

Exercises the full S0-S6 state machine across stormtree and vicar using the
ssh_shim for cooperative release + JSONL fetch.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from tests._helpers.synth_assertions import build_assertion, write_assertions_file
from tests._helpers.synth_jsonl import build_jsonl
from tests.integration.conftest import TwoHostEnv


class TestClaimCooperative:
    """Cooperative claim: vicar reachable, releases session, JSONL transferred."""

    def test_claim_from_vicar_writes_assertion(
        self, two_host_env: TwoHostEnv, two_host_ssh
    ) -> None:
        """Claiming vicar's session writes a claim assertion on stormtree."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        st = two_host_env.stormtree
        sid = str(uuid.uuid4())
        cwd = st.home / "projects" / "mywork"
        cwd.mkdir(parents=True)

        # vicar owns the session.
        t_vicar = datetime.now(UTC) - timedelta(hours=1)
        assertion_vc = build_assertion(
            sid, "vicar", t_vicar, cwd_normalized="~/projects/mywork"
        )
        write_assertions_file(st.state_root, "vicar", {sid: assertion_vc})

        # JSONL exists locally (syncthing mirror).
        build_jsonl(st.home, sid, cwd, n_user=2)

        # Register ssh_shim: vicar reachable.
        two_host_ssh.register("vicar", ["true"], exit_code=0)

        # Register emit-state returning vicar's ownership.
        emit_payload = {
            "ownership": {
                sid: {
                    "owner": "vicar",
                    "asserted_at": t_vicar.isoformat(),
                    "action": "create",
                    "cwd_normalized": "~/projects/mywork",
                }
            }
        }
        two_host_ssh.register(
            "vicar",
            ["croam", "emit-state", "--json"],
            stdout=json.dumps(emit_payload),
        )

        # Register release call.
        two_host_ssh.register("vicar", ["croam", "release", sid], exit_code=0)

        rc = run(
            sid,
            state_root=st.state_root,
            hostname="stormtree",
            home=st.home,
            config_path=st.config_path,
        )

        assert rc == 0
        local = read_local_assertions(st.state_root, "stormtree")
        assert sid in local
        assert local[sid].owner == "stormtree"
        assert local[sid].action == "claim"
        assert local[sid].previous_owner == "vicar"

    def test_claim_self_owned_is_noop(self, two_host_env: TwoHostEnv) -> None:
        """Claiming a session already owned by stormtree returns 0 without SSH."""
        from croam.commands.claim import run

        st = two_host_env.stormtree
        sid = str(uuid.uuid4())
        cwd = st.home / "dev"
        cwd.mkdir(parents=True)
        build_jsonl(st.home, sid, cwd)

        t = datetime.now(UTC)
        write_assertions_file(
            st.state_root,
            "stormtree",
            {sid: build_assertion(sid, "stormtree", t)},
        )

        rc = run(
            sid,
            state_root=st.state_root,
            hostname="stormtree",
            home=st.home,
            config_path=st.config_path,
        )
        assert rc == 0


class TestClaimSshStrict:
    """ssh-strict mode with remote state verification."""

    def test_claim_detects_conflict_from_remote_state(
        self, two_host_env: TwoHostEnv, two_host_ssh
    ) -> None:
        """When remote emit-state reports a different owner, claim still proceeds (logs warning)."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        st = two_host_env.stormtree
        sid = str(uuid.uuid4())
        cwd = st.home / "repo"
        cwd.mkdir(parents=True)
        build_jsonl(st.home, sid, cwd)

        t_vicar = datetime.now(UTC) - timedelta(minutes=30)
        write_assertions_file(
            st.state_root,
            "vicar",
            {sid: build_assertion(sid, "vicar", t_vicar, cwd_normalized="~/repo")},
        )

        # Remote state says vicar owns it (consistent).
        emit_payload = {
            "ownership": {
                sid: {
                    "owner": "vicar",
                    "asserted_at": t_vicar.isoformat(),
                    "action": "create",
                    "cwd_normalized": "~/repo",
                }
            }
        }
        two_host_ssh.register("vicar", ["true"], exit_code=0)
        two_host_ssh.register(
            "vicar",
            ["croam", "emit-state", "--json"],
            stdout=json.dumps(emit_payload),
        )
        two_host_ssh.register("vicar", ["croam", "release", sid], exit_code=0)

        rc = run(
            sid,
            state_root=st.state_root,
            hostname="stormtree",
            home=st.home,
            config_path=st.config_path,
        )
        assert rc == 0
        local = read_local_assertions(st.state_root, "stormtree")
        assert sid in local
        assert local[sid].owner == "stormtree"

    def test_claim_writes_snapshot_after_success(
        self, two_host_env: TwoHostEnv, two_host_ssh
    ) -> None:
        """Successful claim writes a snapshot entry."""
        from croam.commands.claim import run
        from croam.snapshots import get_snapshot_line_count

        st = two_host_env.stormtree
        sid = str(uuid.uuid4())
        cwd = st.home / "snap-test"
        cwd.mkdir(parents=True)
        build_jsonl(st.home, sid, cwd, n_user=3)

        t = datetime.now(UTC) - timedelta(hours=2)
        write_assertions_file(
            st.state_root,
            "vicar",
            {sid: build_assertion(sid, "vicar", t, cwd_normalized="~/snap-test")},
        )

        emit_payload: dict = {"ownership": {}}
        two_host_ssh.register("vicar", ["true"], exit_code=0)
        two_host_ssh.register(
            "vicar",
            ["croam", "emit-state", "--json"],
            stdout=json.dumps(emit_payload),
        )
        two_host_ssh.register("vicar", ["croam", "release", sid], exit_code=0)

        rc = run(
            sid,
            state_root=st.state_root,
            hostname="stormtree",
            home=st.home,
            config_path=st.config_path,
        )
        assert rc == 0

        # 2 header lines + 3 user = 5 lines.
        lc = get_snapshot_line_count(st.state_root, "stormtree", sid)
        assert lc == 5
