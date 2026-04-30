"""croam-specific exceptions."""
from __future__ import annotations


class CroamError(Exception):
    """Base for all croam errors caught by the CLI top-level handler."""


class ConfigError(CroamError):
    """Invalid or missing configuration."""

    def __init__(self, message: str, *, field: str | None = None, reason: str | None = None) -> None:
        self.field = field
        self.reason = reason
        super().__init__(message)


class SshError(CroamError):
    """SSH command failed in a way that prevents progress (NOT a reachability=False signal)."""


class OwnershipConflict(CroamError):
    """Conflicting ownership assertion or malformed ownership.json."""


class TmuxError(CroamError):
    """tmux subprocess failed."""


class SessionNotFound(CroamError):
    """Asked for a sid we cannot locate on any reachable host."""


class OrphanRefused(CroamError):
    """Action refused because target sid has no backing assertion."""


class TimeoutError(CroamError):  # intentional shadow of builtin, scoped to this module
    """Subprocess timed out. Wraps subprocess.TimeoutExpired."""

    def __init__(
        self, message: str, *, argv: list[str] | None = None, timeout_s: float | None = None
    ) -> None:
        self.argv = argv
        self.timeout_s = timeout_s
        super().__init__(message)
