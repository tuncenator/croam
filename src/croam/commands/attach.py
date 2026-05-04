"""croam attach: adopt a live session via tmux, recursing over SSH when remote."""

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
from croam.tmux import has_session


def _peer_alias(owner: str, config: Config) -> str:
    """Return the ssh alias for a peer hostname. Falls back to the hostname itself."""
    entry = config.hosts.get(owner)
    if entry is not None:
        return entry.ssh
    return owner


def run(
    sid: str | None,
    ctx_obj: dict[str, Any],
    config: Config,
    home: Path,
    *,
    here_on_owner: bool = False,
    no_exec: bool | None = None,
) -> int:
    """Attach to a session via tmux, SSHing to the owner if remote.

    Steps:
    1. Resolve no_exec precedence.
    2. If sid is None: delegate to picker.
    3. Resolve owner (skip when here_on_owner=True -- recursion guard).
    4. Branch on local vs. remote.
    5. Execute or emit plan JSON.
    """
    resolved_no_exec: bool = (
        no_exec if no_exec is not None else os.environ.get("CROAM_NO_EXEC") == "1"
    )

    if sid is None:
        from croam.commands import default as default_mod

        return default_mod.run_picker(config=config, home=home, ctx_obj=ctx_obj)

    sock_env = os.environ.get("CROAM_TMUX_SOCK")
    sock: Path | None = Path(sock_env) if sock_env else None

    # Resolve owner.
    if here_on_owner:
        # Recursion guard: treat as local regardless of ownership records.
        owner = config.self_hostname
    else:
        per_host = read_all_assertions(config.storage.state_root)
        merged = merge_assertions(per_host)
        if sid not in merged:
            raise SessionNotFound(f"session {sid!r} not found in any ownership records")
        owner = merged[sid].owner

    is_local = here_on_owner or (owner == config.self_hostname)

    if is_local:
        session_name = f"claude-{sid}"
        if has_session(session_name, sock):
            argv = [
                "tmux",
                *(["-S", str(sock)] if sock else []),
                "attach",
                "-t",
                session_name,
            ]
            action = "tmux-attach"
        else:
            argv = [
                "tmux",
                *(["-S", str(sock)] if sock else []),
                "new-session",
                "-A",
                "-s",
                session_name,
                "claude-real",
                "--resume",
                sid,
            ]
            action = "tmux-new-and-attach"

        logger.info("attach: {} argv={}", action, argv)
        if resolved_no_exec:
            sys.stdout.write(json.dumps({"action": action, "argv": argv}) + "\n")
            return 0
        os.execvp(argv[0], argv)
        raise AssertionError("execvp returned")

    # Remote owner: probe reachability.
    probe = probe_reachability([owner])
    host_status = probe.get(owner)
    reachable = host_status is not None and host_status.reachable

    if not reachable:
        raise SshError(
            f"origin {owner} unreachable; try 'croam peek {sid}' for read-only static transcript"
        )

    peer_alias = _peer_alias(owner, config)
    argv = ["ssh", "-t", peer_alias, f"bash -lc 'croam attach {sid} --here-on-owner'"]
    action = "ssh-recurse"

    logger.info("attach: {} argv={}", action, argv)
    if resolved_no_exec:
        sys.stdout.write(json.dumps({"action": action, "argv": argv}) + "\n")
        return 0
    os.execvp(argv[0], argv)
    raise AssertionError("execvp returned")
