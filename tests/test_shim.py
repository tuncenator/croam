"""Tests for src/croam/shim.py -- pure decision functions."""

from __future__ import annotations

import uuid

import pytest

from croam import shim
from croam.errors import CroamError


def test_should_wrap_default(home):
    assert (
        shim.should_wrap(
            argv=["claude"],
            env={},
            stdin_isatty=True,
            in_tmux=False,
        )
        is True
    )


def test_should_wrap_in_tmux(home):
    assert (
        shim.should_wrap(
            argv=["claude"],
            env={"TMUX": "/tmp/tmux-1000/default,123,4"},
            stdin_isatty=True,
            in_tmux=True,
        )
        is False
    )


def test_should_wrap_not_tty(home):
    assert (
        shim.should_wrap(
            argv=["claude"],
            env={},
            stdin_isatty=False,
            in_tmux=False,
        )
        is False
    )


def test_should_wrap_no_tmux_flag(home):
    assert (
        shim.should_wrap(
            argv=["claude", "--no-tmux", "--effort", "max"],
            env={},
            stdin_isatty=True,
            in_tmux=False,
        )
        is False
    )


def test_should_wrap_print_flag(home):
    assert (
        shim.should_wrap(
            argv=["claude", "--print", "explain this"],
            env={},
            stdin_isatty=True,
            in_tmux=False,
        )
        is False
    )


def test_should_wrap_help_long(home):
    assert (
        shim.should_wrap(
            argv=["claude", "--help"],
            env={},
            stdin_isatty=True,
            in_tmux=False,
        )
        is False
    )


def test_should_wrap_help_short(home):
    assert (
        shim.should_wrap(
            argv=["claude", "-h"],
            env={},
            stdin_isatty=True,
            in_tmux=False,
        )
        is False
    )


def test_should_wrap_opt_out_env_default_name(home):
    assert (
        shim.should_wrap(
            argv=["claude"],
            env={"CROAM_NO_TMUX": "1"},
            stdin_isatty=True,
            in_tmux=False,
        )
        is False
    )


def test_should_wrap_opt_out_env_custom_name(home):
    assert (
        shim.should_wrap(
            argv=["claude"],
            env={"NOPE": "1"},
            stdin_isatty=True,
            in_tmux=False,
            opt_out_env_name="NOPE",
        )
        is False
    )


def test_derive_sid_resume_space(home):
    assert (
        shim.derive_sid(
            argv=["claude", "--resume", "abc-123"],
            env={},
        )
        == "abc-123"
    )


def test_derive_sid_resume_equals(home):
    assert (
        shim.derive_sid(
            argv=["claude", "--resume=abc-123"],
            env={},
        )
        == "abc-123"
    )


def test_derive_sid_resume_in_middle(home):
    assert (
        shim.derive_sid(
            argv=["claude", "--effort", "max", "--resume", "abc-123", "--print"],
            env={},
        )
        == "abc-123"
    )


def test_derive_sid_resume_dangling(home):
    """--resume with no value after it -> fall through to uuid4."""
    sid = shim.derive_sid(argv=["claude", "--resume"], env={})
    uuid.UUID(sid)  # raises if not a valid uuid


def test_derive_sid_no_resume_returns_uuid(home):
    sid = shim.derive_sid(argv=["claude"], env={})
    parsed = uuid.UUID(sid)
    assert parsed.version == 4


def test_strip_no_tmux_present(home):
    assert shim.strip_no_tmux(["claude", "--no-tmux", "--effort", "max"]) == [
        "claude",
        "--effort",
        "max",
    ]


def test_strip_no_tmux_absent(home):
    assert shim.strip_no_tmux(["claude", "--effort", "max"]) == [
        "claude",
        "--effort",
        "max",
    ]


def test_strip_no_tmux_multiple(home):
    """Defensive: if the user typed --no-tmux twice, strip both."""
    assert shim.strip_no_tmux(["claude", "--no-tmux", "--no-tmux", "x"]) == ["claude", "x"]


def test_find_claude_real_prefers_real(home, tmp_path, monkeypatch):
    """When both `claude` and `claude-real` are on PATH, prefer claude-real."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text("#!/bin/sh\necho claude\n")
    (bindir / "claude").chmod(0o755)
    (bindir / "claude-real").write_text("#!/bin/sh\necho real\n")
    (bindir / "claude-real").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert shim.find_claude_real() == bindir / "claude-real"


def test_find_claude_real_falls_back_to_claude(home, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text("#!/bin/sh\necho claude\n")
    (bindir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert shim.find_claude_real() == bindir / "claude"


def test_find_claude_real_neither(home, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # empty bindir
    with pytest.raises(CroamError, match="claude-real"):
        shim.find_claude_real()


def test_is_in_tmux_set(home):
    assert shim.is_in_tmux({"TMUX": "/tmp/tmux/default,1,2"}) is True


def test_is_in_tmux_empty(home):
    assert shim.is_in_tmux({"TMUX": ""}) is False


def test_is_in_tmux_unset(home):
    assert shim.is_in_tmux({}) is False


def test_is_in_tmux_whitespace(home):
    assert shim.is_in_tmux({"TMUX": "  "}) is False


# --- derive_sid: --session-id and -r support ---


def test_derive_sid_session_id_space(home):
    assert shim.derive_sid(["claude", "--session-id", "abc-123"], {}) == "abc-123"


def test_derive_sid_session_id_equals(home):
    assert shim.derive_sid(["claude", "--session-id=abc-123"], {}) == "abc-123"


def test_derive_sid_short_resume(home):
    assert shim.derive_sid(["claude", "-r", "abc-123"], {}) == "abc-123"


# --- needs_session_id_injection ---


def test_needs_injection_new_session(home):
    assert shim.needs_session_id_injection(["claude", "--effort", "max"]) is True


def test_needs_injection_resume_long(home):
    assert shim.needs_session_id_injection(["claude", "--resume", "abc"]) is False


def test_needs_injection_resume_short(home):
    assert shim.needs_session_id_injection(["claude", "-r", "abc"]) is False


def test_needs_injection_resume_equals(home):
    assert shim.needs_session_id_injection(["claude", "--resume=abc"]) is False


def test_needs_injection_continue_long(home):
    assert shim.needs_session_id_injection(["claude", "--continue"]) is False


def test_needs_injection_continue_short(home):
    assert shim.needs_session_id_injection(["claude", "-c"]) is False


def test_needs_injection_session_id_already(home):
    assert shim.needs_session_id_injection(["claude", "--session-id", "abc"]) is False


def test_needs_injection_session_id_equals(home):
    assert shim.needs_session_id_injection(["claude", "--session-id=abc"]) is False


# --- is_continue_mode ---


def test_is_continue_long(home):
    assert shim.is_continue_mode(["claude", "--continue"]) is True


def test_is_continue_short(home):
    assert shim.is_continue_mode(["claude", "-c"]) is True


def test_is_continue_absent(home):
    assert shim.is_continue_mode(["claude", "--effort", "max"]) is False
