"""Centralized subprocess wrapper.

All croam subprocess invocations go through this module to enforce:
- DEBUG-level logging of argv
- Consistent timeout handling translated to CroamError
- Default capture=True with text=True
- Default check=False (callers inspect returncode themselves)
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from loguru import logger

from croam.errors import TimeoutError as CroamTimeoutError


def run(
    argv: list[str],
    *,
    timeout: float | None = None,
    check: bool = False,
    capture: bool = True,
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with croam's defaults.

    Logs argv at DEBUG. Translates subprocess.TimeoutExpired to croam.errors.TimeoutError.
    Returns CompletedProcess with text=True (str stdout/stderr).
    """
    logger.debug("proc.run argv={}", shlex.join(argv))
    try:
        return subprocess.run(
            argv,
            timeout=timeout,
            check=check,
            capture_output=capture,
            text=True,
            env=env,
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired as e:
        raise CroamTimeoutError(
            f"command timed out after {timeout}s: {shlex.join(argv)}",
            argv=argv,
            timeout_s=timeout,
        ) from e
