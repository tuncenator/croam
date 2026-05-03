"""Tests for src/croam/commands/attach.py via the CLI surface."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from croam.cli import app


@pytest.fixture
def runner():
    return CliRunner()


def _write_config(home: Path, hostname: str = "stormtree", extra_hosts: str = "") -> Path:
    cfg = home / ".config" / "croam" / "config.toml"
    content = f'[self]\nhostname = "{hostname}"\n\n[hosts.{hostname}]\nssh = "{hostname}"\n'
    if extra_hosts:
        content += extra_hosts
    cfg.write_text(content)
    return cfg


def _seed_local_assertion(home: Path, state_root: Path, cwd: Path, owner: str = "stormtree") -> str:
    """Create a synthetic JSONL + local assertion, return sid."""
    from tests._helpers.synth_assertions import build_assertion, write_assertions_file
    from tests._helpers.synth_jsonl import build_jsonl

    sid = str(uuid.uuid4())
    build_jsonl(home, sid, cwd)

    assertion = build_assertion(
        sid,
        owner,
        datetime.now(UTC),
        cwd_normalized=f"~/{cwd.relative_to(home)}" if cwd.is_relative_to(home) else str(cwd),
    )

    ownership_path = state_root / owner / "ownership.json"
    existing = {}
    if ownership_path.exists():
        from croam.ownership import read_local_assertions

        existing = dict(read_local_assertions(state_root, owner))
    existing[sid] = assertion
    write_assertions_file(state_root, owner, existing)
    return sid


# ---------------------------------------------------------------------------
# test_attach_local_session_running
# ---------------------------------------------------------------------------


def test_attach_local_session_running(
    home: Path, state_root: Path, runner, tmux_socket: Path, monkeypatch: pytest.MonkeyPatch
):
    """Pre-create tmux session; --no-exec -> tmux-attach plan."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    sid = _seed_local_assertion(home, state_root, cwd)

    session_name = f"claude-{sid}"
    subprocess.run(
        ["tmux", "-S", str(tmux_socket), "new-session", "-d", "-s", session_name, "sleep", "30"],
        check=True,
    )
    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    result = runner.invoke(app, ["attach", sid, "--no-exec"])
    subprocess.run(
        ["tmux", "-S", str(tmux_socket), "kill-session", "-t", session_name], check=False
    )

    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["action"] == "tmux-attach"
    assert "attach" in plan["argv"]
    assert f"claude-{sid}" in plan["argv"]


# ---------------------------------------------------------------------------
# test_attach_local_session_archived
# ---------------------------------------------------------------------------


def test_attach_local_session_archived(
    home: Path, state_root: Path, runner, tmux_socket: Path, monkeypatch: pytest.MonkeyPatch
):
    """No pre-existing tmux -> tmux-new-and-attach plan with correct argv tail."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    sid = _seed_local_assertion(home, state_root, cwd)

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    result = runner.invoke(app, ["attach", sid, "--no-exec"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["action"] == "tmux-new-and-attach"
    argv = plan["argv"]
    # Tail must be: new-session -A -s claude-<sid> claude-real --resume <sid>
    assert "new-session" in argv
    assert "-A" in argv
    assert f"claude-{sid}" in argv
    assert "claude-real" in argv
    assert "--resume" in argv
    assert sid in argv


# ---------------------------------------------------------------------------
# test_attach_remote_reachable
# ---------------------------------------------------------------------------


def test_attach_remote_reachable(
    home: Path,
    state_root: Path,
    runner,
    ssh_shim,
    tmux_socket: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """ssh_shim ok -> ssh-recurse plan with --here-on-owner."""
    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\n'
    _write_config(home, extra_hosts=cfg_extra)

    cwd = home / "proj"
    cwd.mkdir(parents=True)

    # Seed assertion owned by vicar.
    from tests._helpers.synth_assertions import build_assertion, write_assertions_file

    sid = str(uuid.uuid4())
    assertion = build_assertion(sid, "vicar", datetime.now(UTC), cwd_normalized="~/proj")
    (state_root / "vicar").mkdir(parents=True, exist_ok=True)
    write_assertions_file(state_root, "vicar", {sid: assertion})

    # SSH probe -> reachable
    ssh_shim.register("vicar", ["true"], exit_code=0)

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    result = runner.invoke(app, ["attach", sid, "--no-exec"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["action"] == "ssh-recurse"
    assert "vicar" in plan["argv"]
    assert "attach" in plan["argv"]
    assert "--here-on-owner" in plan["argv"]


# ---------------------------------------------------------------------------
# test_attach_remote_unreachable
# ---------------------------------------------------------------------------


def test_attach_remote_unreachable(
    home: Path, state_root: Path, ssh_shim, monkeypatch: pytest.MonkeyPatch
):
    """ssh_shim fails -> exit 2, stderr has 'origin vicar unreachable' and 'croam peek'."""
    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\n'
    _write_config(home, extra_hosts=cfg_extra)

    from tests._helpers.synth_assertions import build_assertion, write_assertions_file

    sid = str(uuid.uuid4())
    assertion = build_assertion(sid, "vicar", datetime.now(UTC), cwd_normalized="~/proj")
    (state_root / "vicar").mkdir(parents=True, exist_ok=True)
    write_assertions_file(state_root, "vicar", {sid: assertion})

    ssh_shim.register("vicar", ["true"], exit_code=1)

    import sys

    proc = subprocess.run(
        [sys.executable, "-c", "from croam.cli import main; main()", "attach", sid],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "HOME": str(home)},
    )
    assert proc.returncode == 2
    assert "vicar" in proc.stderr.lower() or "unreachable" in proc.stderr.lower()
    assert "peek" in proc.stderr


# ---------------------------------------------------------------------------
# test_attach_recursion_guard
# ---------------------------------------------------------------------------


def test_attach_recursion_guard(
    home: Path, state_root: Path, runner, tmux_socket: Path, monkeypatch: pytest.MonkeyPatch
):
    """--here-on-owner: ownership says vicar but action starts with 'tmux-' not 'ssh-recurse'."""
    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\n'
    _write_config(home, extra_hosts=cfg_extra)

    from tests._helpers.synth_assertions import build_assertion, write_assertions_file

    sid = str(uuid.uuid4())
    assertion = build_assertion(sid, "vicar", datetime.now(UTC), cwd_normalized="~/proj")
    (state_root / "vicar").mkdir(parents=True, exist_ok=True)
    write_assertions_file(state_root, "vicar", {sid: assertion})

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    result = runner.invoke(app, ["attach", sid, "--here-on-owner", "--no-exec"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["action"].startswith("tmux-"), f"expected tmux-*, got {plan['action']!r}"


# ---------------------------------------------------------------------------
# test_attach_sid_not_found
# ---------------------------------------------------------------------------


def test_attach_sid_not_found(home: Path, state_root: Path):
    """No assertion -> exit 2, 'not found' in stderr."""
    _write_config(home)
    sid = str(uuid.uuid4())

    import sys

    proc = subprocess.run(
        [sys.executable, "-c", "from croam.cli import main; main()", "attach", sid],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "HOME": str(home)},
    )
    assert proc.returncode == 2
    assert "not found" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# test_attach_picker_fallback
# ---------------------------------------------------------------------------


def test_attach_picker_fallback(
    home: Path, state_root: Path, runner, monkeypatch: pytest.MonkeyPatch
):
    """No sid -> delegates to run_picker; monkeypatched to return 42 -> exit 42."""
    _write_config(home)
    monkeypatch.setattr("croam.commands.default.run_picker", lambda **kw: 42)
    result = runner.invoke(app, ["attach"])
    assert result.exit_code == 42
