"""Diagnostic checks for croam installation health.

`croam doctor` exercises every layer: config, state_root, hosts, syncthing,
ownership, external tools, and conflict files. Exit 0 when no FAIL-level
results; exit 1 otherwise. WARN does not cause non-zero exit.
"""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import typer
from loguru import logger

from croam import proc, sync
from croam.config import Config, load_config
from croam.hosts import HostStatus, probe_reachability
from croam.ownership import merge_assertions, read_all_assertions

# ---------------------------------------------------------------------------
# Thresholds (monkeypatchable in tests)
# ---------------------------------------------------------------------------

SYNCTHING_WARN_AGE = timedelta(hours=1)
SYNCTHING_FAIL_AGE = timedelta(hours=24)
SSH_PROBE_TIMEOUT = 2.0
EXTERNAL_TOOLS = ("fzf", "tmux", "ssh", "claude")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticResult:
    """Single check result."""

    name: str
    level: Literal["OK", "WARN", "FAIL"]
    reason: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# Per-check functions
# ---------------------------------------------------------------------------


def check_config(config_path: Path) -> DiagnosticResult:
    """OK if file exists and loads. FAIL on parse/validation error."""
    if not config_path.exists():
        return DiagnosticResult(name="config", level="FAIL", reason=f"{config_path} does not exist")
    try:
        cfg = load_config(config_path)
        n_hosts = len(cfg.hosts)
        return DiagnosticResult(
            name="config",
            level="OK",
            reason=f"{config_path} exists, {n_hosts} host(s) configured",
        )
    except Exception as e:
        return DiagnosticResult(name="config", level="FAIL", reason=str(e))


def check_state_root_writable(state_root: Path) -> DiagnosticResult:
    """OK if state_root is a writable directory."""
    if not state_root.exists():
        return DiagnosticResult(
            name="state_root", level="FAIL", reason=f"{state_root} does not exist"
        )
    if not state_root.is_dir():
        return DiagnosticResult(
            name="state_root", level="FAIL", reason=f"{state_root} is not a directory"
        )
    try:
        fd, tmp = tempfile.mkstemp(prefix=".croam-doctor-", dir=state_root)
        os.close(fd)
        os.unlink(tmp)
        return DiagnosticResult(name="state_root", level="OK", reason=f"{state_root} writable")
    except OSError as e:
        return DiagnosticResult(
            name="state_root", level="FAIL", reason=f"{state_root} not writable: {e}"
        )


def check_external_tools() -> list[DiagnosticResult]:
    """One result per tool in EXTERNAL_TOOLS."""
    results: list[DiagnosticResult] = []
    for tool in EXTERNAL_TOOLS:
        path = shutil.which(tool)
        if path is None:
            results.append(DiagnosticResult(name=tool, level="FAIL", reason="not found on PATH"))
            continue
        # Try to get version
        try:
            r = proc.run([tool, "--version"], timeout=SSH_PROBE_TIMEOUT)
            version = r.stdout.strip().split("\n")[0][:60] if r.returncode == 0 else None
        except Exception:
            version = None
        reason = version if version else f"present ({path})"
        results.append(DiagnosticResult(name=tool, level="OK", reason=reason))
    return results


def check_hosts(config: Config) -> list[DiagnosticResult]:
    """One result per peer host. WARN (not FAIL) when unreachable."""
    peers = [h for h in config.hosts if h != config.self_hostname]
    if not peers:
        return [DiagnosticResult(name="hosts", level="OK", reason="only self configured")]
    ssh_aliases = [config.hosts[h].ssh for h in peers]
    statuses = probe_reachability(ssh_aliases, timeout_s=SSH_PROBE_TIMEOUT)
    results: list[DiagnosticResult] = []
    for peer in peers:
        alias = config.hosts[peer].ssh
        status: HostStatus | None = statuses.get(alias)
        if status is None or not status.reachable:
            err = status.error if status else "probe failed"
            results.append(DiagnosticResult(name=peer, level="WARN", reason=f"ssh failed: {err}"))
        else:
            results.append(DiagnosticResult(name=peer, level="OK", reason="ssh ok"))
    return results


def check_syncthing(state_root: Path, config: Config) -> list[DiagnosticResult]:
    """One result per sync-enabled peer. OK/WARN/FAIL by freshness."""
    if config.discovery.mode == "ssh":
        return [
            DiagnosticResult(
                name="syncthing",
                level="OK",
                reason="not in use (discovery_mode=ssh)",
            )
        ]
    peers = [h for h in config.hosts if h != config.self_hostname and config.hosts[h].sync]
    if not peers:
        return [DiagnosticResult(name="syncthing", level="OK", reason="no sync-enabled peers")]
    results: list[DiagnosticResult] = []
    for peer in peers:
        age = sync.mirror_freshness(state_root, peer)
        if age is None:
            results.append(
                DiagnosticResult(
                    name=peer,
                    level="FAIL",
                    reason="mirror missing (syncthing never delivered)",
                )
            )
        elif age > SYNCTHING_FAIL_AGE:
            results.append(
                DiagnosticResult(
                    name=peer,
                    level="FAIL",
                    reason=f"mirror stale (last sync {_format_age(age)} ago)",
                )
            )
        elif age > SYNCTHING_WARN_AGE:
            results.append(
                DiagnosticResult(
                    name=peer,
                    level="WARN",
                    reason=f"mirror stale (last sync {_format_age(age)} ago)",
                )
            )
        else:
            results.append(
                DiagnosticResult(
                    name=peer,
                    level="OK",
                    reason=f"mirror fresh (last sync {_format_age(age)} ago)",
                )
            )
    return results


def check_ownership_consistency(state_root: Path, hostnames: list[str]) -> list[DiagnosticResult]:
    """Detect tie-timestamp conflicts in merged ownership view."""
    logger.debug("doctor: checking ownership consistency for {}", hostnames)
    all_assertions = read_all_assertions(state_root)
    merged = merge_assertions(all_assertions)

    # Detect ties: same sid claimed by two hosts at the exact same timestamp
    ties: list[tuple[str, str, str]] = []
    for sid, winner in merged.items():
        for hostname, host_assertions in all_assertions.items():
            if hostname == winner.owner:
                continue
            other = host_assertions.get(sid)
            if other is None:
                continue
            if other.asserted_at == winner.asserted_at and other.owner != winner.owner:
                ties.append((sid, winner.owner, other.owner))

    if not ties:
        return [DiagnosticResult(name="ownership", level="OK", reason="no conflicts")]

    details = "\n".join(f"  {sid}: {a} vs {b} (same timestamp)" for sid, a, b in ties)
    return [
        DiagnosticResult(
            name="ownership",
            level="WARN",
            reason=f"{len(ties)} ownership tie(s) detected",
            detail=details,
        )
    ]


def check_conflict_files(state_root: Path) -> DiagnosticResult:
    """FAIL if syncthing conflict files exist under state_root."""
    conflicts = sync.detect_conflict_files(state_root)
    if not conflicts:
        return DiagnosticResult(name="conflict files", level="OK", reason="none")
    detail = "\n".join(f"  {p}" for p in conflicts)
    return DiagnosticResult(
        name="conflict files",
        level="FAIL",
        reason=f"{len(conflicts)} conflict file(s) found",
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def bootstrap_config_if_missing(config_path: Path, default_state_root: Path) -> bool:
    """Write a minimal default config if config_path does not exist. Returns True if written."""
    if config_path.exists():
        return False
    hostname = socket.gethostname()
    home_str = os.path.expanduser("~")
    content = (
        f'[self]\nhostname = "{hostname}"\n\n'
        f'[hosts.{hostname}]\nssh = "{hostname}"\n'
        f'home = "{home_str}"\nsync = false\n\n'
        f"[storage]\n"
        f'state_root = "{default_state_root}"\n\n'
        f"[discovery]\n"
        f'mode = "ssh"\n\n'
        f"[ownership]\n"
        f'claim_verify = "local"\n\n'
        f"[picker]\n"
        f'default_filter = "exact-pwd"\n'
        f"last_window_days = 30\n\n"
        f"[shim]\n"
        f"enabled = false\n"
        f'opt_out_env = "CROAM_NO_TMUX"\n'
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content, encoding="utf-8")
    config_path.chmod(0o600)
    return True


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


def _format_age(td: timedelta) -> str:
    """Format a timedelta as a human-readable age string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m"
    if total_seconds < 86400:
        hours = total_seconds // 3600
        mins = (total_seconds % 3600) // 60
        if mins:
            return f"{hours}h{mins}m"
        return f"{hours}h"
    days = total_seconds // 86400
    return f"{days}d"


def _format_results(
    results: list[DiagnosticResult],
    started_at: datetime,
) -> str:
    """Build the ASCII doctor report."""
    lines: list[str] = []
    ts = started_at.strftime("%Y-%m-%dT%H:%MZ")
    lines.append(f"croam doctor ({ts})")
    lines.append("=" * 16)

    # Group results by section
    groups: dict[str, list[DiagnosticResult]] = {}
    singles: list[DiagnosticResult] = []
    group_order: list[str] = []

    # Determine groups vs singles
    GROUP_NAMES = {"hosts", "syncthing", "external tools"}
    for r in results:
        # If name contains a dot or matches group prefixes, it's a group entry
        if r.name in ("config", "state_root", "ownership", "conflict files"):
            singles.append(r)
        elif r.name in GROUP_NAMES:
            # Singleton group entry (e.g. "only self configured")
            singles.append(r)
        else:
            # Determine which group this belongs to
            # Check context by looking at where this result was placed
            group_name = _infer_group(r, results)
            if group_name not in groups:
                groups[group_name] = []
                group_order.append(group_name)
            groups[group_name].append(r)

    # Render in order: config, state_root, hosts group, syncthing group,
    # ownership, external tools group, conflict files
    rendered_sections: set[str] = set()

    for r in results:
        if r.name in ("config", "state_root", "ownership", "conflict files"):
            if r.name in rendered_sections:
                continue
            rendered_sections.add(r.name)
            lines.append(f"{r.name + ':':<16}[{r.level}]   {r.reason}")
            if r.detail:
                lines.append(r.detail)
        elif r.name in GROUP_NAMES:
            if r.name in rendered_sections:
                continue
            rendered_sections.add(r.name)
            lines.append(f"{r.name + ':':<16}[{r.level}]   {r.reason}")
        else:
            # This is a group entry; find and render the group header if not done
            group = _infer_group(r, results)
            if group not in rendered_sections:
                rendered_sections.add(group)
                lines.append(f"{group}:")
                for entry in groups.get(group, []):
                    lines.append(f"  {entry.name:<12}[{entry.level}]   {entry.reason}")
                    if entry.detail:
                        lines.append(entry.detail)

    # Summary line
    warnings = sum(1 for r in results if r.level == "WARN")
    failures = sum(1 for r in results if r.level == "FAIL")
    w_word = "warning" if warnings == 1 else "warnings"
    f_word = "failure" if failures == 1 else "failures"
    lines.append("")
    lines.append(f"Summary: {warnings} {w_word}, {failures} {f_word}")
    return "\n".join(lines)


def _infer_group(r: DiagnosticResult, all_results: list[DiagnosticResult]) -> str:
    """Infer which group section a result belongs to based on position in results list."""
    # We place results in known order: config, state_root, hosts..., syncthing...,
    # ownership, tools..., conflict files
    # Find index of this result
    idx = 0
    for i, item in enumerate(all_results):
        if item is r:
            idx = i
            break

    # Look backwards for section markers
    # hosts entries come after state_root and before syncthing/ownership
    # tools entries come after ownership
    seen_ownership = False
    for i in range(idx - 1, -1, -1):
        if all_results[i].name == "ownership":
            seen_ownership = True
            break
        if all_results[i].name in ("config", "state_root"):
            break

    if seen_ownership:
        return "external tools"

    # Check if we're past the hosts section (look for syncthing markers)
    # Simple heuristic: if any earlier entry in this group relates to syncthing
    # keywords in reason
    for i in range(idx - 1, -1, -1):
        if all_results[i].name in ("config", "state_root", "ownership", "conflict files"):
            break
        if "mirror" in all_results[i].reason or "syncthing" in all_results[i].reason:
            return "syncthing"
        if "ssh" in all_results[i].reason:
            return "hosts"

    # Default based on reason content
    if "mirror" in r.reason or "syncthing" in r.reason or "sync" in r.reason:
        return "syncthing"
    if "ssh" in r.reason:
        return "hosts"
    # Could be a tool
    if r.name in EXTERNAL_TOOLS:
        return "external tools"
    return "hosts"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_doctor(config_path: Path, home: Path) -> int:
    """Top-level doctor orchestrator. Returns 0 if no FAILs, else 1."""
    started_at = datetime.now(UTC)
    default_state_root = home / ".local" / "share" / "croam"

    bootstrapped = bootstrap_config_if_missing(config_path, default_state_root)
    if bootstrapped:
        typer.echo(f"bootstrapped default config at {config_path}; please review and edit")

    results: list[DiagnosticResult] = []

    # 1. Config
    results.append(check_config(config_path))

    # Load config for subsequent checks (bail gracefully if config is broken)
    try:
        config = load_config(config_path)
    except Exception:
        # Config check already recorded FAIL; skip remaining checks
        results.append(
            DiagnosticResult(name="state_root", level="FAIL", reason="skipped (config failed)")
        )
        typer.echo(_format_results(results, started_at))
        return 1

    state_root = config.storage.state_root

    # 2. State root
    results.append(check_state_root_writable(state_root))

    # 3. Hosts
    host_results = check_hosts(config)
    results.extend(host_results)

    # 4. Syncthing
    sync_results = check_syncthing(state_root, config)
    results.extend(sync_results)

    # 5. Ownership
    ownership_results = check_ownership_consistency(state_root, list(config.hosts.keys()))
    results.extend(ownership_results)

    # 6. External tools
    tool_results = check_external_tools()
    results.extend(tool_results)

    # 7. Conflict files
    results.append(check_conflict_files(state_root))

    # Format and print
    typer.echo(_format_results(results, started_at))

    # Exit code
    has_fail = any(r.level == "FAIL" for r in results)
    return 1 if has_fail else 0
