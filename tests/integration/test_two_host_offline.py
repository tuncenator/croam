"""Integration: forced claim when vicar is unreachable.

When the origin host does not respond to the SSH probe, the claim state machine
asks for confirmation. We exercise both acceptance (forced claim proceeds) and
refusal (returns 1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from tests._helpers.synth_assertions import build_assertion, write_assertions_file
from tests._helpers.synth_jsonl import build_jsonl
from tests.integration.conftest import TwoHostEnv


class TestForcedClaimVicarUnreachable:
    """claim_verify=ssh-strict with origin unreachable -> force prompt."""

    def test_forced_claim_accepted(self, two_host_env: TwoHostEnv, two_host_ssh) -> None:
        """User accepts forced claim: assertion written, returns 0."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        st = two_host_env.stormtree
        sid = str(uuid.uuid4())
        cwd = st.home / "forced"
        cwd.mkdir(parents=True)
        build_jsonl(st.home, sid, cwd, n_user=2)

        t = datetime.now(UTC) - timedelta(hours=3)
        write_assertions_file(
            st.state_root,
            "vicar",
            {sid: build_assertion(sid, "vicar", t, cwd_normalized="~/forced")},
        )

        # vicar unreachable: exit 255 for probe.
        two_host_ssh.register("vicar", ["true"], exit_code=255)

        with patch("builtins.input", return_value="y"):
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

    def test_forced_claim_refused(self, two_host_env: TwoHostEnv, two_host_ssh) -> None:
        """User refuses forced claim: returns 1, no assertion written."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        st = two_host_env.stormtree
        sid = str(uuid.uuid4())
        cwd = st.home / "refused"
        cwd.mkdir(parents=True)
        build_jsonl(st.home, sid, cwd)

        t = datetime.now(UTC) - timedelta(hours=1)
        write_assertions_file(
            st.state_root,
            "vicar",
            {sid: build_assertion(sid, "vicar", t, cwd_normalized="~/refused")},
        )

        two_host_ssh.register("vicar", ["true"], exit_code=255)

        with patch("builtins.input", return_value="n"):
            rc = run(
                sid,
                state_root=st.state_root,
                hostname="stormtree",
                home=st.home,
                config_path=st.config_path,
            )

        assert rc == 1
        # No claim assertion should be written.
        local = read_local_assertions(st.state_root, "stormtree")
        assert sid not in local

    def test_forced_claim_eof_input_refuses(self, two_host_env: TwoHostEnv, two_host_ssh) -> None:
        """EOFError from input() (non-interactive) is treated as refusal."""
        from croam.commands.claim import run

        st = two_host_env.stormtree
        sid = str(uuid.uuid4())
        cwd = st.home / "eof-test"
        cwd.mkdir(parents=True)
        build_jsonl(st.home, sid, cwd)

        t = datetime.now(UTC)
        write_assertions_file(
            st.state_root,
            "vicar",
            {sid: build_assertion(sid, "vicar", t, cwd_normalized="~/eof-test")},
        )

        two_host_ssh.register("vicar", ["true"], exit_code=255)

        with patch("builtins.input", side_effect=EOFError):
            rc = run(
                sid,
                state_root=st.state_root,
                hostname="stormtree",
                home=st.home,
                config_path=st.config_path,
            )

        assert rc == 1


class TestLocalVerifyModeOffline:
    """claim_verify=local skips SSH probe entirely."""

    def _write_local_config(self, st_home, state_root) -> None:
        cfg = st_home / ".config" / "croam" / "config.toml"
        cfg.write_text(
            '[self]\nhostname = "stormtree"\n\n'
            '[hosts.stormtree]\nssh = "stormtree"\nsync = false\n\n'
            '[hosts.vicar]\nssh = "vicar"\nsync = false\n\n'
            "[storage]\n"
            f'state_root = "{state_root}"\n\n'
            '[discovery]\nmode = "ssh"\n\n'
            '[ownership]\nclaim_verify = "local"\n\n'
            '[picker]\ndefault_filter = "exact-pwd"\nlast_window_days = 30\n\n'
            "[shim]\nenabled = false\n"
            'opt_out_env = "CROAM_NO_TMUX"\n'
        )

    def test_local_verify_no_ssh_probe(self, two_host_env: TwoHostEnv) -> None:
        """local verify mode claims without any SSH call (no shim registered)."""
        from croam.commands.claim import run
        from croam.ownership import read_local_assertions

        st = two_host_env.stormtree
        self._write_local_config(st.home, st.state_root)

        sid = str(uuid.uuid4())
        cwd = st.home / "local-claim"
        cwd.mkdir(parents=True)
        build_jsonl(st.home, sid, cwd)

        t = datetime.now(UTC)
        write_assertions_file(
            st.state_root,
            "vicar",
            {sid: build_assertion(sid, "vicar", t, cwd_normalized="~/local-claim")},
        )

        # No ssh_shim registered -> if SSH is called, test will error (fixture unset).
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
