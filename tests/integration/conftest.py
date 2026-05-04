"""Integration test fixtures: two-host synthetic environment.

TwoHostEnv builds isolated home/state directories for stormtree and vicar,
wires a shared state_root (both host subdirs), and installs the ssh_shim
with canned responses for cross-host probes.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._helpers.fake_ssh import SSH_SHIM_SCRIPT, fixture_path_for


@dataclass(frozen=True)
class HostEnv:
    """Per-host directory layout."""

    name: str
    home: Path
    state_root: Path
    config_path: Path


@dataclass(frozen=True)
class TwoHostEnv:
    """Two-host synthetic environment: stormtree (local) + vicar (remote)."""

    stormtree: HostEnv
    vicar: HostEnv
    # Shared state_root containing subdirs for both hosts.
    shared_state_root: Path


class TwoHostSshRegistry:
    """SSH registry scoped to a TwoHostEnv."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._fixtures_dir = fixtures_dir

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
        target = fixture_path_for(self._fixtures_dir, host, argv)
        target.write_text(
            json.dumps(
                {"stdout": stdout, "stderr": stderr, "exit_code": exit_code, "delay_s": delay_s}
            )
        )


def _write_config(config_path: Path, self_hostname: str, state_root: Path) -> None:
    """Write a minimal two-host config.toml."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f'[self]\nhostname = "{self_hostname}"\n\n'
        f'[hosts.stormtree]\nssh = "stormtree"\nsync = false\n\n'
        f'[hosts.vicar]\nssh = "vicar"\nsync = false\n\n'
        f"[storage]\n"
        f'state_root = "{state_root}"\n\n'
        f'[discovery]\nmode = "ssh"\n\n'
        f'[ownership]\nclaim_verify = "ssh-strict"\n\n'
        f'[picker]\ndefault_filter = "exact-pwd"\nlast_window_days = 30\n\n'
        f"[shim]\nenabled = false\n"
        f'opt_out_env = "CROAM_NO_TMUX"\n'
    )


@pytest.fixture
def two_host_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TwoHostEnv:
    """Build a two-host environment with stormtree + vicar.

    - Each host gets its own home directory tree.
    - Both hosts share a single state_root so assertions files are co-located.
    - HOME is redirected to stormtree's home by default.
    - An ssh_shim is installed; tests register responses on the returned registry.
    """
    # Build stormtree directories.
    st_home = tmp_path / "stormtree" / "home"
    for subdir in (
        ".claude/projects",
        ".claude/sessions",
        ".config/croam",
        ".local/share/croam",
        ".local/state/croam",
        "Sync/croam",
    ):
        (st_home / subdir).mkdir(parents=True)

    # Build vicar directories.
    vc_home = tmp_path / "vicar" / "home"
    for subdir in (
        ".claude/projects",
        ".claude/sessions",
        ".config/croam",
        ".local/share/croam",
        ".local/state/croam",
        "Sync/croam",
    ):
        (vc_home / subdir).mkdir(parents=True)

    # Shared state_root: both host subdirs live under the same root so
    # read_all_assertions can see both.
    shared_state = tmp_path / "state"
    (shared_state / "stormtree").mkdir(parents=True)
    (shared_state / "vicar").mkdir(parents=True)

    # Write configs for each host.
    st_config = st_home / ".config" / "croam" / "config.toml"
    _write_config(st_config, "stormtree", shared_state)

    vc_config = vc_home / ".config" / "croam" / "config.toml"
    _write_config(vc_config, "vicar", shared_state)

    # Redirect HOME to stormtree (the "local" host).
    monkeypatch.setenv("HOME", str(st_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    # Install the ssh_shim.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fixtures_dir = tmp_path / "ssh-fixtures"
    fixtures_dir.mkdir()

    ssh_path = bin_dir / "ssh"
    ssh_path.write_text(SSH_SHIM_SCRIPT.replace("__FIXTURES_DIR__", str(fixtures_dir)))
    ssh_path.chmod(ssh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    st = HostEnv(
        name="stormtree",
        home=st_home,
        state_root=shared_state,
        config_path=st_config,
    )
    vc = HostEnv(
        name="vicar",
        home=vc_home,
        state_root=shared_state,
        config_path=vc_config,
    )
    return TwoHostEnv(stormtree=st, vicar=vc, shared_state_root=shared_state)


@pytest.fixture
def two_host_ssh(two_host_env: TwoHostEnv, tmp_path: Path) -> TwoHostSshRegistry:
    """Return an SSH registry pre-wired for the two_host_env."""
    fixtures_dir = tmp_path / "ssh-fixtures"
    return TwoHostSshRegistry(fixtures_dir)
