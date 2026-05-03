"""Default (no-verb) picker dispatch: discover -> render -> launch -> dispatch."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

from loguru import logger

from croam import picker as picker_mod
from croam.config import Config
from croam.hosts import HostStatus, probe_reachability
from croam.ownership import merge_assertions, read_local_assertions
from croam.sessions import ClaudeSession, discover_local_sessions


def run_picker(*, config: Config, home: Path, ctx_obj: dict) -> int:
    """Orchestrate: discover -> render -> launch -> dispatch.

    Phase 6 ships discover + render + launch. Phase 7 fills in the dispatch table.
    """
    # 1. Discover.
    sessions = discover_local_sessions(home)
    assertions_per_host = {
        config.self_hostname: read_local_assertions(
            config.storage.state_root, config.self_hostname
        ),
        # Peers added by Phase 9 / hybrid mode. Phase 6 reads only local for the picker.
    }
    merged_assertions = merge_assertions(assertions_per_host)

    host_statuses: dict[str, HostStatus] = {}
    if ctx_obj.get("all"):
        host_statuses = probe_reachability(list(config.hosts.keys()))
    else:
        # Local-only: synthesize a self-status without an SSH probe.
        host_statuses[config.self_hostname] = HostStatus(
            name=config.self_hostname,
            reachable=True,
            last_probed=datetime.now(tz=UTC),
            error=None,
        )

    # Phase 4 may not yet have lineage merged; Phase 6 stubs an empty dict.
    lineage: dict = {}  # Phase 9 fills in via lineage.json reads.

    # 1b. Reconcile outclaimed sessions before presenting.
    from croam.commands import reconcile as reconcile_mod

    reconcile_mod.reconcile_all(
        state_root=config.storage.state_root,
        hostname=config.self_hostname,
        home=home,
    )
    # Re-read after reconcile may have changed assertions.
    assertions_per_host = {
        config.self_hostname: read_local_assertions(
            config.storage.state_root, config.self_hostname
        ),
    }
    merged_assertions = merge_assertions(assertions_per_host)

    # 2. Apply pre-render filters.
    filtered_sessions = _apply_filters(sessions, merged_assertions, ctx_obj, home)

    # 3. Render.
    pwd = Path.cwd() if not ctx_obj.get("all") else None
    rows = picker_mod.render_rows(
        sessions=filtered_sessions,
        assertions=merged_assertions,
        host_statuses=host_statuses,
        pwd=pwd,
        lineage=lineage,
    )

    if not rows:
        logger.warning("no sessions match the current filter; try `croam --all`")
        return 0

    # 4. Launch.
    expect_key, selected = picker_mod.launch_picker(rows=rows, filter_pwd=None)

    # 5. Dispatch.
    if not selected:
        return 0  # cancel
    return _dispatch(
        expect_key=expect_key,
        selected=selected,
        ctx_obj=ctx_obj,
        config=config,
        home=home,
    )


def _apply_filters(
    sessions: list[ClaudeSession],
    assertions: Mapping[str, object],
    ctx_obj: dict,
    home: Path,
) -> list[ClaudeSession]:
    """Apply --orphans filter. Other filters (--host, --last) deferred to Phase 7."""
    orphans_only = ctx_obj.get("orphans", False)
    if orphans_only:
        return [s for s in sessions if s.sid not in assertions]
    return [s for s in sessions if s.sid in assertions]  # exclude orphans by default


def _dispatch(
    *,
    expect_key: str,
    selected: list[picker_mod.PickerRow],
    ctx_obj: dict,
    config: Config,
    home: Path,
) -> int:
    """Map fzf expect_key + selected rows to the right verb.

    Single-row dispatch:
      enter ("")  -> attach
      "p"         -> peek
      "ctrl-r"    -> re-run run_picker
      "c"         -> Phase 8: claim
      "f"         -> Phase 8: fork
      "C"         -> Phase 8: claim --here
      "F"         -> Phase 8: fork --here

    Multi-row dispatch:
      compute_action_intersection, refuse if key not in intersection, else iterate.
    """
    from croam.commands import attach, peek

    logger.info("picker dispatch expect_key={!r} n={}", expect_key, len(selected))

    if expect_key == "ctrl-r":
        return run_picker(config=config, home=home, ctx_obj=ctx_obj)

    # Claim and fork dispatch.
    if expect_key in ("c", "C"):
        from croam.commands import claim as claim_mod

        here = expect_key == "C"
        for row in selected:
            rc = claim_mod.run(
                row.sid,
                state_root=config.storage.state_root,
                hostname=config.self_hostname,
                home=home,
                config_path=home / ".config" / "croam" / "config.toml",
                here=here,
            )
            if rc != 0:
                return rc
        return 0
    if expect_key in ("f", "F"):
        from croam.commands import fork as fork_mod

        here = expect_key == "F"
        for row in selected:
            _fork_sid, rc = fork_mod.run(
                row.sid,
                state_root=config.storage.state_root,
                hostname=config.self_hostname,
                home=home,
                here=here,
            )
            if rc != 0:
                return rc
        return 0

    if len(selected) == 1:
        sid = selected[0].sid
        if expect_key == "":
            return attach.run(sid, ctx_obj, config, home)
        if expect_key == "p":
            return peek.run(sid, ctx_obj, config, home)
        # Unrecognised key: fall through to 0 (safe default).
        logger.warning("picker: unknown expect_key={!r}; ignoring", expect_key)
        return 0

    # Multi-row: compute intersection of allowed actions.
    allowed = picker_mod.compute_action_intersection(selected, self_hostname=config.self_hostname)
    if expect_key == "":
        key_action = "attach"
    elif expect_key == "p":
        key_action = "peek"
    else:
        logger.warning("picker: multi-row with unknown key={!r}; ignoring", expect_key)
        return 0

    if key_action not in allowed:
        logger.warning(
            "picker: action={!r} not in intersection={!r} for {} rows; ignoring",
            key_action,
            allowed,
            len(selected),
        )
        return 0

    rc = 0
    for row in selected:
        if key_action == "attach":
            rc = attach.run(row.sid, ctx_obj, config, home)
        elif key_action == "peek":
            rc = peek.run(row.sid, ctx_obj, config, home)
    return rc
