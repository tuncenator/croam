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

    Phase 6 ships discover + render + launch. The dispatch table is filled in by Phase 7+;
    for now, every result raises NotImplementedError or returns 0 (after logging).
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

    # 5. Dispatch (Phase 7+ fills this in).
    if not selected:
        return 0  # cancel
    return _dispatch(expect_key=expect_key, selected=selected, ctx_obj=ctx_obj)


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


def _dispatch(*, expect_key: str, selected: list[picker_mod.PickerRow], ctx_obj: dict) -> int:
    """Phase 6: stub. Phase 7 maps expect_key -> verb.run()."""
    logger.info("picker selected expect_key={!r} n={}", expect_key, len(selected))
    raise NotImplementedError("Phase 7 wires the dispatch table")
