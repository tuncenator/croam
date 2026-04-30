"""croam test fixtures.

The autouse _safety_guard refuses to run any test where HOME has not been
redirected away from the user's real home, except when CROAM_E2E=1.
This prevents accidental contamination of the user's real ~/.claude.

NEVER bypass _safety_guard. NEVER call Path.home() in test code (use the
home fixture). NEVER call os.path.expanduser("~") in test code.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests._helpers.fake_ssh import (
    SSH_SHIM_SCRIPT,
    fixture_path_for,
)


def _check_home_redirected(home: str | None, e2e: str | None) -> None:
    """Validate that HOME points to a tmp path. Raises pytest.fail if not."""
    if e2e == "1":
        return
    import tempfile

    tmp_prefix = tempfile.gettempdir()
    if not home or not (home.startswith("/tmp/") or home.startswith(tmp_prefix)):
        pytest.fail(
            f"HOME is not redirected (HOME={home!r}); refusing to run. "
            "Use the `home` fixture or set CROAM_E2E=1."
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    """Check HOME redirect after all fixtures are set up, before the test body.

    This hookwrapper fires after fixture setup completes. By this point, the
    `home` fixture (if requested) has already redirected HOME via monkeypatch.
    """
    _check_home_redirected(os.environ.get("HOME"), os.environ.get("CROAM_E2E"))
    yield


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a tmp_path-rooted fake HOME and redirect HOME env var to it."""
    h = tmp_path / "home"
    (h / ".claude" / "projects").mkdir(parents=True)
    (h / ".claude" / "sessions").mkdir(parents=True)
    (h / ".config" / "croam").mkdir(parents=True)
    (h / ".local" / "share" / "croam").mkdir(parents=True)
    (h / ".local" / "state" / "croam").mkdir(parents=True)
    (h / "Sync" / "croam").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    # Some libraries cache cwd or expand at import; nuke a few common pitfalls.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return h


@pytest.fixture
def tmux_socket(tmp_path: Path) -> Path:
    """Return a private tmux socket path; tests pass it as `tmux -S <path>`."""
    return tmp_path / "tmux.sock"


@pytest.fixture
def state_root(home: Path) -> Path:
    """Return <home>/.local/share/croam pre-populated with default test hostname subdirs."""
    root = home / ".local" / "share" / "croam"
    for hostname in ("stormtree", "vicar", "corpsefire"):
        (root / hostname).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def ssh_shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """Install a fake `ssh` binary on PATH that emits canned output keyed off (host, argv).

    Returns an object with `.register(host, argv, stdout='', stderr='', exit_code=0, delay_s=0.0)`.
    Tests register canned responses; the binary on PATH looks them up by JSON file.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fixtures_dir = tmp_path / "ssh-fixtures"
    fixtures_dir.mkdir()

    ssh_path = bin_dir / "ssh"
    ssh_path.write_text(SSH_SHIM_SCRIPT.replace("__FIXTURES_DIR__", str(fixtures_dir)))
    ssh_path.chmod(ssh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    class Registry:
        def register(
            self,
            host: str,
            argv: list[str],
            *,
            stdout: str = "",
            stderr: str = "",
            exit_code: int = 0,
            delay_s: float = 0.0,
        ) -> None:
            target = fixture_path_for(fixtures_dir, host, argv)
            target.write_text(
                json.dumps(
                    {"stdout": stdout, "stderr": stderr, "exit_code": exit_code, "delay_s": delay_s}
                )
            )

    yield Registry()


@pytest.fixture
def e2e_dummy() -> tuple[Path, str]:
    """Tier 2: yield the real disposable claude session path + sid.

    Skips the test if CROAM_E2E is not set to "1".
    """
    if os.environ.get("CROAM_E2E") != "1":
        pytest.skip("CROAM_E2E=1 not set; skipping Tier 2 dummy-session test")
    return Path("/tmp/croam-e2e"), "ff7afd8a-ea17-4183-a131-566e7bcb0758"
