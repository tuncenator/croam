"""Smoke tests: exercise every fixture and verify harness contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from loguru import logger

from croam import log
from croam.errors import (
    ConfigError,
    CroamError,
    OrphanRefused,
    OwnershipConflict,
    SessionNotFound,
    SshError,
    TmuxError,
)
from croam.errors import TimeoutError as CroamTimeoutError
from croam.proc import run as proc_run
from tests._helpers.synth_jsonl import build_jsonl
from tests._helpers.synth_session import build_session_metadata

# ---------------------------------------------------------------------------
# Fixture tests
# ---------------------------------------------------------------------------


def test_home_redirect(home: Path) -> None:
    assert os.environ["HOME"] == str(home)
    assert (home / ".claude" / "projects").is_dir()
    assert (home / ".claude" / "sessions").is_dir()
    assert (home / ".config" / "croam").is_dir()
    assert (home / ".local" / "share" / "croam").is_dir()
    assert (home / ".local" / "state" / "croam").is_dir()
    assert (home / "Sync" / "croam").is_dir()


def test_tmux_socket_path_resolves(home: Path, tmux_socket: Path) -> None:
    assert tmux_socket.parent.is_dir()
    assert not tmux_socket.exists()


def test_state_root_has_default_hosts(state_root: Path) -> None:
    assert (state_root / "stormtree").is_dir()
    assert (state_root / "vicar").is_dir()
    assert (state_root / "corpsefire").is_dir()


# ---------------------------------------------------------------------------
# SSH shim tests
# ---------------------------------------------------------------------------


def test_ssh_shim_basic(ssh_shim, home: Path) -> None:
    ssh_shim.register("ok", ["true"], stdout="", exit_code=0)
    cp = proc_run(["ssh", "-o", "BatchMode=yes", "ok", "true"])
    assert cp.returncode == 0
    assert cp.stdout == ""


def test_ssh_shim_with_args(ssh_shim, home: Path) -> None:
    ssh_shim.register("vicar", ["echo", "hello"], stdout="hello\n", exit_code=0)
    cp = proc_run(["ssh", "-o", "BatchMode=yes", "vicar", "echo", "hello"])
    assert cp.returncode == 0
    assert cp.stdout == "hello\n"


def test_ssh_shim_failure(ssh_shim, home: Path) -> None:
    ssh_shim.register("dead", ["true"], stderr="connection refused\n", exit_code=255)
    cp = proc_run(["ssh", "-o", "BatchMode=yes", "dead", "true"])
    assert cp.returncode == 255
    assert "connection refused" in cp.stderr


# ---------------------------------------------------------------------------
# Synth helper tests
# ---------------------------------------------------------------------------


def test_synth_jsonl(home: Path) -> None:
    path = build_jsonl(home, "abc-123", Path("/tmp/foo"), n_user=2)
    assert path.exists()
    lines = [json.loads(line) for line in path.read_text().strip().split("\n")]
    assert len(lines) == 4  # last-prompt + permission-mode + 2 user
    assert lines[2]["sessionId"] == "abc-123"
    assert path.parent.name == "-tmp-foo"


def test_synth_session(home: Path) -> None:
    path = build_session_metadata(home, 99999, "abc-123", Path("/tmp/foo"), status="busy")
    data = json.loads(path.read_text())
    assert data["pid"] == 99999
    assert data["sessionId"] == "abc-123"
    assert data["status"] == "busy"
    assert data["cwd"] == "/tmp/foo"


# ---------------------------------------------------------------------------
# Log tests
# ---------------------------------------------------------------------------


def test_log_configure_default(home: Path) -> None:
    log.configure()
    logger.info("smoke-test-line")


def test_log_configure_with_file(home: Path) -> None:
    log_path = home / ".local" / "state" / "croam" / "croam.log"
    log.configure(level="DEBUG", log_file=log_path, debug=True)
    logger.info("file-sink-line")
    logger.complete()
    assert log_path.exists()
    content = log_path.read_text()
    assert "file-sink-line" in content
    # Verify the line is JSON-serialized
    first_line = content.strip().split("\n")[0]
    record = json.loads(first_line)
    assert "record" in record
    assert record["record"]["message"] == "file-sink-line"


# ---------------------------------------------------------------------------
# Errors tests
# ---------------------------------------------------------------------------


def test_errors_import(home: Path) -> None:
    assert issubclass(CroamError, Exception)
    for cls in (
        ConfigError,
        SshError,
        OwnershipConflict,
        TmuxError,
        SessionNotFound,
        OrphanRefused,
        CroamTimeoutError,
    ):
        assert issubclass(cls, CroamError)


# ---------------------------------------------------------------------------
# Proc tests
# ---------------------------------------------------------------------------


def test_proc_run_basic(home: Path) -> None:
    cp = proc_run(["true"])
    assert cp.returncode == 0
    cp = proc_run(["false"])
    assert cp.returncode == 1


def test_proc_run_timeout(home: Path) -> None:
    with pytest.raises(CroamTimeoutError):
        proc_run(["sleep", "5"], timeout=0.1)


# ---------------------------------------------------------------------------
# Safety guard logic test
# ---------------------------------------------------------------------------


def test_safety_guard_logic(home: Path) -> None:
    from tests.conftest import _check_home_redirected

    # Should pass: tmp path
    _check_home_redirected("/tmp/foo", None)
    # Should pass: e2e bypass
    _check_home_redirected("/home/tunc/something", "1")

    # Should fail: real home, no e2e
    with pytest.raises(pytest.fail.Exception):
        _check_home_redirected("/home/tunc", None)
    # Should fail: None home
    with pytest.raises(pytest.fail.Exception):
        _check_home_redirected(None, None)
    # Should fail: empty home
    with pytest.raises(pytest.fail.Exception):
        _check_home_redirected("", None)
