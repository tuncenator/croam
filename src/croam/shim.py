"""Pure decision logic for the claude-in-tmux shim.

No subprocess calls, no filesystem I/O (except find_claude_real which uses shutil.which).
Every function takes its inputs explicitly so tests can inject them.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from croam.errors import CroamError


def should_wrap(
    argv: list[str],
    env: dict[str, str],
    stdin_isatty: bool,
    in_tmux: bool,
    opt_out_env_name: str = "CROAM_NO_TMUX",
) -> bool:
    """Decide whether to wrap `claude` invocation in a tmux session.

    Returns False (pass through) if any of:
      - stdin is not a tty (scripted invocation)
      - we're already inside a tmux session
      - opt-out env var is set
      - --no-tmux is in argv
      - --print is in argv (claude scripted/non-interactive mode)
      - --help or -h is in argv (claude prints help and exits)

    Returns True otherwise.

    Pure function: no side effects, no external state read.
    """
    if not stdin_isatty:
        return False
    if in_tmux:
        return False
    if opt_out_env_name in env:
        return False
    if "--no-tmux" in argv:
        return False
    if "--print" in argv:
        return False
    return not ("--help" in argv or "-h" in argv)


_RESUME_FLAGS = frozenset({"--resume", "-r"})
_CONTINUE_FLAGS = frozenset({"--continue", "-c"})
_SESSION_ID_FLAG = "--session-id"


def derive_sid(argv: list[str], env: dict[str, str]) -> str:
    """Return the session id for this launch.

    Recognized sources (checked in order):
      --resume <sid> / --resume=<sid> / -r <sid>
      --session-id <sid> / --session-id=<sid>
    Otherwise generate a fresh uuid4 string.
    """
    for i, token in enumerate(argv):
        if token in _RESUME_FLAGS:
            if i + 1 < len(argv):
                return argv[i + 1]
            continue
        if token.startswith("--resume="):
            return token.split("=", 1)[1]
        if token == _SESSION_ID_FLAG:
            if i + 1 < len(argv):
                return argv[i + 1]
            continue
        if token.startswith("--session-id="):
            return token.split("=", 1)[1]
    return str(uuid.uuid4())


def needs_session_id_injection(argv: list[str]) -> bool:
    """Return True when --session-id should be injected into claude argv.

    False when the user already specified --resume, --continue, --session-id,
    or their short forms (Claude Code determines its own session ID).
    """
    for token in argv:
        if token in _RESUME_FLAGS | _CONTINUE_FLAGS | {_SESSION_ID_FLAG}:
            return False
        if token.startswith(("--resume=", "--session-id=")):
            return False
    return True


def is_continue_mode(argv: list[str]) -> bool:
    """Return True when --continue / -c is in argv."""
    return bool(_CONTINUE_FLAGS & set(argv))


def strip_no_tmux(argv: list[str]) -> list[str]:
    """Return argv with `--no-tmux` removed (preserving order)."""
    return [a for a in argv if a != "--no-tmux"]


def find_claude_real() -> Path:
    """Locate the real claude binary on PATH.

    Prefers `claude-real` (the renamed binary after shim install per spec section 8),
    falls back to `claude`. Raises CroamError if neither is found.
    """
    for name in ("claude-real", "claude"):
        located = shutil.which(name)
        if located:
            return Path(located)
    raise CroamError("could not find `claude-real` or `claude` on PATH")


def is_in_tmux(env: dict[str, str]) -> bool:
    """Return True if the standard `TMUX` env var is set to a non-empty value."""
    return bool(env.get("TMUX", "").strip())
