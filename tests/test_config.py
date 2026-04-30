"""Tests for src/croam/config.py.

All eight tests are Tier 1 (synthetic fixtures only).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from croam.config import bootstrap_config, load_config
from croam.errors import ConfigError

_MINIMAL_TOML = """\
[self]
hostname = "test-host"

[hosts.test-host]
ssh = "test-host"
sync = true
"""


def _write_config(home: Path, content: str) -> Path:
    """Write content to the default config path under home."""
    p = home / ".config" / "croam" / "config.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Test 1: minimal valid TOML loads correctly with expected field values
# ---------------------------------------------------------------------------


def test_load_minimal_valid(home: Path) -> None:
    """Minimal valid TOML loads into a Config with correct field values."""
    content = _MINIMAL_TOML + '\n[discovery]\nmode = "ssh"\n'
    _write_config(home, content)
    cfg = load_config()
    assert cfg.self_hostname == "test-host"
    assert cfg.hosts["test-host"].ssh == "test-host"
    assert cfg.discovery.mode == "ssh"
    assert cfg.storage.state_root == home / ".local" / "share" / "croam"


# ---------------------------------------------------------------------------
# Test 2: missing self.hostname raises ConfigError with correct field
# ---------------------------------------------------------------------------


def test_load_missing_self_hostname(home: Path) -> None:
    """Missing [self] table raises ConfigError(field='self.hostname')."""
    content = '[hosts.x]\nssh = "x"\n'
    _write_config(home, content)
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert exc_info.value.field == "self.hostname"


# ---------------------------------------------------------------------------
# Test 3: self not present in [hosts] raises ConfigError with correct field
# ---------------------------------------------------------------------------


def test_load_missing_self_in_hosts(home: Path) -> None:
    """Self hostname not in [hosts] raises ConfigError(field='hosts.<name>')."""
    content = '[self]\nhostname = "foo"\n\n[hosts.bar]\nssh = "bar"\n'
    _write_config(home, content)
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert exc_info.value.field == "hosts.foo"


# ---------------------------------------------------------------------------
# Test 4: invalid discovery.mode raises ConfigError listing valid options
# ---------------------------------------------------------------------------


def test_load_invalid_discovery_mode(home: Path) -> None:
    """Invalid discovery.mode raises ConfigError with field and valid options in reason."""
    content = _MINIMAL_TOML + '\n[discovery]\nmode = "wibble"\n'
    _write_config(home, content)
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert exc_info.value.field == "discovery.mode"
    assert exc_info.value.reason is not None
    # reason must mention the valid options
    assert "syncthing" in exc_info.value.reason
    assert "ssh" in exc_info.value.reason
    assert "hybrid" in exc_info.value.reason


# ---------------------------------------------------------------------------
# Test 5: state_root tilde expands against test HOME (not real user home)
# ---------------------------------------------------------------------------


def test_load_state_root_tilde_expansion(home: Path) -> None:
    """state_root '~/Sync/croam' expands to home/Sync/croam under test HOME."""
    content = _MINIMAL_TOML + '\n[storage]\nstate_root = "~/Sync/croam"\n'
    _write_config(home, content)
    cfg = load_config()
    assert cfg.storage.state_root == home / "Sync" / "croam"


# ---------------------------------------------------------------------------
# Test 6: invalid ownership.claim_verify raises ConfigError
# ---------------------------------------------------------------------------


def test_load_invalid_claim_verify(home: Path) -> None:
    """Invalid claim_verify raises ConfigError(field='ownership.claim_verify')."""
    content = _MINIMAL_TOML + '\n[ownership]\nclaim_verify = "wibble"\n'
    _write_config(home, content)
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert exc_info.value.field == "ownership.claim_verify"
    assert exc_info.value.reason is not None
    assert "local" in exc_info.value.reason
    assert "ssh-strict" in exc_info.value.reason


# ---------------------------------------------------------------------------
# Test 7: optional sections use defaults when absent
# ---------------------------------------------------------------------------


def test_load_uses_defaults_for_optional_sections(home: Path) -> None:
    """Minimal TOML with only [self] + [hosts.X] gets all defaults populated."""
    _write_config(home, _MINIMAL_TOML)
    cfg = load_config()
    assert cfg.discovery.mode == "syncthing"
    assert cfg.ownership.claim_verify == "ssh-strict"
    assert cfg.picker.last_window_days == 30
    assert cfg.picker.default_filter == "exact-pwd"
    assert cfg.shim.enabled is True
    assert cfg.shim.opt_out_env == "CROAM_NO_TMUX"


# ---------------------------------------------------------------------------
# Test 8: bootstrap_config writes skeleton, sets mode 0o600, loads correctly
# ---------------------------------------------------------------------------


def test_load_missing_config_file(home: Path) -> None:
    """load_config raises ConfigError(field='path') when the file doesn't exist."""
    missing = home / ".config" / "croam" / "config.toml"
    with pytest.raises(ConfigError) as exc_info:
        load_config(missing)
    assert exc_info.value.field == "path"


def test_load_missing_host_ssh(home: Path) -> None:
    """Host entry without ssh key raises ConfigError(field='hosts.X.ssh')."""
    content = '[self]\nhostname = "h"\n\n[hosts.h]\nsync = true\n'
    _write_config(home, content)
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert exc_info.value.field == "hosts.h.ssh"


def test_load_invalid_picker_filter(home: Path) -> None:
    """Invalid picker.default_filter raises ConfigError(field='picker.default_filter')."""
    content = _MINIMAL_TOML + '\n[picker]\ndefault_filter = "bad"\nlast_window_days = 30\n'
    _write_config(home, content)
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert exc_info.value.field == "picker.default_filter"


def test_load_invalid_picker_days(home: Path) -> None:
    """Non-positive last_window_days raises ConfigError(field='picker.last_window_days')."""
    content = _MINIMAL_TOML + '\n[picker]\ndefault_filter = "exact-pwd"\nlast_window_days = 0\n'
    _write_config(home, content)
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert exc_info.value.field == "picker.last_window_days"


def test_load_invalid_shim_opt_out(home: Path) -> None:
    """Empty shim.opt_out_env raises ConfigError(field='shim.opt_out_env')."""
    content = _MINIMAL_TOML + '\n[shim]\nenabled = true\nopt_out_env = ""\n'
    _write_config(home, content)
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    assert exc_info.value.field == "shim.opt_out_env"


def test_load_host_with_home_expanded(home: Path) -> None:
    """Host entry with explicit home path is expanded against test HOME."""
    content = '[self]\nhostname = "h"\n\n[hosts.h]\nssh = "h"\nhome = "~/remote-home"\n'
    _write_config(home, content)
    cfg = load_config()
    assert cfg.hosts["h"].home == home / "remote-home"


def test_bootstrap_writes_skeleton(home: Path) -> None:
    """bootstrap_config writes mode-0o600 file and loads a valid Config."""
    dest = home / ".config" / "croam" / "config.toml"
    cfg = bootstrap_config(dest)
    assert dest.exists()
    assert (dest.stat().st_mode & 0o777) == 0o600
    assert cfg.self_hostname == os.uname().nodename
    assert cfg.self_hostname in cfg.hosts
    # Re-load independently to confirm the file is valid TOML
    cfg2 = load_config()
    assert cfg2.self_hostname == cfg.self_hostname
    assert cfg2.storage.state_root == home / ".local" / "share" / "croam"
