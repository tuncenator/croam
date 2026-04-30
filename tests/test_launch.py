"""Integration tests for src/croam/commands/launch.py -- uses --no-exec mode."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from croam import tmux
from croam.commands.launch import build_launch_plan, launch_cmd
from croam.config import (
    Config,
    DiscoveryConfig,
    OwnershipConfig,
    PickerConfig,
    ShimConfig,
    StorageConfig,
)
from croam.errors import TmuxError


def _make_fake_claude(tmp_path: Path) -> Path:
    """Drop a fake `claude` binary on PATH so find_claude_real() succeeds."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "claude"
    fake.write_text("#!/bin/sh\necho fake-claude $@\n")
    fake.chmod(0o755)
    return fake


def _make_config(home: Path, state_root: Path, hostname: str = "stormtree") -> Config:
    """Construct a minimal Config for tests using Phase 2's nested Config."""
    return Config(
        self_hostname=hostname,
        hosts={},
        storage=StorageConfig(state_root=state_root),
        discovery=DiscoveryConfig(mode="ssh"),
        ownership=OwnershipConfig(claim_verify="local"),
        picker=PickerConfig(default_filter="exact-pwd", last_window_days=30),
        shim=ShimConfig(enabled=True, opt_out_env="CROAM_NO_TMUX"),
    )


def test_build_launch_plan_wrap_path(home, tmp_path, monkeypatch):
    """Default invocation in a TTY shell, not in tmux, returns mode='wrap'."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude", "--effort", "max"],
        env={"HOME": str(home)},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
        sock=None,
    )
    assert plan.mode == "wrap"
    uuid.UUID(plan.sid)  # valid uuid4
    assert plan.tmux_session_name == f"claude-{plan.sid}"
    assert plan.tmux_new_argv[:6] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        f"claude-{plan.sid}",
        "--",
    ]
    assert plan.tmux_new_argv[6] == str(fake_claude)
    assert plan.tmux_new_argv[7:] == ["--effort", "max"]
    assert plan.tmux_attach_argv == ["tmux", "attach", "-t", f"claude-{plan.sid}"]


def test_build_launch_plan_passthrough_in_tmux(home, tmp_path, monkeypatch):
    """If TMUX env var is set, mode is 'passthrough'."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude"],
        env={"HOME": str(home), "TMUX": "/tmp/tmux-1000/default,123,4"},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
    )
    assert plan.mode == "passthrough"
    assert plan.passthrough_argv == [str(fake_claude)]
    assert plan.tmux_new_argv is None


def test_build_launch_plan_passthrough_print_flag(home, tmp_path, monkeypatch):
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude", "--print", "say hi"],
        env={"HOME": str(home)},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
    )
    assert plan.mode == "passthrough"


def test_build_launch_plan_resume_uses_provided_sid(home, tmp_path, monkeypatch):
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude", "--resume", "ff7afd8a-ea17-4183-a131-566e7bcb0758"],
        env={"HOME": str(home)},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
    )
    assert plan.sid == "ff7afd8a-ea17-4183-a131-566e7bcb0758"
    assert plan.tmux_session_name == "claude-ff7afd8a-ea17-4183-a131-566e7bcb0758"


def test_build_launch_plan_strips_no_tmux(home, tmp_path, monkeypatch):
    """When --no-tmux is in argv, mode is passthrough AND --no-tmux is stripped."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude", "--no-tmux", "--effort", "max"],
        env={"HOME": str(home)},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
    )
    assert plan.mode == "passthrough"
    assert "--no-tmux" not in (plan.passthrough_argv or [])
    assert plan.passthrough_argv == [str(fake_claude), "--effort", "max"]


def test_launch_cmd_no_exec_writes_assertion(home, tmp_path, capsys, monkeypatch):
    """launch_cmd in --no-exec mode prints the plan AND writes the assertion."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    state_root = tmp_path / "state"
    state_root.mkdir()
    config = _make_config(home=home, state_root=state_root)

    rc = launch_cmd(
        argv=["claude"],
        config=config,
        home=home,
        cwd=home,
        env={"HOME": str(home)},
        stdin_isatty=True,
        no_exec=True,
    )
    assert rc == 0

    captured = capsys.readouterr()
    plan_dict = json.loads(captured.out)
    assert plan_dict["mode"] == "wrap"
    sid = plan_dict["sid"]
    uuid.UUID(sid)

    # Verify ownership.json was written.
    ownership_path = state_root / "stormtree" / "ownership.json"
    assert ownership_path.exists()
    data = json.loads(ownership_path.read_text())
    assert sid in data
    assert data[sid]["action"] == "create"
    assert data[sid]["owner"] == "stormtree"


def test_launch_cmd_real_tmux(home, tmux_socket, tmp_path, monkeypatch):
    """Full integration: launch_cmd creates a real tmux session on the private socket.

    We avoid execvp by patching tmux.attach to a no-op.
    """
    fake_claude = _make_fake_claude(tmp_path)
    # Prepend bindir so find_claude_real() finds the fake, but tmux stays reachable.
    monkeypatch.setenv("PATH", f"{fake_claude.parent}:{os.environ.get('PATH', '')}")
    state_root = tmp_path / "state"
    state_root.mkdir()
    config = _make_config(home=home, state_root=state_root)

    attach_calls: list[tuple] = []
    monkeypatch.setattr(tmux, "attach", lambda *a, **kw: attach_calls.append((a, kw)))

    # AssertionError("attach returned") will fire because our patched attach
    # actually returns. Catch it and verify the side effects.
    with pytest.raises(AssertionError, match="attach returned"):
        launch_cmd(
            argv=["claude"],
            config=config,
            home=home,
            cwd=home,
            env={"HOME": str(home)},
            stdin_isatty=True,
            sock=tmux_socket,
            no_exec=False,
        )

    assert len(attach_calls) == 1
    sessions = tmux.list_sessions(sock=tmux_socket)
    names = [n for n, _ in sessions]
    assert any(n.startswith("claude-") for n in names)
    # Cleanup
    for n, _ in sessions:
        tmux.kill_session(n, sock=tmux_socket)


def test_assertion_persists_on_tmux_failure(home, tmux_socket, tmp_path, monkeypatch):
    """Assertion-before-side-effect: assertion stays on disk even when tmux fails."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    state_root = tmp_path / "state"
    state_root.mkdir()
    config = _make_config(home=home, state_root=state_root)

    def _raise_tmux(*a, **kw):
        raise TmuxError("injected tmux failure")

    monkeypatch.setattr(tmux, "new_session_detached", _raise_tmux)

    with pytest.raises(TmuxError, match="injected tmux failure"):
        launch_cmd(
            argv=["claude"],
            config=config,
            home=home,
            cwd=home,
            env={"HOME": str(home)},
            stdin_isatty=True,
            sock=tmux_socket,
            no_exec=False,
        )

    # Assertion must be present even though tmux failed.
    ownership_path = state_root / "stormtree" / "ownership.json"
    assert ownership_path.exists(), "ownership.json must exist after tmux failure"
    data = json.loads(ownership_path.read_text())
    assert len(data) == 1
    sid = next(iter(data))
    assert data[sid]["action"] == "create"
