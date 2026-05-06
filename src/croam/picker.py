"""fzf picker: row layout, multi-select intersection, subprocess orchestration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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
    glyph: str  # column 2 (displayed) -- "●" reachable, "○" unreachable, "?" unknown
    status_word: str  # column 3 (hidden filter)
    reach_word: str  # column 4 (hidden filter)
    cwd_word: str  # column 5 (hidden filter)
    host: str  # column 6 (displayed)
    last: str  # column 7 (displayed)
    cwd_display: str  # column 8 (displayed)
    name: str  # column 9 (displayed)


# ---------------------------------------------------------------------------
# Pure formatting helpers
# ---------------------------------------------------------------------------


def fish_truncate_path(path: str, home: str) -> str:
    """Truncate a filesystem path fish-shell style.

    Replaces home prefix with ~, then abbreviates each intermediate component
    to its first character, keeping the last component in full.

    Examples (home=/home/tunc):
        /home/tunc/Programs/onlayer-x/internal/iam -> ~/P/o/i/iam
        /home/tunc/Programs/croam                  -> ~/P/croam
        /home/tunc                                 -> ~
        /opt/services/myapp                        -> /o/s/myapp
        /                                          -> /
        /usr                                       -> /usr
    """
    # Normalise home: strip trailing slash.
    home = home.rstrip("/")

    # Expand leading ~ in path using the provided home.
    if path == "~":
        return "~"
    if path.startswith("~/"):
        path = home + path[1:]

    # Check for exact match with home.
    if path == home:
        return "~"

    # Check for home prefix.
    home_prefix = home + "/"
    if path.startswith(home_prefix):
        rest = path[len(home_prefix):]
        prefix = "~/"
    elif path == "/":
        return "/"
    else:
        # Absolute path with no home prefix.
        # Strip leading slash, split, re-add root marker.
        rest = path.lstrip("/")
        prefix = "/"

    parts = rest.split("/")

    # Single component: nothing to abbreviate.
    if len(parts) == 1:
        return prefix + parts[0]

    # Abbreviate all but the last component.
    abbreviated: list[str] = []
    for part in parts[:-1]:
        if part.startswith(".") and len(part) > 1:
            # Dotfile: keep dot + first char after dot.
            abbreviated.append("." + part[1])
        elif part:
            abbreviated.append(part[0])
        else:
            abbreviated.append(part)

    return prefix + "/".join(abbreviated) + "/" + parts[-1]


def extract_first_user_message(jsonl_path: Path, max_chars: int = 80) -> str | None:
    """Return the first non-empty user message text from a JSONL transcript.

    Reads line by line, skipping non-user entries and empty content.
    Truncates to max_chars characters, appending '...' if truncated.
    Returns None if the file is missing/unreadable or has no non-empty user message.
    """
    # Import here to avoid circular import at module load time while keeping
    # _extract_text reuse. The function is called at row-render time, not import time.
    from croam.transcript import _extract_text

    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.debug("extract_first_user_message: cannot read {}: {}", jsonl_path, e)
        return None

    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "user":
            continue
        message = obj.get("message", "")
        text = _extract_text(message).strip()
        if not text:
            continue
        if len(text) > max_chars:
            return text[:max_chars] + "..."
        return text

    return None


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
    """Return filled circle if reachable, open circle if unreachable, '?' if unknown."""
    if host_status is None:
        return "?"
    return "●" if host_status.reachable else "○"


# ANSI color codes per status_word.
_STATUS_ANSI: dict[str, str] = {
    "running-idle": "\033[32m",   # green
    "running-busy": "\033[33m",   # yellow
    "archived": "\033[90m",       # gray (bright black)
    "unreachable": "\033[2m",     # dim
}
_ANSI_RESET = "\033[0m"


def colorize_glyph(glyph: str, status_word: str) -> str:
    """Wrap glyph in ANSI escape codes based on status_word.

    Returns the glyph unchanged for unknown status words.
    """
    code = _STATUS_ANSI.get(status_word)
    if code is None:
        return glyph
    return f"{code}{glyph}{_ANSI_RESET}"


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
        glyph = colorize_glyph(glyph, status_word)
        reach_word = "reachable" if (hs is not None and hs.reachable) else "unreachable"

        # Resolve cwd presence on local fs.
        cwd_normalized = getattr(assertion, "cwd_normalized", str(session.cwd))
        cwd_path = _resolve_cwd(cwd_normalized, host_homes)
        cwd_word = "present" if cwd_path.is_dir() else "missing-cwd"

        last = format_last_column(session.updated_at_ms, now)
        raw_cwd = cwd_normalized if assertion else str(session.cwd)
        cwd_display = fish_truncate_path(raw_cwd, str(Path.home()))

        # Build name with optional lineage tag.
        base_name = session.name
        if base_name is None:
            base_name = extract_first_user_message(session.transcript_path) or session.sid[:8]
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
    """Tab-join columns and newline-terminate for fzf stdin.

    Displayed columns (host, last, cwd_display) are left-padded to their max
    width so columns stay aligned regardless of hostname length.
    """
    if not rows:
        return ""
    host_w = max(len(_scrub(r.host)) for r in rows)
    last_w = max(len(_scrub(r.last)) for r in rows)
    cwd_w = max(len(_scrub(r.cwd_display)) for r in rows)
    lines = []
    for r in rows:
        cols = [
            _scrub(r.sid),
            _scrub(r.glyph),
            _scrub(r.status_word),
            _scrub(r.reach_word),
            _scrub(r.cwd_word),
            _scrub(r.host).ljust(host_w),
            _scrub(r.last).rjust(last_w),
            _scrub(r.cwd_display).ljust(cwd_w),
            _scrub(r.name),
        ]
        lines.append("\t".join(cols))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# fzf argv construction (two-mode: Filter -> Action)
# ---------------------------------------------------------------------------

_FILTER_HEADER = "type to filter | enter=select | ctrl-r=reload"
_ACTION_HEADER = (
    "enter:attach  p:peek  c:claim  C:claim-here  f:fork  F:fork-here  esc:back"
)


def build_fzf_argv(
    filter_pwd: Path | None,
    *,
    keyfile: str,
) -> list[str]:
    """Construct the fzf argv with two-mode bindings.

    Filter mode (initial): user types freely, action keys unbound.
    Action mode (after Enter): action keys active, header shows hotkeys.
    """
    action_hdr = _ACTION_HEADER
    filter_hdr = _FILTER_HEADER

    # Enter: in filter mode -> transition to action mode.
    #         in action mode -> accept (attach).
    mode_file = keyfile + ".mode"
    enter_transform = (
        f"transform:if [[ -f '{mode_file}' ]]; then"
        f"  echo 'accept';"
        f" else"
        f"  touch '{mode_file}';"
        f"  echo 'unbind(change)+change-prompt(> )"
        f"+change-header({action_hdr})"
        f"+rebind(p,c,f,C,F)';"
        f" fi"
    )

    # Esc: in action mode -> back to filter mode.
    #       in filter mode -> abort.
    esc_transform = (
        f"transform:if [[ -f '{mode_file}' ]]; then"
        f"  rm -f '{mode_file}';"
        f"  echo 'change-prompt(filter> )"
        f"+change-header({filter_hdr})"
        f"+unbind(p,c,f,C,F)+rebind(change)';"
        f" else"
        f"  echo 'abort';"
        f" fi"
    )

    argv = [
        "fzf",
        "--multi",
        "--ansi",
        "--delimiter=\t",
        "--with-nth=2,6,7,8,9",
        "--prompt=filter> ",
        f"--header={filter_hdr}",
        "--height=80%",
        "--layout=reverse",
        "--preview=croam preview {1}",
        "--preview-window=right:50%:wrap",
        # Tab for multi-select works in both modes.
        "--bind=tab:toggle+down",
        "--bind=shift-tab:toggle+up",
        '--bind=multi:transform-header:echo "$FZF_SELECT_COUNT/$FZF_MATCH_COUNT selected"',
        # Mode transitions.
        f"--bind=enter:{enter_transform}",
        f"--bind=esc:{esc_transform}",
        # Action keys: unbound at start, rebound when entering action mode.
        f"--bind=p:execute-silent(echo p > {keyfile})+accept",
        f"--bind=c:execute-silent(echo c > {keyfile})+accept",
        f"--bind=f:execute-silent(echo f > {keyfile})+accept",
        f"--bind=C:execute-silent(echo C > {keyfile})+accept",
        f"--bind=F:execute-silent(echo F > {keyfile})+accept",
        "--bind=start:unbind(p,c,f,C,F)",
        # ctrl-r always available (no conflict with typing).
        "--expect=ctrl-r",
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

    expect_key="" means plain Enter (attach).
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

    # Temp file for action key communication from fzf bindings.
    keyfd, keyfile = tempfile.mkstemp(prefix="croam-key-")
    os.close(keyfd)
    mode_file = keyfile + ".mode"

    try:
        argv = [fzf_binary, *build_fzf_argv(filter_pwd, keyfile=keyfile)[1:]]
        stdin_data = format_input_lines(rows)

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

        # --expect line is always first (ctrl-r or empty).
        expect_key = lines[0]
        selected_lines = lines[1:]

        # If expect_key is empty, check the keyfile for action mode keys.
        if not expect_key:
            try:
                key_content = Path(keyfile).read_text().strip()
                if key_content:
                    expect_key = key_content
            except OSError:
                pass

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
    finally:
        import contextlib

        for f in (keyfile, mode_file):
            with contextlib.suppress(OSError):
                os.unlink(f)


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
