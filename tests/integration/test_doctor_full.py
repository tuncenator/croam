"""Integration: doctor full run with two-host environment.

Exercises run_doctor() end-to-end:
- Clean setup returns exit 0, no FAIL.
- Conflict file causes exit 1 with FAIL in output.
"""

from __future__ import annotations

import subprocess

import pytest

from tests.integration.conftest import TwoHostEnv


def _mock_proc_run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    """Fake proc.run returning version string for any tool."""
    return subprocess.CompletedProcess(argv, 0, stdout=f"{argv[0]} 1.0.0\n", stderr="")


class TestDoctorFullRun:
    """run_doctor() end-to-end with synthetic two-host env."""

    def test_clean_setup_exits_zero(
        self, two_host_env: TwoHostEnv, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Clean config + writable state_root + no conflicts -> exit 0, no FAIL."""
        from croam.doctor import run_doctor

        st = two_host_env.stormtree
        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.proc.run", _mock_proc_run)

        rc = run_doctor(st.config_path, st.home)
        assert rc == 0

    def test_conflict_file_exits_one(
        self, two_host_env: TwoHostEnv, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Syncthing conflict file present -> exit 1, FAIL in output."""
        from croam.doctor import run_doctor

        st = two_host_env.stormtree
        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.proc.run", _mock_proc_run)

        conflict = st.state_root / "vicar" / "ownership.sync-conflict-20260501-120000-ABC.json"
        conflict.write_text("{}")

        rc = run_doctor(st.config_path, st.home)
        assert rc == 1
        captured = capsys.readouterr()
        assert "[FAIL]" in captured.out
        assert "sync-conflict" in captured.out

    def test_summary_line_present(
        self, two_host_env: TwoHostEnv, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Doctor output always includes a Summary line."""
        from croam.doctor import run_doctor

        st = two_host_env.stormtree
        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.proc.run", _mock_proc_run)

        run_doctor(st.config_path, st.home)
        captured = capsys.readouterr()
        assert "Summary:" in captured.out

    def test_missing_config_bootstraps(
        self, two_host_env: TwoHostEnv, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """No config.toml: doctor bootstraps and creates file."""
        from croam.doctor import run_doctor

        st = two_host_env.stormtree
        # Remove the config file.
        st.config_path.unlink()
        assert not st.config_path.exists()

        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.proc.run", _mock_proc_run)

        run_doctor(st.config_path, st.home)
        assert st.config_path.exists()

    def test_unreachable_peer_warns_not_fails(
        self, two_host_env: TwoHostEnv, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Unreachable peer -> WARN only, exit 0."""
        from croam.doctor import run_doctor

        st = two_host_env.stormtree
        # Don't register vicar as reachable in the ssh_shim -> it'll fail.
        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.doctor.check_external_tools", lambda: [])

        rc = run_doctor(st.config_path, st.home)
        assert rc == 0
        captured = capsys.readouterr()
        assert "[WARN]" in captured.out
