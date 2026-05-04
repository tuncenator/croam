"""Tier 2: attach --no-exec against real dummy session at /tmp/croam-e2e/.

Gated on CROAM_E2E=1. Reads the real JSONL in /tmp/croam-e2e and exercises
the attach verb with no_exec=True to verify the action JSON without actually
starting a tmux session.
"""

from __future__ import annotations

import io
import json
import os
import sys

import pytest


@pytest.mark.skipif(not os.environ.get("CROAM_E2E"), reason="Tier 2 only")
class TestE2EDummyAttach:
    """attach --no-exec against the real dummy session."""

    def test_attach_no_exec_emits_action_json(self, e2e_dummy, home) -> None:
        """attach with no_exec=True prints action JSON to stdout, exits 0."""
        from datetime import UTC, datetime

        from croam.commands.attach import run
        from croam.config import load_config
        from croam.ownership import Assertion, write_local_assertion

        _e2e_home, sid = e2e_dummy

        config_path = home / ".config" / "croam" / "config.toml"
        state_root = home / ".local" / "share" / "croam"

        config_path.write_text(
            '[self]\nhostname = "stormtree"\n\n'
            '[hosts.stormtree]\nssh = "stormtree"\nsync = false\n\n'
            "[storage]\n"
            f'state_root = "{state_root}"\n\n'
            '[discovery]\nmode = "ssh"\n\n'
            '[ownership]\nclaim_verify = "local"\n\n'
            '[picker]\ndefault_filter = "exact-pwd"\nlast_window_days = 30\n\n'
            "[shim]\nenabled = false\n"
            'opt_out_env = "CROAM_NO_TMUX"\n'
        )

        (state_root / "stormtree").mkdir(parents=True, exist_ok=True)

        assertion = Assertion(
            sid=sid,
            owner="stormtree",
            asserted_at=datetime.now(UTC),
            action="create",
            cwd_normalized="~/projects/test",
        )
        write_local_assertion(state_root, "stormtree", assertion)

        config = load_config(config_path)
        ctx_obj: dict = {}

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = run(sid, ctx_obj, config, home, no_exec=True)
        finally:
            sys.stdout = old_stdout

        assert rc == 0
        output = captured.getvalue().strip()
        data = json.loads(output)
        assert "action" in data
        assert "argv" in data
        assert data["action"] in ("tmux-attach", "tmux-new-and-attach")

    def test_attach_no_exec_argv_contains_sid(self, e2e_dummy, home) -> None:
        """The emitted argv includes the sid for resume."""
        from datetime import UTC, datetime

        from croam.commands.attach import run
        from croam.config import load_config
        from croam.ownership import Assertion, write_local_assertion

        _e2e_home, sid = e2e_dummy

        config_path = home / ".config" / "croam" / "config.toml"
        state_root = home / ".local" / "share" / "croam"

        config_path.write_text(
            '[self]\nhostname = "stormtree"\n\n'
            '[hosts.stormtree]\nssh = "stormtree"\nsync = false\n\n'
            "[storage]\n"
            f'state_root = "{state_root}"\n\n'
            '[discovery]\nmode = "ssh"\n\n'
            '[ownership]\nclaim_verify = "local"\n\n'
            '[picker]\ndefault_filter = "exact-pwd"\nlast_window_days = 30\n\n'
            "[shim]\nenabled = false\n"
            'opt_out_env = "CROAM_NO_TMUX"\n'
        )

        (state_root / "stormtree").mkdir(parents=True, exist_ok=True)

        assertion = Assertion(
            sid=sid,
            owner="stormtree",
            asserted_at=datetime.now(UTC),
            action="create",
            cwd_normalized="~/projects/test",
        )
        write_local_assertion(state_root, "stormtree", assertion)

        config = load_config(config_path)

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = run(sid, {}, config, home, no_exec=True)
        finally:
            sys.stdout = old_stdout

        assert rc == 0
        data = json.loads(captured.getvalue().strip())
        # The sid appears somewhere in the argv.
        assert sid in data["argv"]
