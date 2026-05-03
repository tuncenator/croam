"""croam fork: branch a new session from an existing JSONL transcript.

Self-contained, no SSH coordination. Generates uuid4 fork_sid, copies JSONL
(trimming trailing partial JSON), writes lineage + assertion + snapshot.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from croam.errors import SessionNotFound
from croam.ownership import Assertion, add_lineage, read_local_assertions, write_local_assertion
from croam.paths import encode_cwd, normalize_cwd
from croam.snapshots import write_snapshot


def _find_jsonl(home: Path, sid: str) -> Path | None:
    """Locate the JSONL transcript for sid under ~/.claude/projects/."""
    projects_dir = home / ".claude" / "projects"
    if not projects_dir.exists():
        return None
    for subdir in projects_dir.iterdir():
        if not subdir.is_dir():
            continue
        candidate = subdir / f"{sid}.jsonl"
        if candidate.exists():
            return candidate
    return None


def _copy_jsonl_trimmed(src: Path, dst: Path) -> int:
    """Copy JSONL from src to dst, trimming trailing incomplete JSON lines.

    Uses bytes to avoid UTF-8 mid-stream corruption. Returns the line count
    of the resulting file.
    """
    raw = src.read_bytes()
    lines = raw.split(b"\n")
    # Remove trailing empty line from split
    if lines and lines[-1] == b"":
        lines = lines[:-1]
    # Validate each line is parseable JSON; trim from the end
    valid_lines: list[bytes] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            json.loads(line)
            valid_lines.append(line)
        except json.JSONDecodeError:
            # Trailing partial line: stop here
            logger.warning("fork: trimming partial JSON line from {}", src)
            break

    dst.parent.mkdir(parents=True, exist_ok=True)
    content = b"\n".join(valid_lines) + b"\n" if valid_lines else b""
    dst.write_bytes(content)
    return len(valid_lines)


def run(
    sid: str,
    *,
    state_root: Path,
    hostname: str,
    home: Path,
    here: bool = False,
) -> tuple[str, int]:
    """Fork a session, creating a new JSONL + lineage + assertion + snapshot.

    Returns (fork_sid, exit_code). Raises SessionNotFound if source JSONL
    is missing.
    """
    # Locate source JSONL.
    src_path = _find_jsonl(home, sid)
    if src_path is None:
        raise SessionNotFound(f"cannot fork: JSONL for sid={sid!r} not found")

    # Determine target directory.
    if here:
        target_cwd = Path.cwd()
        encoded_target = encode_cwd(target_cwd)
        cwd_normalized = normalize_cwd(target_cwd, home)
    else:
        # Use the same project directory as the source.
        encoded_target = src_path.parent.name
        # Read cwd_normalized from existing assertion if available.
        local_assertions = read_local_assertions(state_root, hostname)
        if sid in local_assertions:
            cwd_normalized = local_assertions[sid].cwd_normalized
        else:
            # Fallback: derive from the encoded directory name.
            cwd_normalized = f"~/{encoded_target}"

    # Generate fork sid.
    fork_sid = str(uuid.uuid4())

    # Copy JSONL with partial-line trimming.
    dst_dir = home / ".claude" / "projects" / encoded_target
    dst_path = dst_dir / f"{fork_sid}.jsonl"
    line_count = _copy_jsonl_trimmed(src_path, dst_path)

    # Write lineage.
    fork_n = add_lineage(state_root, hostname, fork_sid, sid)
    logger.info("fork: sid={} -> fork_sid={} fork_n={}", sid, fork_sid, fork_n)

    # Write ownership assertion.
    fork_assertion = Assertion(
        sid=fork_sid,
        owner=hostname,
        asserted_at=datetime.now(UTC),
        action="create",
        cwd_normalized=cwd_normalized,
    )
    write_local_assertion(state_root, hostname, fork_assertion)

    # Write snapshot.
    write_snapshot(state_root, hostname, fork_sid, line_count)

    return fork_sid, 0
