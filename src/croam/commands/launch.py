"""Orchestrator for `croam launch`: wraps claude invocations in a tmux session."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from loguru import logger

from croam import shim, tmux
from croam.config import Config
from croam.errors import TmuxError
from croam.ownership import Assertion, write_local_assertion
from croam.paths import normalize_cwd


@dataclass(frozen=True)
class LaunchPlan:
    """The decided-upon plan before any side effects fire.

    Fields populated for every plan:
      mode: "wrap" or "passthrough"
      sid: the session id (resumed or freshly generated)
      claude_argv: the argv that will run `claude-real` (with --no-tmux stripped)
      cwd_normalized: the cwd to record on the assertion

    Fields populated only when mode == "wrap":
      tmux_session_name: e.g., "claude-<sid>"
      tmux_new_argv: full `tmux ... new-session -d -s ... -- claude-real ...` argv
      tmux_attach_argv: full `tmux ... attach -t ...` argv

    Fields populated only when mode == "passthrough":
      passthrough_argv: full argv passed to `os.execvp` (claude_argv with executable resolved)
    """

    mode: Literal["wrap", "passthrough"]
    sid: str
    claude_argv: list[str]
    cwd_normalized: str
    tmux_session_name: str | None = None
    tmux_new_argv: list[str] | None = None
    tmux_attach_argv: list[str] | None = None
    passthrough_argv: list[str] | None = None


def build_launch_plan(
    argv: list[str],
    env: dict[str, str],
    stdin_isatty: bool,
    cwd: Path,
    home: Path,
    config: Config,
    sock: Path | None = None,
) -> LaunchPlan:
    """Pure function. Decides wrap-vs-passthrough, derives sid, builds all argvs.

    Parameters
    ----------
    argv : the user-facing argv (e.g., ["claude", "--effort", "max"]). argv[0]
        is informational; the actual binary path is resolved via find_claude_real().
    env : the environment dict (caller passes os.environ.copy() in production)
    stdin_isatty : caller passes sys.stdin.isatty() (allows monkeypatching in tests)
    cwd : the user's $PWD at launch time (caller passes Path.cwd())
    home : the user's HOME (caller passes Path(env["HOME"]))
    config : loaded Config dataclass
    sock : optional tmux socket path (None = default tmux server). Tests pass tmux_socket.

    Returns a LaunchPlan describing exactly what launch_cmd will execute.
    """
    claude_real = shim.find_claude_real()
    in_tmux = shim.is_in_tmux(env)
    sid = shim.derive_sid(argv, env)
    cleaned_argv = shim.strip_no_tmux(argv)
    # Replace argv[0] with the resolved binary path so subprocess/exec uses it.
    claude_argv = [str(claude_real), *cleaned_argv[1:]]
    cwd_normalized = normalize_cwd(cwd, home)

    if not config.shim.enabled or not shim.should_wrap(
        argv=argv,
        env=env,
        stdin_isatty=stdin_isatty,
        in_tmux=in_tmux,
        opt_out_env_name=config.shim.opt_out_env,
    ):
        return LaunchPlan(
            mode="passthrough",
            sid=sid,
            claude_argv=claude_argv,
            cwd_normalized=cwd_normalized,
            passthrough_argv=claude_argv,
        )

    session_name = f"claude-{sid}"
    new_argv = tmux.build_new_session_argv(session_name, claude_argv, sock)
    attach_argv = tmux.build_attach_argv(session_name, sock, read_only=False)
    return LaunchPlan(
        mode="wrap",
        sid=sid,
        claude_argv=claude_argv,
        cwd_normalized=cwd_normalized,
        tmux_session_name=session_name,
        tmux_new_argv=new_argv,
        tmux_attach_argv=attach_argv,
    )


def launch_cmd(
    argv: list[str],
    config: Config,
    home: Path,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    stdin_isatty: bool | None = None,
    sock: Path | None = None,
    no_exec: bool = False,
) -> int:
    """Top-level entry point for `croam launch`.

    Steps (in order):
      1. Build the LaunchPlan (pure decision).
      2. Write the ownership.json `create` assertion (BEFORE side effects).
      3. If no_exec: serialize the plan as JSON to stdout, return 0.
      4. If mode == "passthrough": os.execvp(claude_argv[0], claude_argv).
      5. If mode == "wrap":
         a. tmux.new_session_detached(session_name, claude_argv, sock=sock)
         b. tmux.attach(session_name, sock=sock)  -- replaces process

    Returns 0 in no_exec mode. Never returns otherwise (os.execvp replaces process).
    Raises CroamError if claude-real cannot be found, or TmuxError if tmux fails.
    """
    cwd = cwd or Path.cwd()
    env = env if env is not None else os.environ.copy()
    resolved_isatty: bool = stdin_isatty if stdin_isatty is not None else sys.stdin.isatty()

    plan = build_launch_plan(
        argv=argv,
        env=env,
        stdin_isatty=resolved_isatty,
        cwd=cwd,
        home=home,
        config=config,
        sock=sock,
    )

    # Step 2: write the assertion BEFORE side effects. If we crash later, the
    # assertion stays -- doctor surfaces it as "owned but no live process".
    assertion = Assertion(
        sid=plan.sid,
        owner=config.self_hostname,
        asserted_at=datetime.now(UTC),
        action="create",
        cwd_normalized=plan.cwd_normalized,
        previous_owner=None,
    )
    write_local_assertion(config.storage.state_root, config.self_hostname, assertion)
    logger.info("wrote create assertion sid={} owner={}", plan.sid, config.self_hostname)

    # Step 3: --no-exec mode for tests/integration.
    if no_exec:
        plan_dict = {
            "mode": plan.mode,
            "sid": plan.sid,
            "claude_argv": plan.claude_argv,
            "cwd_normalized": plan.cwd_normalized,
            "tmux_session_name": plan.tmux_session_name,
            "tmux_new_argv": plan.tmux_new_argv,
            "tmux_attach_argv": plan.tmux_attach_argv,
            "passthrough_argv": plan.passthrough_argv,
        }
        sys.stdout.write(json.dumps(plan_dict, indent=2) + "\n")
        return 0

    # Step 4 / 5: real side effects.
    if plan.mode == "passthrough":
        logger.info("passthrough exec: {}", plan.claude_argv)
        os.execvp(plan.claude_argv[0], plan.claude_argv)
        raise AssertionError("execvp returned")

    # mode == "wrap"
    assert plan.tmux_session_name is not None
    try:
        tmux.new_session_detached(
            plan.tmux_session_name,
            plan.claude_argv,
            sock=sock,
        )
    except TmuxError:
        # The assertion stays on disk -- doctor will surface it. Re-raise so
        # the CLI prints a clean error and exits non-zero.
        raise
    logger.info("created tmux session {}", plan.tmux_session_name)
    tmux.attach(plan.tmux_session_name, sock=sock)
    raise AssertionError("attach returned")
