"""Tests for src/croam/commands/peek.py via the CLI surface."""

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


def _seed_local_session(home: Path, state_root: Path, cwd: Path) -> str:
    """Create a synthetic JSONL + local assertion, return sid."""
    from tests._helpers.synth_assertions import build_assertion, write_assertions_file
    from tests._helpers.synth_jsonl import build_jsonl

    sid = str(uuid.uuid4())
    build_jsonl(home, sid, cwd, n_user=2)

    assertion = build_assertion(
        sid,
        "stormtree",
        datetime.now(UTC),
        cwd_normalized=f"~/{cwd.relative_to(home)}" if cwd.is_relative_to(home) else str(cwd),
    )
    write_assertions_file(state_root, "stormtree", {sid: assertion})
    return sid


def _seed_remote_assertion(state_root: Path, owner: str, sid: str, cwd_normalized: str) -> None:
    """Write a remote host's assertion."""
    from tests._helpers.synth_assertions import build_assertion, write_assertions_file

    assertion = build_assertion(
        sid,
        owner,
        datetime.now(UTC),
        cwd_normalized=cwd_normalized,
    )
    (state_root / owner).mkdir(parents=True, exist_ok=True)
    write_assertions_file(state_root, owner, {sid: assertion})


# ---------------------------------------------------------------------------
# test_peek_local_live
# ---------------------------------------------------------------------------


def test_peek_local_live(
    home: Path, state_root: Path, runner, tmux_socket: Path, monkeypatch: pytest.MonkeyPatch
):
    """Local session with live tmux -> tmux-peek with attach -r -t."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    sid = _seed_local_session(home, state_root, cwd)

    # Start a real tmux session.
    session_name = f"claude-{sid}"
    subprocess.run(
        ["tmux", "-S", str(tmux_socket), "new-session", "-d", "-s", session_name, "sleep", "30"],
        check=True,
    )

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    result = runner.invoke(app, ["peek", sid, "--no-exec"])
    subprocess.run(
        ["tmux", "-S", str(tmux_socket), "kill-session", "-t", session_name], check=False
    )

    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["action"] == "tmux-peek"
    argv = plan["argv"]
    assert "attach" in argv
    assert "-r" in argv
    assert f"claude-{sid}" in argv


# ---------------------------------------------------------------------------
# test_peek_local_archived
# ---------------------------------------------------------------------------


def test_peek_local_archived(
    home: Path, state_root: Path, runner, tmux_socket: Path, monkeypatch: pytest.MonkeyPatch
):
    """Local session with no tmux -> static-transcript, path ends with <sid>.jsonl."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    sid = _seed_local_session(home, state_root, cwd)

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    result = runner.invoke(app, ["peek", sid, "--no-exec"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["action"] == "static-transcript"
    assert plan["argv"][1].endswith(f"{sid}.jsonl")


# ---------------------------------------------------------------------------
# test_peek_local_archived_renders
# ---------------------------------------------------------------------------


def test_peek_local_archived_renders(
    home: Path, state_root: Path, runner, tmux_socket: Path, monkeypatch: pytest.MonkeyPatch
):
    """No tmux: actually render transcript, stdout has [user] twice (n_user=2)."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    sid = _seed_local_session(home, state_root, cwd)  # n_user=2 by default

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    result = runner.invoke(app, ["peek", sid])
    assert result.exit_code == 0, result.output
    assert result.output.count("[user]") == 2


# ---------------------------------------------------------------------------
# test_peek_remote_reachable_recurses
# ---------------------------------------------------------------------------


def test_peek_remote_reachable_recurses(
    home: Path,
    state_root: Path,
    runner,
    tmux_socket: Path,
    ssh_shim,
    monkeypatch: pytest.MonkeyPatch,
):
    """Remote reachable -> ssh-recurse with --here-on-owner."""
    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\n'
    _write_config(home, extra_hosts=cfg_extra)

    sid = str(uuid.uuid4())
    _seed_remote_assertion(state_root, "vicar", sid, "~/remote-proj")

    # Register ssh shim: vicar true -> exit 0 (reachability probe)
    ssh_shim.register("vicar", ["true"], exit_code=0)

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    result = runner.invoke(app, ["peek", sid, "--no-exec"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["action"] == "ssh-recurse"
    assert "vicar" in plan["argv"]
    argv_str = " ".join(plan["argv"])
    assert "croam peek" in argv_str
    assert "--here-on-owner" in argv_str


# ---------------------------------------------------------------------------
# test_peek_remote_unreachable_via_mirror
# ---------------------------------------------------------------------------


def test_peek_remote_unreachable_via_mirror(
    home: Path, state_root: Path, runner, ssh_shim, monkeypatch: pytest.MonkeyPatch
):
    """Remote unreachable, mirror exists -> static-transcript-mirror action returned."""
    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\nhome = "/tmp/vicar-home"\n'
    _write_config(home, extra_hosts=cfg_extra)

    sid = str(uuid.uuid4())
    cwd_normalized = "~/proj"
    _seed_remote_assertion(state_root, "vicar", sid, cwd_normalized)

    # SSH probe fails -> unreachable
    ssh_shim.register("vicar", ["true"], exit_code=1)

    # Build the mirror JSONL at state_root/vicar/projects/<encoded>/<sid>.jsonl
    from croam.paths import encode_cwd

    vicar_home = Path("/tmp/vicar-home")
    cwd_abs = vicar_home / "proj"
    encoded = encode_cwd(cwd_abs)
    mirror_dir = state_root / "vicar" / "projects" / encoded
    mirror_dir.mkdir(parents=True, exist_ok=True)
    mirror_jsonl = mirror_dir / f"{sid}.jsonl"
    mirror_jsonl.write_text(
        '{"type":"user","message":"mirror msg"}\n',
        encoding="utf-8",
    )

    # Use --no-exec to verify the planned action without needing stdout capture of transcript.
    result = runner.invoke(app, ["peek", sid, "--no-exec"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["action"] == "static-transcript-mirror"
    assert plan["argv"][1].endswith(f"{sid}.jsonl")


# ---------------------------------------------------------------------------
# test_peek_remote_unreachable_no_mirror
# ---------------------------------------------------------------------------


def test_peek_remote_unreachable_no_mirror(
    home: Path, state_root: Path, ssh_shim, monkeypatch: pytest.MonkeyPatch
):
    """Remote unreachable, no mirror -> exit 2, stderr has 'unreachable'."""
    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\nhome = "/tmp/vicar-home"\n'
    _write_config(home, extra_hosts=cfg_extra)

    sid = str(uuid.uuid4())
    _seed_remote_assertion(state_root, "vicar", sid, "~/proj")

    ssh_shim.register("vicar", ["true"], exit_code=1)

    # Use subprocess to invoke main() so CroamError -> SystemExit(2) is triggered.
    import sys

    env = {**__import__("os").environ, "HOME": str(home)}
    proc = subprocess.run(
        [sys.executable, "-c", "from croam.cli import main; main()", "peek", sid],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 2
    assert "unreachable" in proc.stderr.lower() or "no mirror" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# test_peek_sid_not_found
# ---------------------------------------------------------------------------


def test_peek_sid_not_found(home: Path, state_root: Path):
    """No assertion for sid -> exit 2, 'not found' in stderr."""
    _write_config(home)
    sid = str(uuid.uuid4())

    import sys

    proc = subprocess.run(
        [sys.executable, "-c", "from croam.cli import main; main()", "peek", sid],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "HOME": str(home)},
    )
    assert proc.returncode == 2
    assert "not found" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# Direct run() tests for coverage of branches not reachable via --no-exec
# ---------------------------------------------------------------------------


def test_peek_run_sid_not_found_raises(home: Path, state_root: Path):
    """run() raises SessionNotFound when sid absent."""
    from croam.commands.peek import run
    from croam.config import load_config
    from croam.errors import SessionNotFound

    _write_config(home)
    config = load_config(home / ".config" / "croam" / "config.toml")
    sid = str(uuid.uuid4())

    with pytest.raises(SessionNotFound):
        run(sid, {}, config, home, no_exec=True)


def test_peek_run_here_on_owner_uses_local_owner(
    home: Path, state_root: Path, tmux_socket: Path, monkeypatch: pytest.MonkeyPatch
):
    """here_on_owner=True -> owner is self_hostname regardless of merged ownership."""
    from croam.commands.peek import run
    from croam.config import load_config

    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\n'
    _write_config(home, extra_hosts=cfg_extra)
    config = load_config(home / ".config" / "croam" / "config.toml")

    cwd = home / "proj"
    cwd.mkdir(parents=True)
    sid = _seed_local_session(home, state_root, cwd)

    monkeypatch.setenv("CROAM_TMUX_SOCK", str(tmux_socket))

    # here_on_owner=True with no tmux -> static-transcript (local path)
    import io

    buf = io.StringIO()
    import sys

    old = sys.stdout
    sys.stdout = buf
    try:
        rc = run(sid, {}, config, home, here_on_owner=True, no_exec=True)
    finally:
        sys.stdout = old
    assert rc == 0
    import json

    plan = json.loads(buf.getvalue())
    assert plan["action"] == "static-transcript"


def test_peek_peer_alias_fallback(home: Path, state_root: Path):
    """_peer_alias returns owner name itself when not in config hosts."""
    from croam.commands.peek import _peer_alias
    from croam.config import load_config

    _write_config(home)
    config = load_config(home / ".config" / "croam" / "config.toml")
    assert _peer_alias("unknown-host", config) == "unknown-host"


def test_peek_run_remote_unreachable_raises_no_mirror(home: Path, state_root: Path, ssh_shim):
    """run() raises SshError when remote unreachable and no mirror."""
    from croam.commands.peek import run
    from croam.config import load_config
    from croam.errors import SshError
    from tests._helpers.synth_assertions import build_assertion, write_assertions_file

    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\nhome = "/tmp/vicar-home"\n'
    _write_config(home, extra_hosts=cfg_extra)
    config = load_config(home / ".config" / "croam" / "config.toml")

    sid = str(uuid.uuid4())
    (state_root / "vicar").mkdir(parents=True, exist_ok=True)
    write_assertions_file(
        state_root,
        "vicar",
        {sid: build_assertion(sid, "vicar", datetime.now(UTC), cwd_normalized="~/proj")},
    )

    ssh_shim.register("vicar", ["true"], exit_code=1)

    with pytest.raises(SshError, match="unreachable"):
        run(sid, {}, config, home, no_exec=True)


def test_peek_run_mirror_renders_transcript(home: Path, state_root: Path, ssh_shim):
    """Unreachable remote with mirror: no_exec=False renders the mirror transcript."""
    import io
    import sys

    from croam.commands.peek import run
    from croam.config import load_config
    from croam.paths import encode_cwd
    from tests._helpers.synth_assertions import build_assertion, write_assertions_file

    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\nhome = "/tmp/vicar-home"\n'
    _write_config(home, extra_hosts=cfg_extra)
    config = load_config(home / ".config" / "croam" / "config.toml")

    sid = str(uuid.uuid4())
    cwd_normalized = "~/proj"
    (state_root / "vicar").mkdir(parents=True, exist_ok=True)
    write_assertions_file(
        state_root,
        "vicar",
        {sid: build_assertion(sid, "vicar", datetime.now(UTC), cwd_normalized=cwd_normalized)},
    )

    ssh_shim.register("vicar", ["true"], exit_code=1)

    vicar_home = Path("/tmp/vicar-home")
    cwd_abs = vicar_home / "proj"
    encoded = encode_cwd(cwd_abs)
    mirror_dir = state_root / "vicar" / "projects" / encoded
    mirror_dir.mkdir(parents=True, exist_ok=True)
    mirror_jsonl = mirror_dir / f"{sid}.jsonl"
    mirror_jsonl.write_text('{"type":"user","message":"from mirror"}\n', encoding="utf-8")

    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = run(sid, {}, config, home, no_exec=False)
    finally:
        sys.stdout = old

    assert rc == 0
    assert "[user] from mirror" in buf.getvalue()
