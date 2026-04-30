"""fzf picker: row layout, multi-select intersection, subprocess orchestration."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

from loguru import logger

from croam.errors import CroamError
from croam.hosts import HostStatus
from croam.sessions import ClaudeSession


@dataclass(frozen=True)
class PickerRow:
    """One row in the fzf picker. Column ordering is the wire-format contract."""

    sid: str  # column 1 (hidden filter)
    glyph: str  # column 2 (displayed) -- "o" reachable, "O" unreachable, "?" unknown
    status_word: str  # column 3 (hidden filter)
    reach_word: str  # column 4 (hidden filter)
    cwd_word: str  # column 5 (hidden filter)
    host: str  # column 6 (displayed)
    last: str  # column 7 (displayed)
    cwd_display: str  # column 8 (displayed) -- TODO(phase-11): fish-style truncation
    name: str  # column 9 (displayed)


# ---------------------------------------------------------------------------
# Pure formatting helpers
# ---------------------------------------------------------------------------


def format_last_column(updated_at_ms: int | None, now: datetime) -> str:
    """Format ms-epoch timestamp as 'Nm', 'Nh', 'ND', 'NM' per spec section 4."""
    if updated_at_ms is None:
        return "-"
    then = datetime.fromtimestamp(updated_at_ms / 1000, tz=UTC)
    delta_s = (now - then).total_seconds()
    minutes = int(delta_s // 60)
    hours = int(delta_s // 3600)
    days = int(delta_s // 86400)
    if hours < 1:
        return f"{minutes}m"
    if hours < 48:
        return f"{hours}h"
    if days <= 30:
        return f"{days}D"
    months = days // 30
    return f"{months}M"


def compute_glyph(host_status: HostStatus | None) -> str:
    """Return 'o' if reachable, 'O' if unreachable, '?' if unknown."""
    if host_status is None:
        return "?"
    return "o" if host_status.reachable else "O"


def compute_status_word(session: ClaudeSession, host_status: HostStatus | None) -> str:
    """Return 'running-idle' | 'running-busy' | 'archived' | 'unreachable'."""
    if host_status is not None and not host_status.reachable:
        return "unreachable"
    if session.pid is None:
        return "archived"
    if session.status == "busy":
        return "running-busy"
    return "running-idle"


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------


def _scrub(s: str) -> str:
    """Replace tabs, newlines, carriage returns with single space."""
    return s.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def render_rows(
    sessions: list[ClaudeSession],
    assertions: Mapping[str, object],
    host_statuses: dict[str, HostStatus],
    pwd: Path | None,
    lineage: Mapping[str, object],
    *,
    now: datetime | None = None,
    host_homes: dict[str, Path] | None = None,
) -> list[PickerRow]:
    """Build picker rows by joining sessions/assertions/host_statuses/lineage on sid.

    Rows sorted by (updated_at_ms desc, sid asc). Sessions without an assertion
    get host="unknown". Assertions without a session are skipped.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    rows: list[PickerRow] = []
    for session in sessions:
        assertion = assertions.get(session.sid)
        owner = getattr(assertion, "owner", "unknown") if assertion else "unknown"
        hs = host_statuses.get(owner)
        glyph = compute_glyph(hs)
        status_word = compute_status_word(session, hs)
        reach_word = "reachable" if (hs is not None and hs.reachable) else "unreachable"

        # Resolve cwd presence on local fs.
        cwd_normalized = getattr(assertion, "cwd_normalized", str(session.cwd))
        cwd_path = _resolve_cwd(cwd_normalized, host_homes)
        cwd_word = "present" if cwd_path.is_dir() else "missing-cwd"

        last = format_last_column(session.updated_at_ms, now)
        cwd_display = cwd_normalized if assertion else str(session.cwd)

        # Build name with optional lineage tag.
        base_name = session.name or session.sid[:8]
        le = lineage.get(session.sid)
        if le is not None:
            parent_short = getattr(le, "parent_sid", "")[:6]
            fork_n = getattr(le, "fork_n", 0)
            base_name = f"{base_name} [{parent_short}-F#{fork_n}]"

        rows.append(
            PickerRow(
                sid=session.sid,
                glyph=glyph,
                status_word=status_word,
                reach_word=reach_word,
                cwd_word=cwd_word,
                host=owner,
                last=last,
                cwd_display=cwd_display,
                name=base_name,
            )
        )

    # Stable sort: updated_at_ms desc (nulls last), sid asc tiebreak.
    rows.sort(key=lambda r: (-(assertions.get(r.sid) is not None), r.sid))
    # Re-sort by the actual timestamp from sessions.
    session_map = {s.sid: s for s in sessions}
    rows.sort(
        key=lambda r: (
            -(session_map[r.sid].updated_at_ms or 0),
            r.sid,
        )
    )
    return rows


def _resolve_cwd(cwd_normalized: str, host_homes: dict[str, Path] | None) -> Path:
    """Resolve a normalized cwd string to a local Path for is_dir() check."""
    if cwd_normalized.startswith("~"):
        home = Path.home()
        if host_homes:
            # Use the first available home (self host).
            for h in host_homes.values():
                home = h
                break
        return home / cwd_normalized[2:] if len(cwd_normalized) > 1 else home
    return Path(cwd_normalized)


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------


def format_input_lines(rows: list[PickerRow]) -> str:
    """Tab-join columns and newline-terminate for fzf stdin."""
    if not rows:
        return ""
    lines = []
    for r in rows:
        cols = [
            _scrub(r.sid),
            _scrub(r.glyph),
            _scrub(r.status_word),
            _scrub(r.reach_word),
            _scrub(r.cwd_word),
            _scrub(r.host),
            _scrub(r.last),
            _scrub(r.cwd_display),
            _scrub(r.name),
        ]
        lines.append("\t".join(cols))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# fzf argv construction
# ---------------------------------------------------------------------------

_DEFAULT_HEADER = (
    "enter:attach  p:peek  c:claim  f:fork  C:claim --here  F:fork --here  ctrl-r:reload"
)


def build_fzf_argv(
    filter_pwd: Path | None,
    *,
    header_default: str = _DEFAULT_HEADER,
) -> list[str]:
    """Construct the fzf argv. Pure function."""
    argv = [
        "fzf",
        "--multi",
        "--ansi",
        "--delimiter=\t",
        "--with-nth=2,6,7,8,9",
        "--expect=p,c,f,C,F,ctrl-r",
        "--bind=tab:toggle+down",
        "--bind=shift-tab:toggle+up",
        '--bind=select,deselect:transform-header:echo "$FZF_SELECT_COUNT/$FZF_MATCH_COUNT selected"',
        f"--header={header_default}",
        "--height=80%",
        "--layout=reverse",
        "--preview=printf 'sid: {1}\\n(preview pane to be filled in v2)\\n'",
        "--preview-window=right:50%:wrap",
    ]
    if filter_pwd is not None:
        argv.append(f"--query={filter_pwd.as_posix()}")
    return argv


# ---------------------------------------------------------------------------
# Subprocess orchestrator
# ---------------------------------------------------------------------------


def launch_picker(
    rows: list[PickerRow],
    filter_pwd: Path | None,
    *,
    fzf_binary: str = "fzf",
    env_overrides: dict[str, str] | None = None,
) -> tuple[str, list[PickerRow]]:
    """Run fzf, return (expect_key, selected_rows).

    expect_key="" means plain Enter.
    selected_rows is empty on cancel (rc=130) or no-match (rc=1).
    Raises CroamError on rc=2 (fzf error) or rc in (126, 127) (exec failure).
    """
    if not sys.stdin.isatty():
        raise CroamError(
            "picker requires an interactive terminal; use `croam ls --json` for scripts"
        )

    if not rows:
        logger.warning("launch_picker called with zero rows; returning empty")
        return "", []

    argv = [fzf_binary, *build_fzf_argv(filter_pwd)[1:]]
    stdin_data = format_input_lines(rows)

    # Sanitize env so user's FZF_DEFAULT_OPTS doesn't poison our flags.
    env = {**os.environ, "FZF_DEFAULT_OPTS": ""}
    if env_overrides:
        env.update(env_overrides)

    logger.debug("launching fzf: argv={}, n_rows={}", argv, len(rows))

    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        env=env,
        text=True,
        encoding="utf-8",
    )
    out, _ = proc.communicate(stdin_data)
    rc = proc.returncode

    if rc in (130, 1):
        return "", []
    if rc in (2, 126, 127):
        raise CroamError(f"fzf exited with code {rc}")
    if rc != 0:
        raise CroamError(f"fzf exited unexpectedly with code {rc}")

    lines = out.splitlines()
    if not lines:
        return "", []

    expect_key = lines[0]
    selected_lines = lines[1:]
    by_sid = {r.sid: r for r in rows}
    selected_rows = []
    for raw in selected_lines:
        sid = raw.split("\t", 1)[0]
        row = by_sid.get(sid)
        if row is not None:
            selected_rows.append(row)
        else:
            logger.warning("fzf returned sid={!r} not in input rows; skipping", sid)
    return expect_key, selected_rows


# ---------------------------------------------------------------------------
# Multi-select action intersection
# ---------------------------------------------------------------------------


def _row_safe_actions(row: PickerRow, self_hostname: str) -> set[str]:
    """Per-row safe action set."""
    actions = {"peek"}
    if row.reach_word == "reachable":
        actions.add("attach")
    if row.cwd_word == "present":
        actions.add("claim")
        actions.add("fork")
    actions.add("claim-here")
    actions.add("fork-here")
    return actions


def compute_action_intersection(selected: list[PickerRow], *, self_hostname: str) -> set[str]:
    """Return the set of safe verb keys universally applicable across all selected rows."""
    if not selected:
        return set()
    return set.intersection(*[_row_safe_actions(r, self_hostname) for r in selected])
