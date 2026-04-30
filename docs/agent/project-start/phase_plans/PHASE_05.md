# Phase 5: Tmux integration & claude shim

**Feature**: project-start
**Estimated Context Budget**: ~70k tokens

**Difficulty**: medium
**Visual**: no
**Functional**: yes

**Execution Mode**: parallel
**Batch**: 3 (with Phase 3 and Phase 4)

---

## Objective

Implement tmux subprocess wrappers, the claude shim decision logic, and the `croam launch` orchestrator that wraps interactive `claude` invocations inside a tmux session named `claude-<sid>`. This phase ships Surface 1 (the `croam launch` verb) and Surface 3 (the shim wrapping behavior described in design spec section 8).

The phase has three orthogonal pieces:

1. `src/croam/tmux.py`: thin subprocess wrappers around the `tmux` binary. Pure mechanical I/O; no policy.
2. `src/croam/shim.py`: pure decision logic over (argv, env, stdin_isatty, in_tmux). Produces a sid and a wrap/pass-through verdict. No subprocess calls, no I/O.
3. `src/croam/commands/launch.py`: the orchestrator that consumes both, writes the ownership assertion, and either `tmux new + attach` or pass-through `claude-real`.

Critical design constraint: every `os.execvp` site MUST have an extracted "argv-builder" function so tests can assert on the planned argv without actually exec()ing. The orchestrator additionally supports a `--no-exec` mode that emits the planned argv as JSON to stdout instead of calling `os.execvp` -- this is what integration tests use.

---

## Deliverables

1. `src/croam/tmux.py` -- subprocess wrappers + argv builders for every tmux operation
2. `src/croam/shim.py` -- pure decision functions: `should_wrap`, `derive_sid`, `strip_no_tmux`, `find_claude_real`, `is_in_tmux`
3. `src/croam/commands/__init__.py` -- empty package marker (Phase 6/7/8 add sibling modules here)
4. `src/croam/commands/launch.py` -- `launch_cmd` orchestrator, `build_launch_plan` argv-builder, `LaunchPlan` dataclass
5. `tests/test_tmux.py` -- real tmux against private socket
6. `tests/test_shim.py` -- pure-function decision tests
7. `tests/test_launch.py` -- orchestrator integration tests (uses `--no-exec`)

No CLI surface is wired in this phase. Phase 6 ships `cli.py` and the typer `cmd_launch` dispatcher that calls `launch_cmd`.

---

## Detailed Requirements

### 1. `src/croam/tmux.py`

Module preamble:

```python
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn

from loguru import logger

from croam.errors import TmuxError
```

#### Argv builders (pure functions, public, testable in isolation)

```python
def build_has_session_argv(name: str, sock: Path | None) -> list[str]:
    """Return argv for `tmux [-S sock] has-session -t <name>`."""

def build_new_session_argv(
    name: str,
    command: list[str],
    sock: Path | None,
) -> list[str]:
    """Return argv for `tmux [-S sock] new-session -d -s <name> -- <command...>`.
    The literal `--` terminator is required to separate tmux flags from the command."""

def build_attach_argv(name: str, sock: Path | None, read_only: bool) -> list[str]:
    """Return argv for `tmux [-S sock] attach -t <name>` (with `-r` if read_only).

    Note: tmux's read-only flag is `-r`, placed BEFORE `-t <name>`:
    `tmux -S sock attach -r -t name`."""

def build_kill_session_argv(name: str, sock: Path | None) -> list[str]:
    """Return argv for `tmux [-S sock] kill-session -t <name>`."""

def build_list_sessions_argv(sock: Path | None) -> list[str]:
    """Return argv for `tmux [-S sock] list-sessions -F "#{session_name}:#{session_attached}"`."""
```

Implementation rule: when `sock is not None`, prepend `["tmux", "-S", str(sock)]`; otherwise `["tmux"]`. Do NOT use the user's $TMUX_SOCKET or $TMUX_TMPDIR -- explicit socket only.

Session names MUST be validated by callers; `tmux.py` never constructs them. Callers pass `claude-<sid>` already formed.

#### Side-effecting wrappers

```python
def has_session(name: str, sock: Path | None = None) -> bool:
    """`tmux has-session -t <name>` returns 0 (True) or 1 (False).

    Any other exit code (e.g., 127 if tmux missing) raises TmuxError.
    Stderr is captured at DEBUG level."""
    argv = build_has_session_argv(name, sock)
    logger.debug("tmux argv: {}", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise TmuxError(
        f"tmux has-session unexpected exit {result.returncode}: {result.stderr.strip()}"
    )


def new_session_detached(
    name: str,
    command: list[str],
    *,
    sock: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Create a detached tmux session running `command`. Raises TmuxError on failure.

    Parameters
    ----------
    name : the tmux session name (caller-formed, e.g., `claude-<sid>`)
    command : argv of the program to run inside the new window
    sock : private socket path, or None for default tmux server
    env : extra env vars merged onto os.environ for the tmux subprocess
    """
    argv = build_new_session_argv(name, command, sock)
    logger.debug("tmux argv: {}", argv)
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(argv, capture_output=True, text=True, check=False, env=full_env)
    if result.returncode != 0:
        raise TmuxError(
            f"tmux new-session failed (exit {result.returncode}): {result.stderr.strip()}"
        )


def attach(name: str, *, sock: Path | None = None, read_only: bool = False) -> NoReturn:
    """Replace the current process with `tmux attach -t <name>`. Does not return."""
    argv = build_attach_argv(name, sock, read_only)
    logger.debug("tmux exec argv: {}", argv)
    os.execvp(argv[0], argv)
    raise AssertionError("execvp returned")  # mypy/pyright happy; never reached


def kill_session(name: str, sock: Path | None = None) -> None:
    """Kill a tmux session. Idempotent: no-op if session does not exist."""
    argv = build_kill_session_argv(name, sock)
    logger.debug("tmux argv: {}", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return
    # tmux returns 1 with stderr "can't find session: NAME" when session is gone -- idempotent.
    if "can't find session" in result.stderr or "no server running" in result.stderr:
        return
    raise TmuxError(
        f"tmux kill-session failed (exit {result.returncode}): {result.stderr.strip()}"
    )


def list_sessions(sock: Path | None = None) -> list[tuple[str, bool]]:
    """Return [(name, attached), ...]. Empty list if server is not running.

    `attached` is True when tmux reports `session_attached` >= 1."""
    argv = build_list_sessions_argv(sock)
    logger.debug("tmux argv: {}", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # exit 1 + stderr "no server running" is the empty case.
        if "no server running" in result.stderr:
            return []
        raise TmuxError(
            f"tmux list-sessions failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    sessions: list[tuple[str, bool]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        name, _, attached_str = line.partition(":")
        sessions.append((name, attached_str.strip() != "0"))
    return sessions
```

### 2. `src/croam/shim.py`

Module preamble:

```python
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from croam.errors import CroamError
```

Pure decision functions, no subprocess, no filesystem (except `find_claude_real` which uses `shutil.which`). Every function takes its inputs explicitly so tests inject them.

```python
def should_wrap(
    argv: list[str],
    env: dict[str, str],
    stdin_isatty: bool,
    in_tmux: bool,
    opt_out_env_name: str = "CROAM_NO_TMUX",
) -> bool:
    """Decide whether to wrap `claude` invocation in a tmux session.

    Returns False (pass through) if any of:
      - stdin is not a tty (scripted invocation)
      - we're already inside a tmux session
      - opt-out env var is set
      - --no-tmux is in argv
      - --print is in argv (claude scripted/non-interactive mode)
      - --help or -h is in argv (claude prints help and exits)

    Returns True otherwise.

    Pure function: no side effects, no external state read.
    """
    if not stdin_isatty:
        return False
    if in_tmux:
        return False
    if opt_out_env_name in env:
        return False
    if "--no-tmux" in argv:
        return False
    if "--print" in argv:
        return False
    if "--help" in argv or "-h" in argv:
        return False
    return True


def derive_sid(argv: list[str], env: dict[str, str]) -> str:
    """Return the session id for this launch.

    If --resume <sid> or --resume=<sid> is in argv, return that sid.
    Otherwise generate a fresh uuid4 string.
    """
    for i, token in enumerate(argv):
        if token == "--resume":
            # next token is the sid (if present)
            if i + 1 < len(argv):
                return argv[i + 1]
            # `--resume` with no value -> behave as if no resume given
            continue
        if token.startswith("--resume="):
            return token.split("=", 1)[1]
    return str(uuid.uuid4())


def strip_no_tmux(argv: list[str]) -> list[str]:
    """Return argv with `--no-tmux` removed (preserving order)."""
    return [a for a in argv if a != "--no-tmux"]


def find_claude_real() -> Path:
    """Locate the real claude binary on PATH.

    Prefers `claude-real` (the renamed binary after shim install per spec section 8),
    falls back to `claude`. Raises CroamError if neither is found.
    """
    for name in ("claude-real", "claude"):
        located = shutil.which(name)
        if located:
            return Path(located)
    raise CroamError("could not find `claude-real` or `claude` on PATH")


def is_in_tmux(env: dict[str, str]) -> bool:
    """Return True if the standard `TMUX` env var is set to a non-empty value."""
    return bool(env.get("TMUX", "").strip())
```

### 3. `src/croam/commands/__init__.py`

Empty file (single-line module docstring is fine):

```python
"""croam command handlers (one module per verb)."""
```

### 4. `src/croam/commands/launch.py`

This is the orchestrator. It calls into `shim`, `tmux`, and `ownership`. All side effects that can be planned in advance go through `build_launch_plan` -- a pure function that returns a `LaunchPlan` dataclass describing what `launch_cmd` will do. Tests assert on the plan; `launch_cmd` consumes it.

```python
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from loguru import logger

from croam import shim, tmux
from croam.config import Config
from croam.errors import CroamError, TmuxError
from croam.ownership import Assertion, write_local_assertion  # Phase 4 deliverable
from croam.paths import normalize_cwd  # Phase 2 deliverable


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

    if not config.shim_enabled or not shim.should_wrap(
        argv=cleaned_argv,
        env=env,
        stdin_isatty=stdin_isatty,
        in_tmux=in_tmux,
        opt_out_env_name=config.shim_opt_out_env,
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

    The assertion is written BEFORE the tmux call so other hosts see "session
    exists" ASAP via syncthing. If the tmux call fails after the assertion is
    written, the assertion stays on disk: it's a soft inconsistency that
    Phase 9's `croam doctor` surfaces. This is intentional.

    Returns:
      - In no_exec mode: returns 0 after printing the plan.
      - In passthrough/wrap modes: never returns under normal conditions
        (os.execvp replaces the process). On failure before exec: returns
        non-zero exit code via raised CroamError caught by the cli.

    Raises:
      - CroamError if claude-real cannot be found, or if tmux fails before exec.
    """
    cwd = cwd or Path.cwd()
    env = env if env is not None else os.environ.copy()
    stdin_isatty = stdin_isatty if stdin_isatty is not None else sys.stdin.isatty()

    plan = build_launch_plan(
        argv=argv,
        env=env,
        stdin_isatty=stdin_isatty,
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
        asserted_at=datetime.now(timezone.utc),
        action="create",
        cwd_normalized=plan.cwd_normalized,
        previous_owner=None,
    )
    write_local_assertion(config.state_root, config.self_hostname, assertion)
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
```

### 5. `tests/test_tmux.py`

Use real tmux against the `tmux_socket` fixture from `tests/conftest.py` (Phase 1 deliverable). Every test passes `sock=tmux_socket` explicitly. Use `tmux ls -S <sock>` to verify outcomes between operations.

Tests:

```python
def test_build_has_session_argv():
    assert tmux.build_has_session_argv("foo", None) == ["tmux", "has-session", "-t", "foo"]
    assert tmux.build_has_session_argv("foo", Path("/tmp/sock")) == [
        "tmux", "-S", "/tmp/sock", "has-session", "-t", "foo",
    ]


def test_build_new_session_argv():
    assert tmux.build_new_session_argv("foo", ["sleep", "10"], None) == [
        "tmux", "new-session", "-d", "-s", "foo", "--", "sleep", "10",
    ]
    assert tmux.build_new_session_argv("foo", ["sleep", "10"], Path("/tmp/sock")) == [
        "tmux", "-S", "/tmp/sock", "new-session", "-d", "-s", "foo", "--", "sleep", "10",
    ]


def test_build_attach_argv_default():
    assert tmux.build_attach_argv("foo", None, read_only=False) == [
        "tmux", "attach", "-t", "foo",
    ]


def test_build_attach_argv_read_only():
    assert tmux.build_attach_argv("foo", Path("/tmp/sock"), read_only=True) == [
        "tmux", "-S", "/tmp/sock", "attach", "-r", "-t", "foo",
    ]


def test_build_kill_session_argv():
    assert tmux.build_kill_session_argv("foo", None) == [
        "tmux", "kill-session", "-t", "foo",
    ]


def test_build_list_sessions_argv():
    assert tmux.build_list_sessions_argv(Path("/tmp/sock")) == [
        "tmux", "-S", "/tmp/sock", "list-sessions",
        "-F", "#{session_name}:#{session_attached}",
    ]


def test_has_session_false_no_server(tmux_socket):
    """An empty private socket has no sessions."""
    assert tmux.has_session("nonexistent", sock=tmux_socket) is False


def test_new_and_has(tmux_socket):
    """Creating a session makes has_session True; killing makes it False."""
    tmux.new_session_detached("croam-test-foo", ["sleep", "10"], sock=tmux_socket)
    try:
        assert tmux.has_session("croam-test-foo", sock=tmux_socket) is True
    finally:
        tmux.kill_session("croam-test-foo", sock=tmux_socket)
    assert tmux.has_session("croam-test-foo", sock=tmux_socket) is False


def test_list_sessions_empty(tmux_socket):
    assert tmux.list_sessions(sock=tmux_socket) == []


def test_list_sessions_three(tmux_socket):
    names = ["croam-test-a", "croam-test-b", "croam-test-c"]
    try:
        for n in names:
            tmux.new_session_detached(n, ["sleep", "10"], sock=tmux_socket)
        listed = tmux.list_sessions(sock=tmux_socket)
        assert sorted(name for name, _ in listed) == names
        # None attached.
        assert all(attached is False for _, attached in listed)
    finally:
        for n in names:
            tmux.kill_session(n, sock=tmux_socket)


def test_idempotent_kill_no_session(tmux_socket):
    """Killing a non-existent session does not raise."""
    tmux.kill_session("not-there", sock=tmux_socket)


def test_idempotent_kill_no_server(tmux_socket):
    """Killing on a socket with no server running does not raise."""
    # tmux_socket fixture starts empty; no server started.
    tmux.kill_session("not-there", sock=tmux_socket)


def test_new_session_failure_raises(tmux_socket):
    """Asking tmux to run a non-existent program inside a new-session must raise.

    Note: tmux new-session -d returns 0 even if the inner command fails, because
    the child is detached. To force a failure, create a session with a duplicate
    name."""
    tmux.new_session_detached("croam-test-dup", ["sleep", "10"], sock=tmux_socket)
    try:
        with pytest.raises(TmuxError, match="new-session"):
            tmux.new_session_detached("croam-test-dup", ["sleep", "10"], sock=tmux_socket)
    finally:
        tmux.kill_session("croam-test-dup", sock=tmux_socket)
```

### 6. `tests/test_shim.py`

Pure function tests, all microsecond-fast.

```python
def test_should_wrap_default():
    assert shim.should_wrap(
        argv=["claude"], env={}, stdin_isatty=True, in_tmux=False,
    ) is True


def test_should_wrap_in_tmux():
    assert shim.should_wrap(
        argv=["claude"], env={"TMUX": "/tmp/tmux-1000/default,123,4"},
        stdin_isatty=True, in_tmux=True,
    ) is False


def test_should_wrap_not_tty():
    assert shim.should_wrap(
        argv=["claude"], env={}, stdin_isatty=False, in_tmux=False,
    ) is False


def test_should_wrap_no_tmux_flag():
    assert shim.should_wrap(
        argv=["claude", "--no-tmux", "--effort", "max"],
        env={}, stdin_isatty=True, in_tmux=False,
    ) is False


def test_should_wrap_print_flag():
    assert shim.should_wrap(
        argv=["claude", "--print", "explain this"],
        env={}, stdin_isatty=True, in_tmux=False,
    ) is False


def test_should_wrap_help_long():
    assert shim.should_wrap(
        argv=["claude", "--help"], env={}, stdin_isatty=True, in_tmux=False,
    ) is False


def test_should_wrap_help_short():
    assert shim.should_wrap(
        argv=["claude", "-h"], env={}, stdin_isatty=True, in_tmux=False,
    ) is False


def test_should_wrap_opt_out_env_default_name():
    assert shim.should_wrap(
        argv=["claude"], env={"CROAM_NO_TMUX": "1"},
        stdin_isatty=True, in_tmux=False,
    ) is False


def test_should_wrap_opt_out_env_custom_name():
    assert shim.should_wrap(
        argv=["claude"], env={"NOPE": "1"},
        stdin_isatty=True, in_tmux=False, opt_out_env_name="NOPE",
    ) is False


def test_derive_sid_resume_space():
    assert shim.derive_sid(
        argv=["claude", "--resume", "abc-123"], env={},
    ) == "abc-123"


def test_derive_sid_resume_equals():
    assert shim.derive_sid(
        argv=["claude", "--resume=abc-123"], env={},
    ) == "abc-123"


def test_derive_sid_resume_in_middle():
    assert shim.derive_sid(
        argv=["claude", "--effort", "max", "--resume", "abc-123", "--print"], env={},
    ) == "abc-123"


def test_derive_sid_resume_dangling():
    """--resume with no value after it -> fall through to uuid4."""
    sid = shim.derive_sid(argv=["claude", "--resume"], env={})
    uuid.UUID(sid)  # raises if not a valid uuid


def test_derive_sid_no_resume_returns_uuid():
    sid = shim.derive_sid(argv=["claude"], env={})
    parsed = uuid.UUID(sid)
    assert parsed.version == 4


def test_strip_no_tmux_present():
    assert shim.strip_no_tmux(["claude", "--no-tmux", "--effort", "max"]) == [
        "claude", "--effort", "max",
    ]


def test_strip_no_tmux_absent():
    assert shim.strip_no_tmux(["claude", "--effort", "max"]) == [
        "claude", "--effort", "max",
    ]


def test_strip_no_tmux_multiple():
    """Defensive: if the user typed --no-tmux twice, strip both."""
    assert shim.strip_no_tmux(["claude", "--no-tmux", "--no-tmux", "x"]) == ["claude", "x"]


def test_find_claude_real_prefers_real(tmp_path, monkeypatch):
    """When both `claude` and `claude-real` are on PATH, prefer claude-real."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text("#!/bin/sh\necho claude\n")
    (bindir / "claude").chmod(0o755)
    (bindir / "claude-real").write_text("#!/bin/sh\necho real\n")
    (bindir / "claude-real").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert shim.find_claude_real() == bindir / "claude-real"


def test_find_claude_real_falls_back_to_claude(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "claude").write_text("#!/bin/sh\necho claude\n")
    (bindir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir))
    assert shim.find_claude_real() == bindir / "claude"


def test_find_claude_real_neither(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # empty bindir
    with pytest.raises(CroamError, match="claude-real"):
        shim.find_claude_real()


def test_is_in_tmux_set():
    assert shim.is_in_tmux({"TMUX": "/tmp/tmux/default,1,2"}) is True


def test_is_in_tmux_empty():
    assert shim.is_in_tmux({"TMUX": ""}) is False


def test_is_in_tmux_unset():
    assert shim.is_in_tmux({}) is False


def test_is_in_tmux_whitespace():
    assert shim.is_in_tmux({"TMUX": "  "}) is False
```

### 7. `tests/test_launch.py`

Integration tests using `--no-exec` so we never actually exec. The `home` and `tmux_socket` fixtures handle isolation.

```python
def _make_fake_claude(tmp_path: Path) -> Path:
    """Drop a fake `claude` binary on PATH so find_claude_real() succeeds."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "claude"
    fake.write_text("#!/bin/sh\necho fake-claude $@\n")
    fake.chmod(0o755)
    return fake


def _make_config(home: Path, state_root: Path, hostname: str = "stormtree") -> Config:
    """Construct a minimal Config for tests. Phase 2 ships Config; this stub uses
    keyword-only construction. Adjust if Phase 2's signature differs."""
    return Config(
        self_hostname=hostname,
        hosts={},
        state_root=state_root,
        discovery_mode="ssh",
        claim_verify="local",
        picker_default_filter="exact-pwd",
        picker_last_window_days=30,
        shim_enabled=True,
        shim_opt_out_env="CROAM_NO_TMUX",
    )


def test_build_launch_plan_wrap_path(home, tmp_path, monkeypatch):
    """Default invocation in a TTY shell, not in tmux, returns mode='wrap'."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude", "--effort", "max"],
        env={"HOME": str(home)},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
        sock=None,
    )
    assert plan.mode == "wrap"
    uuid.UUID(plan.sid)  # valid uuid4
    assert plan.tmux_session_name == f"claude-{plan.sid}"
    assert plan.tmux_new_argv[:6] == [
        "tmux", "new-session", "-d", "-s", f"claude-{plan.sid}", "--",
    ]
    assert plan.tmux_new_argv[6] == str(fake_claude)
    assert plan.tmux_new_argv[7:] == ["--effort", "max"]
    assert plan.tmux_attach_argv == ["tmux", "attach", "-t", f"claude-{plan.sid}"]


def test_build_launch_plan_passthrough_in_tmux(home, tmp_path, monkeypatch):
    """If TMUX env var is set, mode is 'passthrough'."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude"],
        env={"HOME": str(home), "TMUX": "/tmp/tmux-1000/default,123,4"},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
    )
    assert plan.mode == "passthrough"
    assert plan.passthrough_argv == [str(fake_claude)]
    assert plan.tmux_new_argv is None


def test_build_launch_plan_passthrough_print_flag(home, tmp_path, monkeypatch):
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude", "--print", "say hi"],
        env={"HOME": str(home)},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
    )
    assert plan.mode == "passthrough"


def test_build_launch_plan_resume_uses_provided_sid(home, tmp_path, monkeypatch):
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude", "--resume", "ff7afd8a-ea17-4183-a131-566e7bcb0758"],
        env={"HOME": str(home)},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
    )
    assert plan.sid == "ff7afd8a-ea17-4183-a131-566e7bcb0758"
    assert plan.tmux_session_name == "claude-ff7afd8a-ea17-4183-a131-566e7bcb0758"


def test_build_launch_plan_strips_no_tmux(home, tmp_path, monkeypatch):
    """When --no-tmux is in argv, mode is passthrough AND --no-tmux is stripped."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    config = _make_config(home=home, state_root=tmp_path / "state")
    plan = build_launch_plan(
        argv=["claude", "--no-tmux", "--effort", "max"],
        env={"HOME": str(home)},
        stdin_isatty=True,
        cwd=home,
        home=home,
        config=config,
    )
    assert plan.mode == "passthrough"
    assert "--no-tmux" not in plan.passthrough_argv
    assert plan.passthrough_argv == [str(fake_claude), "--effort", "max"]


def test_launch_cmd_no_exec_writes_assertion(home, tmp_path, capsys, monkeypatch):
    """launch_cmd in --no-exec mode prints the plan AND writes the assertion."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    state_root = tmp_path / "state"
    state_root.mkdir()
    config = _make_config(home=home, state_root=state_root)

    rc = launch_cmd(
        argv=["claude"],
        config=config,
        home=home,
        cwd=home,
        env={"HOME": str(home)},
        stdin_isatty=True,
        no_exec=True,
    )
    assert rc == 0

    captured = capsys.readouterr()
    plan_dict = json.loads(captured.out)
    assert plan_dict["mode"] == "wrap"
    sid = plan_dict["sid"]
    uuid.UUID(sid)

    # Verify ownership.json was written.
    ownership_path = state_root / "stormtree" / "ownership.json"
    assert ownership_path.exists()
    data = json.loads(ownership_path.read_text())
    assert sid in data
    assert data[sid]["action"] == "create"
    assert data[sid]["owner"] == "stormtree"


def test_launch_cmd_real_tmux(home, tmux_socket, tmp_path, monkeypatch):
    """Full integration: launch_cmd creates a real tmux session on the private socket.

    We avoid execvp by patching tmux.attach to a no-op."""
    fake_claude = _make_fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(fake_claude.parent))
    state_root = tmp_path / "state"
    state_root.mkdir()
    config = _make_config(home=home, state_root=state_root)

    attach_calls: list[tuple] = []
    monkeypatch.setattr(tmux, "attach", lambda *a, **kw: attach_calls.append((a, kw)))

    # AssertionError("attach returned") will fire because our patched attach
    # actually returns. Catch it and verify the side effects.
    with pytest.raises(AssertionError, match="attach returned"):
        launch_cmd(
            argv=["claude"],
            config=config,
            home=home,
            cwd=home,
            env={"HOME": str(home)},
            stdin_isatty=True,
            sock=tmux_socket,
            no_exec=False,
        )

    assert len(attach_calls) == 1
    sessions = tmux.list_sessions(sock=tmux_socket)
    names = [n for n, _ in sessions]
    assert any(n.startswith("claude-") for n in names)
    # Cleanup
    for n, _ in sessions:
        tmux.kill_session(n, sock=tmux_socket)
```

### Edge cases and integration constraints

- **`os.execvp` is irreversible**: every call site has an argv-builder counterpart. Tests assert on builders + the `--no-exec` JSON output. The orchestrator's two real `execvp` paths (`launch.py` passthrough, `tmux.attach`) are reached only in production or in tests that explicitly monkeypatch them.
- **Assertion-before-side-effect**: `launch_cmd` writes the `ownership.json` create assertion BEFORE the tmux/exec call. If tmux fails, the assertion remains. This is intentional: it surfaces as a "soft" inconsistency in `croam doctor` (Phase 9), not a fatal bug. The alternative (rolling back the assertion on tmux failure) introduces a race window where another host could miss the assertion entirely.
- **`stdin.isatty()` injection**: `launch_cmd` accepts `stdin_isatty` as a parameter so tests can pass a literal True/False. Production calls pass `sys.stdin.isatty()`. Never call `sys.stdin.isatty()` from inside `should_wrap` -- that would make the function impure.
- **TMUX detection via env**: only `os.environ.get("TMUX")` -- never check `tmux display-message -p '#{client_tty}'` or similar. The env var is set by tmux when it spawns child shells; if it's set and non-empty, we're inside a tmux client. This is the standard contract.
- **`--resume` parsing**: handle BOTH `--resume <sid>` (separate arg) and `--resume=<sid>` (joined). Both are valid argparse styles. Test both. Dangling `--resume` (no value after it) falls through to uuid4 generation -- DO NOT raise.
- **`--no-tmux` propagation**: stripped from argv before passing to claude-real. Claude does not understand `--no-tmux`; passing it through would cause claude to error out.
- **Session-name validation**: `claude-<sid>` is the literal format. sid is either a uuid4 or a user-provided string after `--resume`. Test that sids containing `:` or other tmux-special characters do not crash; if they would crash tmux, raise `TmuxError` with a clear message before invoking tmux. (Practically: claude sids are uuid4 hex, no special chars; we don't need to defensively encode.)
- **Idempotent kill**: `kill_session` is no-op when the session does not exist OR when the tmux server is not running. The test must cover both paths because tmux's exit code differs.
- **No tracebacks to user**: any `CroamError` raised inside `launch_cmd` propagates up to the typer dispatcher in Phase 6, which catches it and prints a one-liner. Inside this phase, ensure all error paths raise typed exceptions, never bare `Exception`.

### Implementation order (within the phase)

Build in this sequence so each layer can be tested before the next is started:

1. **`src/croam/tmux.py`** -- subprocess wrappers + builders. Easiest layer; pure I/O. Run `pytest tests/test_tmux.py` until green.
2. **`src/croam/shim.py`** -- pure functions, no I/O. Run `pytest tests/test_shim.py` until green.
3. **`src/croam/commands/__init__.py`** -- empty package marker.
4. **`src/croam/commands/launch.py`** -- orchestrator. Depends on Phase 2 (`Config`, `normalize_cwd`) and Phase 4 (`Assertion`, `write_local_assertion`). Run `pytest tests/test_launch.py` until green.
5. Run the full suite: `pytest tests/test_tmux.py tests/test_shim.py tests/test_launch.py -v`.

---

## Dependencies

**Requires**:
- Phase 1: `src/croam/errors.py` (`CroamError`, `TmuxError`), `src/croam/log.py` (loguru `logger`), `tests/conftest.py` (the `home`, `tmux_socket` fixtures, conftest guard).
- Phase 2: `src/croam/config.py` (`Config` dataclass, `load_config`), `src/croam/paths.py` (`normalize_cwd`).
- Phase 4: `src/croam/ownership.py` (`Assertion` dataclass, `write_local_assertion`).

If Phase 4's API is named differently (`write_local_assertions` plural, `add_assertion`, etc.) adapt the import. The contract this phase needs: a function that, given `(state_root: Path, hostname: str, assertion: Assertion)`, atomically inserts the assertion into `<state_root>/<hostname>/ownership.json`.

**Enables**:
- Phase 6: `cli.py` will dispatch `croam launch` to `launch_cmd`.
- Phase 7: `commands/attach.py` will call `tmux.has_session`, `tmux.new_session_detached`, `tmux.attach` for the kill-and-relaunch flow.
- Phase 8: `commands/claim.py` will call `tmux.kill_session` on the origin during the release step.

---

## Completion Criteria

- [ ] `src/croam/tmux.py` implements all five argv-builders and all five wrappers; `pytest tests/test_tmux.py -v` passes
- [ ] `src/croam/shim.py` implements `should_wrap`, `derive_sid`, `strip_no_tmux`, `find_claude_real`, `is_in_tmux`; `pytest tests/test_shim.py -v` passes
- [ ] `src/croam/commands/__init__.py` exists (empty)
- [ ] `src/croam/commands/launch.py` implements `LaunchPlan`, `build_launch_plan`, `launch_cmd`; `pytest tests/test_launch.py -v` passes
- [ ] `should_wrap` has 100% branch coverage (verifiable via `pytest --cov=src/croam/shim tests/test_shim.py`)
- [ ] No call site of `os.execvp` lacks a corresponding argv-builder
- [ ] `launch_cmd` writes the ownership.json assertion BEFORE invoking tmux/exec (verifiable: a test that injects a tmux failure shows the assertion still on disk)
- [ ] All public functions have type hints and one-line docstrings
- [ ] `ruff check src/croam/tmux.py src/croam/shim.py src/croam/commands/launch.py tests/test_tmux.py tests/test_shim.py tests/test_launch.py` passes
- [ ] `pyright src/croam/tmux.py src/croam/shim.py src/croam/commands/launch.py` passes

---

## Testing Requirements

### Tests to write

- `tests/test_tmux.py`: 13 tests covering builders + wrappers + edge cases listed above
- `tests/test_shim.py`: 22 tests covering all branches of `should_wrap`, `derive_sid`, `strip_no_tmux`, `find_claude_real`, `is_in_tmux`
- `tests/test_launch.py`: 7 tests covering `build_launch_plan` plan output and `launch_cmd` with real tmux + assertion writing

### Test commands

Run inside the project root with `uv` already initialized:

```
# Single-file targeted runs (use these during iteration)
uv run pytest tests/test_tmux.py -v
uv run pytest tests/test_shim.py -v
uv run pytest tests/test_launch.py -v

# Phase verification (run before marking complete)
uv run pytest tests/test_tmux.py tests/test_shim.py tests/test_launch.py -v --tb=short

# Coverage check for shim purity
uv run pytest tests/test_shim.py --cov=src/croam/shim --cov-report=term-missing

# Lint and type-check
uv run ruff check src/croam/tmux.py src/croam/shim.py src/croam/commands/launch.py
uv run pyright src/croam/tmux.py src/croam/shim.py src/croam/commands/launch.py
```

### Test environment requirements

- `tmux` (>= 3.0) on PATH for `test_tmux.py` and the real-tmux test in `test_launch.py`
- A tmpfs-style writable `tmp_path` (provided by pytest)
- The `home`, `tmux_socket` fixtures from `tests/conftest.py` (Phase 1)
- The `monkeypatch` fixture (built-in pytest) for PATH manipulation

### Anti-patterns to watch for

From `FUNCTIONAL_QA_STRATEGY.md`:

- **Anti-pattern A (HOME redirect)**: every test that touches the filesystem uses the `home` fixture. Never call `Path.home()` or `os.path.expanduser("~")`. The conftest guard refuses to run otherwise.
- **Anti-pattern C (Mocked tmux misses session-naming bugs)**: `test_tmux.py` uses real tmux against `tmux_socket`. Do NOT mock `subprocess.run` here. The only place we monkeypatch is `tmux.attach` in `test_launch_cmd_real_tmux`, because actually exec()ing would replace the pytest process.

---

## Functional QA

These checks exercise Surface 1 (`croam launch`, via `launch_cmd` in `--no-exec` mode) and Surface 3 (the shim wrapping decision). They map to the spec's Loop A (first-run sanity, single host) since `croam launch` is what the `claude` alias calls when the user types `claude` after install.

- [ ] **(shim surface, Loop A)** `shim.should_wrap(argv=["claude"], env={}, stdin_isatty=True, in_tmux=False)` returns exactly `True`. Capture call + return value in summary.

- [ ] **(shim surface, Loop A)** `shim.should_wrap(argv=["claude", "--print", "x"], env={}, stdin_isatty=True, in_tmux=False)` returns exactly `False` (claude scripted mode bypasses tmux). Capture call + return.

- [ ] **(shim surface, Loop A)** `shim.derive_sid(argv=["claude", "--resume", "abc-123"], env={})` returns exactly `"abc-123"`. Capture.

- [ ] **(shim surface, Loop A)** `shim.derive_sid(argv=["claude", "--resume=abc-123"], env={})` returns exactly `"abc-123"`. Capture.

- [ ] **(launch surface, Loop A)** `launch_cmd(argv=["claude"], config=<test_config>, home=<tmp_home>, no_exec=True)` writes a JSON plan to stdout AND creates `<state_root>/<self_hostname>/ownership.json` with one entry whose `action == "create"`. Paste the stdout JSON and the on-disk ownership.json contents into summary.

- [ ] **(launch surface, Loop A)** The planned `tmux_new_argv` from `--no-exec` matches the pattern `["tmux", "-S", <sock>, "new-session", "-d", "-s", "claude-<sid>", "--", <claude-real-path>, ...remaining-claude-args]`. Paste the captured argv list.

- [ ] **(launch surface, Loop A)** Real-tmux integration: with the `tmux_socket` fixture and `tmux.attach` patched to a no-op, `launch_cmd` causes `tmux -S <sock> ls` to show a session named `claude-<sid>`. Capture the output of `tmux -S <sock> ls`.

- [ ] **(shim surface)** Anti-pattern check: at least one `test_shim.py` test verifies `is_in_tmux({"TMUX": ""})` returns False (an empty TMUX env var is NOT inside tmux). Capture.

- [ ] **(launch surface)** Crash-safety check: with `tmux.new_session_detached` monkeypatched to raise `TmuxError`, `launch_cmd` propagates the exception AND `<state_root>/<hostname>/ownership.json` still contains the assertion (assertion-before-side-effect contract). Paste the assertion JSON contents and confirm the exception was raised.

---

## Helpers Required

This phase has no helper dependencies. The required mechanics (tmux subprocess, ownership-file writes, PATH manipulation in tests) are either core Python stdlib or covered by Phase 1's conftest fixtures.

---

## External Interfaces Consumed

- **`tmux` subprocess interface (`has-session`, `list-sessions`, `new-session`, `kill-session` exit codes and stderr text)**
  - **Consumed by**: `src/croam/tmux.py` -- the wrappers parse exit codes and stderr substrings.
  - **How to capture**: run these commands against a private socket BEFORE writing the wrappers, paste outputs into the phase summary.
    ```
    SOCK=/tmp/croam-capture.sock
    # 1. has-session against empty server
    tmux -S "$SOCK" has-session -t notexist; echo "EXIT=$?"
    # 2. list-sessions against empty server (no server running)
    tmux -S "$SOCK" list-sessions -F "#{session_name}:#{session_attached}" 2>&1; echo "EXIT=$?"
    # 3. new-session, then list-sessions, then has-session
    tmux -S "$SOCK" new-session -d -s captest -- sleep 30
    tmux -S "$SOCK" list-sessions -F "#{session_name}:#{session_attached}"
    tmux -S "$SOCK" has-session -t captest; echo "EXIT=$?"
    # 4. duplicate new-session (must fail)
    tmux -S "$SOCK" new-session -d -s captest -- sleep 30 2>&1; echo "EXIT=$?"
    # 5. kill-session of nonexistent
    tmux -S "$SOCK" kill-session -t notexist 2>&1; echo "EXIT=$?"
    # 6. cleanup
    tmux -S "$SOCK" kill-server 2>&1
    rm -f "$SOCK"
    ```
  - **If not observable**: tmux is universally available; if not, install via `pacman -S tmux` / `apt install tmux` and rerun. Do NOT proceed without real captures -- the wrappers' error-text branches depend on the exact stderr substrings tmux emits.

- **`claude` (or `claude-real`) binary on PATH**
  - **Consumed by**: `src/croam/shim.py:find_claude_real()` -- only the existence/path is used, not the binary's behavior. `--version` is captured to confirm we're talking to the version the spec assumed.
  - **How to capture**:
    ```
    which claude
    which claude-real 2>&1 || echo "not present (expected pre-shim-install)"
    claude --version
    ```
  - **If not observable**: tests use a fake `claude` shell script written into a `tmp_path/bin` directory and `monkeypatch.setenv("PATH", ...)`; production code uses `shutil.which`. Capture is informational only -- the implementation does not parse `claude --version` output.

---

## Notes

- The `tmux new-session` argv uses the literal `--` separator before the inner command. This is non-negotiable: without `--`, tmux interprets command flags (`-d`, `-s`, etc. that may appear in the inner argv, e.g., `claude -d`) as tmux's own flags. Always emit `--`.
- `tmux attach -r` (read-only) is for `croam peek` (Phase 7), not `croam launch`. Phase 5 ships the `read_only` parameter on `attach()` and `build_attach_argv()`, but `launch_cmd` always calls with `read_only=False`. Phase 7 will use `read_only=True`.
- The `LaunchPlan` dataclass is intentionally `frozen=True`. The orchestrator never mutates it; it only consumes fields to drive side effects.
- `launch_cmd` returns `int` to match the typer convention where command handlers return an exit code. Under normal wrap/passthrough flow, `launch_cmd` does not return -- `os.execvp` replaces the process. Only the `--no-exec` path returns 0.
- The `AssertionError("execvp returned")` lines exist solely to satisfy the type checker (`NoReturn`-equivalent annotations). They should never execute.
- If `Config` from Phase 2 differs in field names from the stub used in `_make_config`, adapt accordingly. The contract this phase needs from `Config`: `self_hostname`, `state_root`, `shim_enabled`, `shim_opt_out_env`. Other fields are loaded but unused here.
- If `Assertion` and `write_local_assertion` from Phase 4 differ in signature, adapt the import and the call site in `launch_cmd`. The contract: write a single assertion atomically (`os.replace` semantics) into `<state_root>/<hostname>/ownership.json`.
