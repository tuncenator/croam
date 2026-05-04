"""Tests for src/croam/doctor.py -- diagnostic checks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from croam.cli import app
from croam.doctor import (
    DiagnosticResult,
    _format_results,
    check_config,
    check_conflict_files,
    check_external_tools,
    check_state_root_writable,
)


def _write_config(home: Path, *, extra: str = "") -> Path:
    """Write a minimal config.toml under home. Returns config path."""
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        '[self]\nhostname = "stormtree"\n\n'
        '[hosts.stormtree]\nssh = "stormtree"\nsync = false\n\n'
        "[storage]\n"
        f'state_root = "{home / ".local" / "share" / "croam"}"\n\n'
        '[discovery]\nmode = "ssh"\n\n'
        '[ownership]\nclaim_verify = "local"\n\n'
        '[picker]\ndefault_filter = "exact-pwd"\nlast_window_days = 30\n\n'
        "[shim]\nenabled = false\n"
        'opt_out_env = "CROAM_NO_TMUX"\n' + extra
    )
    return cfg


def _write_config_with_peer(
    home: Path, *, peer: str = "vicar", discovery: str = "ssh", sync: bool = False
) -> Path:
    """Write config with self + one peer."""
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        '[self]\nhostname = "stormtree"\n\n'
        '[hosts.stormtree]\nssh = "stormtree"\nsync = false\n\n'
        f'[hosts.{peer}]\nssh = "{peer}"\nsync = {str(sync).lower()}\n\n'
        "[storage]\n"
        f'state_root = "{home / ".local" / "share" / "croam"}"\n\n'
        f'[discovery]\nmode = "{discovery}"\n\n'
        '[ownership]\nclaim_verify = "local"\n\n'
        '[picker]\ndefault_filter = "exact-pwd"\nlast_window_days = 30\n\n'
        "[shim]\nenabled = false\n"
        'opt_out_env = "CROAM_NO_TMUX"\n'
    )
    return cfg


def _mock_proc_run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    """Fake proc.run that returns a version string for any tool."""
    return subprocess.CompletedProcess(argv, 0, stdout=f"{argv[0]} 1.0.0\n", stderr="")


def _mock_tools_ok() -> list[DiagnosticResult]:
    """Return OK results for all external tools."""
    return [
        DiagnosticResult(name=t, level="OK", reason="ok") for t in ("fzf", "tmux", "ssh", "claude")
    ]


# ---------------------------------------------------------------------------
# Unit tests for individual checks
# ---------------------------------------------------------------------------


class TestCheckConfig:
    def test_ok_with_valid_config(self, home: Path) -> None:
        cfg = _write_config(home)
        result = check_config(cfg)
        assert result.level == "OK"
        assert "1 host" in result.reason

    def test_fail_when_missing(self, home: Path) -> None:
        result = check_config(home / "nonexistent.toml")
        assert result.level == "FAIL"


class TestCheckStateRoot:
    def test_ok_when_writable(self, state_root: Path) -> None:
        result = check_state_root_writable(state_root)
        assert result.level == "OK"

    def test_fail_when_missing(self, home: Path) -> None:
        result = check_state_root_writable(home / "nope")
        assert result.level == "FAIL"


class TestCheckExternalTools:
    def test_reports_found_tools(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.proc.run", _mock_proc_run)
        results = check_external_tools()
        assert len(results) == 4
        assert all(r.level == "OK" for r in results)

    def test_fail_when_tool_missing(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda t: None)
        results = check_external_tools()
        assert all(r.level == "FAIL" for r in results)


class TestCheckConflictFiles:
    def test_ok_when_no_conflicts(self, state_root: Path) -> None:
        result = check_conflict_files(state_root)
        assert result.level == "OK"

    def test_fail_when_conflict_found(self, state_root: Path) -> None:
        conflict = state_root / "vicar" / "ownership.sync-conflict-20260430-100000-XYZ.json"
        conflict.parent.mkdir(parents=True, exist_ok=True)
        conflict.write_text("{}")
        result = check_conflict_files(state_root)
        assert result.level == "FAIL"
        assert result.detail is not None
        assert "sync-conflict" in result.detail


# ---------------------------------------------------------------------------
# Formatter tests
# ---------------------------------------------------------------------------


class TestFormatResults:
    def test_aligns_columns(self, home: Path) -> None:
        results = [
            DiagnosticResult(name="config", level="OK", reason="present"),
            DiagnosticResult(name="ownership", level="WARN", reason="1 tie"),
        ]
        out = _format_results(results, started_at=datetime(2026, 4, 30, 14, 30, tzinfo=UTC))
        assert "[OK]" in out
        assert "[WARN]" in out
        assert "croam doctor (2026-04-30T14:30Z)" in out

    def test_summary_line(self, home: Path) -> None:
        results = [
            DiagnosticResult(name="config", level="OK", reason="ok"),
            DiagnosticResult(name="state_root", level="FAIL", reason="missing"),
        ]
        out = _format_results(results, started_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC))
        assert "Summary: 0 warnings, 1 failure" in out


# ---------------------------------------------------------------------------
# Integration tests via CLI runner
# ---------------------------------------------------------------------------


class TestDoctorCli:
    def test_doctor_clean_setup(
        self,
        home: Path,
        state_root: Path,
        ssh_shim,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Clean fixture: exit 0, no FAIL."""
        _write_config(home)
        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.proc.run", _mock_proc_run)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "[FAIL]" not in result.stdout
        assert "[OK]" in result.stdout
        assert "Summary: 0 warnings, 0 failures" in result.stdout

    def test_doctor_missing_config_bootstraps(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No config.toml: doctor bootstraps and proceeds."""
        config_path = home / ".config" / "croam" / "config.toml"
        assert not config_path.exists()
        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.proc.run", _mock_proc_run)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        assert config_path.exists()
        assert "bootstrapped" in result.stdout.lower()

    def test_doctor_unreachable_host(
        self,
        home: Path,
        state_root: Path,
        ssh_shim,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unreachable peer: WARN, exit 0."""
        _write_config_with_peer(home, peer="vicar")
        monkeypatch.setattr("croam.doctor.check_external_tools", _mock_tools_ok)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "[WARN]" in result.stdout
        assert "vicar" in result.stdout

    def test_doctor_conflict_file_detected(
        self,
        home: Path,
        state_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Conflict file present: FAIL, exit 1."""
        _write_config(home)
        conflict = state_root / "vicar" / "ownership.sync-conflict-20260430-100000-XYZ.json"
        conflict.parent.mkdir(parents=True, exist_ok=True)
        conflict.write_text("{}")
        monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
        monkeypatch.setattr("croam.proc.run", _mock_proc_run)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        assert "[FAIL]" in result.stdout
        assert "sync-conflict" in result.stdout

    def test_doctor_stale_syncthing_warns(
        self,
        home: Path,
        state_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Peer mirror 2h old: WARN, exit 0."""
        _write_config_with_peer(home, peer="vicar", discovery="syncthing", sync=True)
        peer = state_root / "vicar"
        peer.mkdir(parents=True, exist_ok=True)
        f = peer / "ownership.json"
        f.write_text("{}")
        two_hours_ago = time.time() - 7200
        os.utime(f, (two_hours_ago, two_hours_ago))
        monkeypatch.setattr("croam.doctor.check_external_tools", _mock_tools_ok)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "[WARN]" in result.stdout

    def test_doctor_very_stale_syncthing_fails(
        self,
        home: Path,
        state_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """48h stale mirror: FAIL, exit 1."""
        _write_config_with_peer(home, peer="vicar", discovery="syncthing", sync=True)
        peer = state_root / "vicar"
        peer.mkdir(parents=True, exist_ok=True)
        f = peer / "ownership.json"
        f.write_text("{}")
        very_old = time.time() - 86400 * 2
        os.utime(f, (very_old, very_old))
        monkeypatch.setattr("croam.doctor.check_external_tools", _mock_tools_ok)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 1
        assert "[FAIL]" in result.stdout

    def test_doctor_outclaim_detected(
        self,
        home: Path,
        state_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two hosts assert same sid with same timestamp: WARN."""
        _write_config_with_peer(home, peer="vicar")
        sid = "tied-sid"
        ts = "2026-04-30T10:00:00+00:00"
        for hostname in ("stormtree", "vicar"):
            peer = state_root / hostname
            peer.mkdir(parents=True, exist_ok=True)
            (peer / "ownership.json").write_text(
                json.dumps(
                    {
                        sid: {
                            "owner": hostname,
                            "asserted_at": ts,
                            "action": "create",
                            "cwd_normalized": "~/foo",
                        }
                    }
                )
            )
        monkeypatch.setattr("croam.doctor.check_external_tools", _mock_tools_ok)

        runner = CliRunner()
        result = runner.invoke(app, ["doctor"])
        assert "[WARN]" in result.stdout
        assert sid in result.stdout
