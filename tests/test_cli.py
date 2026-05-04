"""Tests for src/croam/cli.py.

Phase 6: 6 tests covering help output, hidden command, emit-state wiring,
debug flag wiring, top-level CroamError -> typer.Exit(2) handler, and
cmd_launch config plumbing.
"""

from __future__ import annotations

import json
import re
import sys

import pytest
from typer.testing import CliRunner

from croam.cli import app


@pytest.fixture
def runner():
    return CliRunner()


def test_help_shows_verbs(home, runner):
    """--help lists all public verbs."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = result.output
    for verb in ("ls", "attach", "peek", "claim", "fork", "launch", "doctor"):
        assert re.search(rf"\b{verb}\b", out), f"verb {verb!r} missing from --help: {out!r}"


def test_help_does_not_show_emit_state(home, runner):
    """--help must NOT show the hidden emit-state verb."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "emit-state" not in result.output


def test_emit_state_runs(home, state_root, runner, monkeypatch):
    """Phase 3 owns emit_state. Phase 6 verifies wiring through cli."""
    # Write a minimal config so load_config works.
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.write_text('[self]\nhostname = "stormtree"\n\n[hosts.stormtree]\nssh = "stormtree"\n')
    result = runner.invoke(app, ["emit-state"])
    assert result.exit_code == 0, f"output: {result.output}"
    payload = json.loads(result.output)
    assert isinstance(payload, dict)


def test_global_debug_flag(home, state_root, runner):
    """--debug bumps logging level; ls now works (Phase 7 replaced Phase 6 stub)."""
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.write_text('[self]\nhostname = "stormtree"\n\n[hosts.stormtree]\nssh = "stormtree"\n')
    result = runner.invoke(app, ["--debug", "ls"])
    assert result.exit_code == 0, f"output: {result.output}"


def test_top_level_croam_error_handler(home):
    """CroamError raised inside the app -> exit_code=2 + 'croam: ...' on stderr.

    Trigger via subprocess: invoke main() entry point with no config.toml.
    The no-verb path calls load_config() which raises ConfigError (a CroamError
    subclass). main() catches it and produces exit 2 + 'croam: ...' on stderr.
    """
    import subprocess

    # Ensure no config exists so load_config raises ConfigError.
    cfg = home / ".config" / "croam" / "config.toml"
    if cfg.exists():
        cfg.unlink()

    result = subprocess.run(
        [sys.executable, "-c", "from croam.cli import main; main()"],
        capture_output=True,
        text=True,
        env={**dict(__import__("os").environ), "HOME": str(home)},
    )
    assert result.returncode == 2
    assert "croam:" in result.stderr


def test_cmd_launch_uses_config(home, state_root, runner, monkeypatch):
    """cmd_launch passes a real Config (not None) to launch_cmd.

    Monkey-patch launch_cmd to capture its kwargs. If someone re-introduces
    the None-config bug, the assertion on config type will fail.
    """
    from croam.config import Config

    # Write a minimal config so load_config() succeeds.
    cfg = home / ".config" / "croam" / "config.toml"
    cfg.write_text('[self]\nhostname = "stormtree"\n\n[hosts.stormtree]\nssh = "stormtree"\n')

    captured: dict = {}

    def fake_launch_cmd(argv, config, home, **kwargs):
        captured["config"] = config
        captured["argv"] = argv
        captured["home"] = home
        return 0

    monkeypatch.setattr("croam.commands.launch.launch_cmd", fake_launch_cmd)

    result = runner.invoke(app, ["launch"])
    assert result.exit_code == 0, f"output: {result.output}"
    assert "config" in captured, "launch_cmd was never called"
    assert isinstance(captured["config"], Config), (
        f"expected Config, got {type(captured['config'])}"
    )
