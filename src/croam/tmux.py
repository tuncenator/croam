"""Thin subprocess wrappers around the tmux binary.

Pure mechanical I/O; no policy. All session-name construction happens in callers.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

from loguru import logger

from croam.errors import TmuxError


def _base_argv(sock: Path | None) -> list[str]:
    """Return the base tmux argv prefix including optional -S socket."""
    if sock is not None:
        return ["tmux", "-S", str(sock)]
    return ["tmux"]


def build_has_session_argv(name: str, sock: Path | None) -> list[str]:
    """Return argv for `tmux [-S sock] has-session -t <name>`."""
    return [*_base_argv(sock), "has-session", "-t", name]


def build_new_session_argv(
    name: str,
    command: list[str],
    sock: Path | None,
) -> list[str]:
    """Return argv for `tmux [-S sock] new-session -d -s <name> -- <command...>`.

    The literal `--` terminator is required to separate tmux flags from the command.
    """
    return [*_base_argv(sock), "new-session", "-d", "-s", name, "--", *command]


def build_attach_argv(name: str, sock: Path | None, read_only: bool) -> list[str]:
    """Return argv for `tmux [-S sock] attach -t <name>` (with `-r` if read_only).

    Note: tmux's read-only flag is `-r`, placed BEFORE `-t <name>`:
    `tmux -S sock attach -r -t name`.
    """
    base = [*_base_argv(sock), "attach"]
    if read_only:
        base.append("-r")
    base.extend(["-t", name])
    return base


def build_kill_session_argv(name: str, sock: Path | None) -> list[str]:
    """Return argv for `tmux [-S sock] kill-session -t <name>`."""
    return [*_base_argv(sock), "kill-session", "-t", name]


def build_list_sessions_argv(sock: Path | None) -> list[str]:
    """Return argv for `tmux [-S sock] list-sessions -F "#{session_name}:#{session_attached}"`."""
    return [*_base_argv(sock), "list-sessions", "-F", "#{session_name}:#{session_attached}"]


def has_session(name: str, sock: Path | None = None) -> bool:
    """`tmux has-session -t <name>` returns 0 (True) or 1 (False).

    Any other exit code (e.g., 127 if tmux missing) raises TmuxError.
    Stderr is captured at DEBUG level.
    """
    argv = build_has_session_argv(name, sock)
    logger.debug("tmux argv: {}", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise TmuxError(
        f"tmux has-session unexpected exit {result.returncode}: {result.stderr.strip()}"
    )


def new_session_detached(
    name: str,
    command: list[str],
    *,
    sock: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Create a detached tmux session running `command`. Raises TmuxError on failure.

    Parameters
    ----------
    name : the tmux session name (caller-formed, e.g., `claude-<sid>`)
    command : argv of the program to run inside the new window
    sock : private socket path, or None for default tmux server
    env : extra env vars merged onto os.environ for the tmux subprocess
    """
    argv = build_new_session_argv(name, command, sock)
    logger.debug("tmux argv: {}", argv)
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(argv, capture_output=True, text=True, check=False, env=full_env)
    if result.returncode != 0:
        raise TmuxError(
            f"tmux new-session failed (exit {result.returncode}): {result.stderr.strip()}"
        )


def attach(name: str, *, sock: Path | None = None, read_only: bool = False) -> NoReturn:
    """Replace the current process with `tmux attach -t <name>`. Does not return."""
    argv = build_attach_argv(name, sock, read_only)
    logger.debug("tmux exec argv: {}", argv)
    os.execvp(argv[0], argv)
    raise AssertionError("execvp returned")  # mypy/pyright happy; never reached


def kill_session(name: str, sock: Path | None = None) -> None:
    """Kill a tmux session. Idempotent: no-op if session does not exist or server not running."""
    argv = build_kill_session_argv(name, sock)
    logger.debug("tmux argv: {}", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return
    # tmux returns 1 with stderr "can't find session: NAME" when session is gone -- idempotent.
    # Also handles "no server running" (server exited) and "error connecting to" (no socket).
    stderr = result.stderr
    if (
        "can't find session" in stderr
        or "no server running" in stderr
        or "error connecting to" in stderr
    ):
        return
    raise TmuxError(
        f"tmux kill-session failed (exit {result.returncode}): {stderr.strip()}"
    )


def list_sessions(sock: Path | None = None) -> list[tuple[str, bool]]:
    """Return [(name, attached), ...]. Empty list if server is not running.

    `attached` is True when tmux reports `session_attached` >= 1.
    """
    argv = build_list_sessions_argv(sock)
    logger.debug("tmux argv: {}", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # Exit 1 with these stderr messages means no server / no socket -- empty case.
        stderr = result.stderr
        if "no server running" in stderr or "error connecting to" in stderr:
            return []
        raise TmuxError(
            f"tmux list-sessions failed (exit {result.returncode}): {stderr.strip()}"
        )
    sessions: list[tuple[str, bool]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        name, _, attached_str = line.partition(":")
        sessions.append((name, attached_str.strip() != "0"))
    return sessions
