"""TOML config loader and frozen Config dataclass tree.

Single-read at process startup; all consumers receive an immutable Config.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from croam.errors import ConfigError

_DEFAULT_CONFIG_PATH = "~/.config/croam/config.toml"

_DISCOVERY_MODES = {"syncthing", "ssh", "hybrid"}
_CLAIM_VERIFY_MODES = {"local", "ssh-strict"}
_FILTER_MODES = {"exact-pwd", "project-root"}


@dataclass(frozen=True)
class HostEntry:
    """Configuration for a single host (local or remote)."""

    name: str
    ssh: str
    home: Path | None = None
    # TODO: Phase 3 will resolve home=None to os.path.expanduser("~") for local host,
    # or fail loudly for remote hosts with home=None.
    sync: bool = True


@dataclass(frozen=True)
class StorageConfig:
    """File-system location for croam's per-host state files."""

    state_root: Path


@dataclass(frozen=True)
class DiscoveryConfig:
    """How to discover session state across hosts."""

    mode: Literal["syncthing", "ssh", "hybrid"]


@dataclass(frozen=True)
class OwnershipConfig:
    """Policy for claiming session ownership."""

    claim_verify: Literal["local", "ssh-strict"]


@dataclass(frozen=True)
class PickerConfig:
    """Settings for the interactive fzf session picker."""

    default_filter: Literal["exact-pwd", "project-root"]
    last_window_days: int


@dataclass(frozen=True)
class ShimConfig:
    """Settings for the claude-in-tmux shim."""

    enabled: bool
    opt_out_env: str


@dataclass(frozen=True)
class Config:
    """Immutable top-level configuration. Loaded once at process startup.

    `hosts` is a dict[str, HostEntry] inside a frozen dataclass -- the dict
    itself is mutable by language but callers MUST treat it as read-only.
    """

    self_hostname: str
    hosts: dict[str, HostEntry]
    storage: StorageConfig
    discovery: DiscoveryConfig
    ownership: OwnershipConfig
    picker: PickerConfig
    shim: ShimConfig


def _expand(s: str) -> Path:
    """Expand ~ in a path string and return a Path."""
    return Path(os.path.expanduser(s))


def _parse_hosts(raw_hosts: dict[str, object], self_hostname: str) -> dict[str, HostEntry]:
    """Parse [hosts] table into a dict of HostEntry. Validates self is present."""
    if self_hostname not in raw_hosts:
        raise ConfigError(
            f"Self host {self_hostname!r} not found in [hosts]",
            field=f"hosts.{self_hostname}",
            reason="self host must be present in [hosts]",
        )
    entries: dict[str, HostEntry] = {}
    for name, raw in raw_hosts.items():
        raw_dict = raw if isinstance(raw, dict) else {}
        ssh = raw_dict.get("ssh", "")
        if not isinstance(ssh, str) or not ssh:
            raise ConfigError(
                f"hosts.{name}.ssh must be a non-empty string",
                field=f"hosts.{name}.ssh",
                reason="required field missing or empty",
            )
        raw_home = raw_dict.get("home")
        home: Path | None = _expand(raw_home) if isinstance(raw_home, str) else None
        sync = bool(raw_dict.get("sync", True))
        entries[name] = HostEntry(name=name, ssh=ssh, home=home, sync=sync)
    return entries


def load_config(path: Path | None = None) -> Config:
    """Load and validate config from `path` (default ~/.config/croam/config.toml).

    Raises ConfigError on missing file or invalid schema.
    """
    if path is None:
        path = Path(os.path.expanduser(_DEFAULT_CONFIG_PATH))

    if not path.exists():
        raise ConfigError(
            f"Config not found at {path}",
            field="path",
            reason=f"config not found at {path}; run 'croam doctor' to bootstrap",
        )

    raw = tomllib.loads(path.read_text())

    # --- [self] ---
    raw_self = raw.get("self", {})
    self_hostname = raw_self.get("hostname", "") if isinstance(raw_self, dict) else ""
    if not isinstance(self_hostname, str) or not self_hostname:
        raise ConfigError(
            "self.hostname is required",
            field="self.hostname",
            reason="required field missing",
        )

    # --- [hosts] ---
    raw_hosts = raw.get("hosts", {})
    if not isinstance(raw_hosts, dict):  # pragma: no cover
        raw_hosts = {}  # pragma: no cover
    hosts = _parse_hosts(raw_hosts, self_hostname)

    # --- [storage] ---
    raw_storage = raw.get("storage", {})
    if isinstance(raw_storage, dict):
        raw_state_root = raw_storage.get("state_root", "~/.local/share/croam")
    else:  # pragma: no cover
        raw_state_root = "~/.local/share/croam"  # pragma: no cover
    if not isinstance(raw_state_root, str):  # pragma: no cover
        raise ConfigError(  # pragma: no cover
            "storage.state_root must be a string",
            field="storage.state_root",
            reason="must be a string path",
        )
    state_root = _expand(raw_state_root)
    storage = StorageConfig(state_root=state_root)

    # --- [discovery] ---
    raw_discovery = raw.get("discovery", {})
    discovery_mode: str = (
        raw_discovery.get("mode", "syncthing") if isinstance(raw_discovery, dict) else "syncthing"
    )
    if discovery_mode not in _DISCOVERY_MODES:
        raise ConfigError(
            f"Invalid discovery.mode: {discovery_mode!r}",
            field="discovery.mode",
            reason=f"discovery.mode must be one of {_DISCOVERY_MODES!r}, got {discovery_mode!r}",
        )
    discovery = DiscoveryConfig(mode=discovery_mode)  # type: ignore[arg-type]

    # --- [ownership] ---
    raw_ownership = raw.get("ownership", {})
    claim_verify: str = (
        raw_ownership.get("claim_verify", "ssh-strict")
        if isinstance(raw_ownership, dict)
        else "ssh-strict"
    )
    if claim_verify not in _CLAIM_VERIFY_MODES:
        raise ConfigError(
            f"Invalid ownership.claim_verify: {claim_verify!r}",
            field="ownership.claim_verify",
            reason=f"ownership.claim_verify must be one of {_CLAIM_VERIFY_MODES!r}, got {claim_verify!r}",
        )
    ownership = OwnershipConfig(claim_verify=claim_verify)  # type: ignore[arg-type]

    # --- [picker] ---
    raw_picker = raw.get("picker", {})
    if isinstance(raw_picker, dict):
        default_filter: str = raw_picker.get("default_filter", "exact-pwd")
        last_window_days: int = raw_picker.get("last_window_days", 30)
    else:  # pragma: no cover
        default_filter = "exact-pwd"  # pragma: no cover
        last_window_days = 30  # pragma: no cover
    if default_filter not in _FILTER_MODES:
        raise ConfigError(
            f"Invalid picker.default_filter: {default_filter!r}",
            field="picker.default_filter",
            reason=f"picker.default_filter must be one of {_FILTER_MODES!r}, got {default_filter!r}",
        )
    if not isinstance(last_window_days, int) or last_window_days <= 0:
        raise ConfigError(
            "picker.last_window_days must be a positive integer",
            field="picker.last_window_days",
            reason="must be a positive integer",
        )
    picker = PickerConfig(default_filter=default_filter, last_window_days=last_window_days)  # type: ignore[arg-type]

    # --- [shim] ---
    raw_shim = raw.get("shim", {})
    if isinstance(raw_shim, dict):
        shim_enabled: bool = raw_shim.get("enabled", True)
        shim_opt_out: str = raw_shim.get("opt_out_env", "CROAM_NO_TMUX")
    else:  # pragma: no cover
        shim_enabled = True  # pragma: no cover
        shim_opt_out = "CROAM_NO_TMUX"  # pragma: no cover
    if not isinstance(shim_enabled, bool):  # pragma: no cover
        raise ConfigError(  # pragma: no cover
            "shim.enabled must be a boolean",
            field="shim.enabled",
            reason="must be true or false",
        )
    if not isinstance(shim_opt_out, str) or not shim_opt_out:
        raise ConfigError(
            "shim.opt_out_env must be a non-empty string",
            field="shim.opt_out_env",
            reason="must be a non-empty string",
        )
    shim = ShimConfig(enabled=shim_enabled, opt_out_env=shim_opt_out)

    return Config(
        self_hostname=self_hostname,
        hosts=hosts,
        storage=storage,
        discovery=discovery,
        ownership=ownership,
        picker=picker,
        shim=shim,
    )


def bootstrap_config(path: Path) -> Config:
    """Write a minimal-valid skeleton config to `path` and return the loaded Config.

    Creates parent directories. Uses os.uname().nodename as the hostname.
    Writes atomically via tmp -> os.replace with mode 0o600.
    """
    nodename = os.uname().nodename
    skeleton = f"""\
[self]
hostname = "{nodename}"

[hosts.{nodename}]
ssh = "{nodename}"
sync = true

[storage]
state_root = "~/.local/share/croam"

[discovery]
mode = "ssh"

[ownership]
claim_verify = "ssh-strict"

[picker]
default_filter = "exact-pwd"
last_window_days = 30

[shim]
enabled = true
opt_out_env = "CROAM_NO_TMUX"
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(skeleton)
    tmp.chmod(0o600)
    os.replace(tmp, path)
    return load_config(path)
