"""croam peek: read-only session view (live tmux or static transcript fallback)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from croam.config import Config
from croam.errors import SessionNotFound, SshError
from croam.hosts import probe_reachability
from croam.ownership import merge_assertions, read_all_assertions
from croam.paths import denormalize_cwd, encode_cwd
from croam.tmux import has_session


def _peer_alias(owner: str, config: Config) -> str:
    """Return the ssh alias for a peer hostname. Falls back to the hostname itself."""
    entry = config.hosts.get(owner)
    if entry is not None:
        return entry.ssh
    return owner


def run(
    sid: str,
    ctx_obj: dict[str, Any],
    config: Config,
    home: Path,
    *,
    here_on_owner: bool = False,
    no_exec: bool | None = None,
) -> int:
    """Peek at a session: read-only tmux attach, or static transcript render.

    Dispatch matrix (owner_locality x reachability x tmux_exists):
      - local + tmux exists     -> tmux-peek (attach -r -t)
      - local + no tmux         -> static-transcript from home/.claude/projects/
      - remote + reachable      -> ssh-recurse with --here-on-owner
      - remote + unreachable    -> static-transcript-mirror from state_root/<owner>/projects/
      - remote + unreachable + no mirror -> SshError
    """
    resolved_no_exec: bool = (
        no_exec if no_exec is not None else os.environ.get("CROAM_NO_EXEC") == "1"
    )

    sock_env = os.environ.get("CROAM_TMUX_SOCK")
    sock: Path | None = Path(sock_env) if sock_env else None

    # Resolve owner.
    if here_on_owner:
        owner = config.self_hostname
    else:
        per_host = read_all_assertions(config.storage.state_root)
        merged = merge_assertions(per_host)
        if sid not in merged:
            raise SessionNotFound(f"session {sid!r} not found in any ownership records")
        owner = merged[sid].owner
        assertion = merged[sid]

    if here_on_owner:
        # Re-read to get the assertion for cwd.
        per_host_local = read_all_assertions(config.storage.state_root)
        merged_local = merge_assertions(per_host_local)
        assertion = merged_local.get(sid)

    is_local = here_on_owner or (owner == config.self_hostname)

    if is_local:
        session_name = f"claude-{sid}"
        tmux_exists = has_session(session_name, sock)

        if tmux_exists:
            # Live read-only attach.
            argv = [
                "tmux",
                *(["-S", str(sock)] if sock else []),
                "attach",
                "-r",
                "-t",
                session_name,
            ]
            logger.info("peek: tmux-peek argv={}", argv)
            if resolved_no_exec:
                sys.stdout.write(json.dumps({"action": "tmux-peek", "argv": argv}) + "\n")
                return 0
            os.execvp(argv[0], argv)
            raise AssertionError("execvp returned")

        # No live tmux -- render static transcript.
        transcript_path: Path | None = None
        if assertion is not None:
            try:
                cwd_abs = denormalize_cwd(assertion.cwd_normalized, home)
                encoded = encode_cwd(cwd_abs)
                transcript_path = home / ".claude" / "projects" / encoded / f"{sid}.jsonl"
            except (ValueError, Exception) as e:
                logger.warning("peek: could not resolve transcript path: {}", e)

        if transcript_path is None:
            transcript_path = home / ".claude" / "projects" / f"unknown-{sid}" / f"{sid}.jsonl"

        argv_repr = ["render_static_transcript", str(transcript_path)]
        logger.info("peek: static-transcript path={}", transcript_path)
        if resolved_no_exec:
            sys.stdout.write(
                json.dumps({"action": "static-transcript", "argv": argv_repr}) + "\n"
            )
            return 0
        from croam.transcript import render_static_transcript
        return render_static_transcript(transcript_path)

    # Remote owner.
    probe = probe_reachability([owner])
    host_status = probe.get(owner)
    reachable = host_status is not None and host_status.reachable

    if reachable:
        peer_alias = _peer_alias(owner, config)
        argv = ["ssh", peer_alias, "croam", "peek", sid, "--here-on-owner"]
        logger.info("peek: ssh-recurse argv={}", argv)
        if resolved_no_exec:
            sys.stdout.write(json.dumps({"action": "ssh-recurse", "argv": argv}) + "\n")
            return 0
        os.execvp(argv[0], argv)
        raise AssertionError("execvp returned")

    # Remote + unreachable: try mirror.
    mirror_path: Path | None = None
    if assertion is not None:
        try:
            cwd_abs = denormalize_cwd(
                assertion.cwd_normalized,
                config.hosts[owner].home if owner in config.hosts and config.hosts[owner].home
                else home,
            )
            encoded = encode_cwd(cwd_abs)
            mirror_path = (
                config.storage.state_root / owner / "projects" / encoded / f"{sid}.jsonl"
            )
        except (ValueError, KeyError, Exception) as e:
            logger.warning("peek: could not resolve mirror path for owner={}: {}", owner, e)

    if mirror_path is not None and mirror_path.exists():
        argv_repr = ["render_static_transcript", str(mirror_path)]
        logger.info("peek: static-transcript-mirror path={}", mirror_path)
        if resolved_no_exec:
            sys.stdout.write(
                json.dumps({"action": "static-transcript-mirror", "argv": argv_repr}) + "\n"
            )
            return 0
        from croam.transcript import render_static_transcript
        return render_static_transcript(mirror_path)

    raise SshError(
        f"origin {owner} unreachable and no mirror found for session {sid!r}; "
        "no mirror available"
    )
