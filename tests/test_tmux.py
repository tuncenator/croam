"""Tests for src/croam/tmux.py -- real tmux against private socket."""

from __future__ import annotations

from pathlib import Path

import pytest

from croam import tmux
from croam.errors import TmuxError


def test_build_has_session_argv(home):
    assert tmux.build_has_session_argv("foo", None) == ["tmux", "has-session", "-t", "foo"]
    assert tmux.build_has_session_argv("foo", Path("/tmp/sock")) == [
        "tmux",
        "-S",
        "/tmp/sock",
        "has-session",
        "-t",
        "foo",
    ]


def test_build_new_session_argv(home):
    assert tmux.build_new_session_argv("foo", ["sleep", "10"], None) == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        "foo",
        "--",
        "sleep",
        "10",
    ]
    assert tmux.build_new_session_argv("foo", ["sleep", "10"], Path("/tmp/sock")) == [
        "tmux",
        "-S",
        "/tmp/sock",
        "new-session",
        "-d",
        "-s",
        "foo",
        "--",
        "sleep",
        "10",
    ]


def test_build_attach_argv_default(home):
    assert tmux.build_attach_argv("foo", None, read_only=False) == [
        "tmux",
        "attach",
        "-t",
        "foo",
    ]


def test_build_attach_argv_read_only(home):
    assert tmux.build_attach_argv("foo", Path("/tmp/sock"), read_only=True) == [
        "tmux",
        "-S",
        "/tmp/sock",
        "attach",
        "-r",
        "-t",
        "foo",
    ]


def test_build_kill_session_argv(home):
    assert tmux.build_kill_session_argv("foo", None) == [
        "tmux",
        "kill-session",
        "-t",
        "foo",
    ]


def test_build_list_sessions_argv(home):
    assert tmux.build_list_sessions_argv(Path("/tmp/sock")) == [
        "tmux",
        "-S",
        "/tmp/sock",
        "list-sessions",
        "-F",
        "#{session_name}:#{session_attached}",
    ]


def test_has_session_false_no_server(home, tmux_socket):
    """An empty private socket has no sessions."""
    assert tmux.has_session("nonexistent", sock=tmux_socket) is False


def test_new_and_has(home, tmux_socket):
    """Creating a session makes has_session True; killing makes it False."""
    tmux.new_session_detached("croam-test-foo", ["sleep", "10"], sock=tmux_socket)
    try:
        assert tmux.has_session("croam-test-foo", sock=tmux_socket) is True
    finally:
        tmux.kill_session("croam-test-foo", sock=tmux_socket)
    assert tmux.has_session("croam-test-foo", sock=tmux_socket) is False


def test_list_sessions_empty(home, tmux_socket):
    assert tmux.list_sessions(sock=tmux_socket) == []


def test_list_sessions_three(home, tmux_socket):
    names = ["croam-test-a", "croam-test-b", "croam-test-c"]
    try:
        for n in names:
            tmux.new_session_detached(n, ["sleep", "10"], sock=tmux_socket)
        listed = tmux.list_sessions(sock=tmux_socket)
        assert sorted(name for name, _ in listed) == names
        # None attached.
        assert all(attached is False for _, attached in listed)
    finally:
        for n in names:
            tmux.kill_session(n, sock=tmux_socket)


def test_idempotent_kill_no_session(home, tmux_socket):
    """Killing a non-existent session does not raise.

    Creates a server first so we get "can't find session" not "no server running".
    """
    # Start a real session so the server is alive, then kill non-existent.
    tmux.new_session_detached("croam-keeper", ["sleep", "30"], sock=tmux_socket)
    try:
        tmux.kill_session("not-there", sock=tmux_socket)
    finally:
        tmux.kill_session("croam-keeper", sock=tmux_socket)


def test_idempotent_kill_no_server(home, tmux_socket):
    """Killing on a socket with no server running does not raise."""
    # tmux_socket fixture starts empty; no server started.
    tmux.kill_session("not-there", sock=tmux_socket)


def test_new_session_failure_raises(home, tmux_socket):
    """Duplicate session name raises TmuxError.

    Note: tmux new-session -d returns 0 even if the inner command fails, because
    the child is detached. To force a failure, create a session with a duplicate
    name."""
    tmux.new_session_detached("croam-test-dup", ["sleep", "10"], sock=tmux_socket)
    try:
        with pytest.raises(TmuxError, match="new-session"):
            tmux.new_session_detached("croam-test-dup", ["sleep", "10"], sock=tmux_socket)
    finally:
        tmux.kill_session("croam-test-dup", sock=tmux_socket)
