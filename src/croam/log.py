"""Loguru configuration for croam CLI."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_STDERR_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{module}</cyan>:<cyan>{function}</cyan> | "
    "<level>{message}</level>"
)

_NOISY_MODULES = {
    "paramiko": "WARNING",
    "asyncssh": "WARNING",
    "urllib3": "WARNING",
    "asyncio": "INFO",
}


def configure(level: str = "INFO", log_file: Path | None = None, debug: bool = False) -> None:
    """Set up croam's logging. Idempotent: removes any existing sinks first."""
    logger.remove()
    filter_map = {**_NOISY_MODULES, "": level}
    logger.add(
        sys.stderr,
        format=_STDERR_FORMAT,
        level=0,
        filter=filter_map,
        colorize=True,
        backtrace=debug,
        diagnose=debug,
        enqueue=False,
    )
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            level="DEBUG",
            serialize=True,
            format="{message}",
            backtrace=True,
            diagnose=False,
            enqueue=True,
            rotation="10 MB",
            retention=5,
            encoding="utf-8",
        )


__all__ = ["configure", "logger"]
