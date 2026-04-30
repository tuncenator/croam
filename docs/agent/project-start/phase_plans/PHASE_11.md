# Phase 11: Polish, install, README

**Feature**: project-start
**Estimated Context Budget**: ~40k tokens

**Difficulty**: easy
**Visual**: no
**Functional**: yes

**Execution Mode**: sequential
**Batch**: 8 (final batch; depends on Phase 10)

---

## Objective

Wrap up the croam v1 project. Ship a complete `README.md`, two idempotent shell scripts (`scripts/install-shim.sh`, `scripts/install-cctakeover-alias.sh`), tests verifying their behavior, and run a final lint/type-check pass. No new functionality. The end state is: a fresh user can clone the repo, run `uv tool install --editable .`, run `croam doctor`, run `bash scripts/install-shim.sh`, and have a fully working installation.

---

## Deliverables

1. **`README.md`** at the project root -- one-paragraph description, install steps, verb cheat sheet, shim install instructions, configuration pointer, test command, license note.
2. **`scripts/install-shim.sh`** -- POSIX-compatible bash script. Renames the system `claude` binary to `claude-real` and creates a `claude` wrapper that execs `croam launch "$@"`. Refuses to use sudo; if the install dir is non-writable, exits 1 with a helpful message.
3. **`scripts/install-cctakeover-alias.sh`** -- bash script. Idempotently appends `alias cctakeover='croam'` to the user's shell rc file (`~/.zshrc` if `$SHELL` ends in zsh, else `~/.bashrc`).
4. **`tests/test_install_scripts.py`** -- pytest module verifying `--self-check`, idempotency, alias-rc behavior, and refusal-to-elevate semantics. Uses synthetic `tmp_path`-rooted fake `$HOME` and a fake `claude` binary on `$PATH`.
5. **`pyproject.toml` version bump** -- confirm `version = "0.1.0"` (no change required if already correct; verify and adjust only if drifted).
6. **Final lint/type pass** -- run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright src/croam`. Fix anything that surfaces.
7. **Coverage verification** -- `uv run pytest --cov=src/croam --cov-fail-under=80` exits 0.

NON-deliverables (these are owned by other phases or out of scope):
- Anything under `src/croam/` (Phases 1-10 own that tree).
- `tests/conftest.py` (Phase 1 owns it; reuse, do not edit).
- `docs/USAGE.md` -- explicitly OPTIONAL in the brief; SKIP unless time permits and no risk of touching contested files. If written, it goes under `docs/USAGE.md` and contains only verb examples + troubleshooting notes -- nothing that duplicates the design spec.

---

## Detailed Requirements

### 1. `README.md`

Location: `/home/tunc/Sync/Programs/croam/README.md`. Plain markdown, ASCII only (per project convention -- no emojis, no unicode glyphs). Length target: 150-250 lines. Structure:

```markdown
# croam

One-paragraph description: croam unifies claude-code session discovery, attachment,
ownership transfer, and branching across all of a user's hosts. It uses SSH for
live remote access and optional syncthing for offline-capable mirroring. It
obsoletes `cctakeover` by making every claude session run inside a tmux session
named for its UUID, attachable from any local terminal and from any reachable
host remotely. Built for users with multiple personal computers (e.g., a desktop
at home, a laptop at work) who run claude-code on each.

## Install

Recommended:
    uv tool install --editable .

Alternate:
    pipx install -e .

Both install a `croam` console script wired to `croam.cli:app`.

## First run

Bootstrap the default config:
    croam doctor

`croam doctor` writes a default `~/.config/croam/config.toml` if one does not
already exist, then runs diagnostics: config sanity, SSH reachability for each
configured host, syncthing health (if mode = "syncthing"), tmux/fzf/claude
binary presence, and ownership consistency.

## Verbs

| Verb | Purpose |
|---|---|
| `croam` | Open the interactive fzf picker for sessions in $PWD |
| `croam ls` | List sessions non-interactively (`--json` for scripting) |
| `croam attach <sid>` | Attach to a session; SSHes to owner if remote |
| `croam peek <sid>` | Read-only view of a session (live or static) |
| `croam claim <sid>` | Transfer ownership of a session to this host |
| `croam fork <sid>` | Branch a session into a new sid owned by this host |
| `croam launch [args]` | Start a new claude session inside tmux (used by the shim) |
| `croam doctor` | Diagnose config, SSH, syncthing, ownership |

Common flags: `--all`, `--host <name>`, `--last <days>`, `--orphans`,
`--here` (claim/fork variant that rebases cwd to $PWD), `--json` (machine-readable
ls output), `--debug` (verbose logging to ~/.local/state/croam/croam.log).

## Configuration

The config file lives at `~/.config/croam/config.toml`. The schema is documented
in detail in `docs/specs/2026-04-30-croam-design.md` section 10. Top-level
sections: `[self]`, `[hosts.<name>]`, `[storage]`, `[discovery]`, `[ownership]`,
`[picker]`, `[shim]`. The default written by `croam doctor` covers a single-host
setup; add `[hosts.<peer>]` blocks per peer.

## Shim install

Every interactive `claude` invocation should run inside a tmux session named
`claude-<sid>`. To enable this, the system `claude` binary is renamed to
`claude-real` and replaced with a small wrapper that execs `croam launch`.

Steps (manual, for users who want to understand each move):

1. Locate the `claude` binary:
       which claude
2. Verify it is the real claude binary, not already a wrapper:
       file $(which claude)
   The output should NOT contain "shell script". If it does, the shim is
   already installed; stop here.
3. Rename it to `claude-real` (in-place):
       mv "$(which claude)" "$(dirname "$(which claude)")/claude-real"
4. Create the `claude` wrapper script:
       cat > "$(dirname "$(which claude-real)")/claude" <<'EOF'
       #!/usr/bin/env bash
       exec croam launch "$@"
       EOF
       chmod +x "$(dirname "$(which claude-real)")/claude"
5. Verify:
       claude --version    # should still print the claude version, but now via croam

The helper script `scripts/install-shim.sh` automates steps 1-4 with safety
checks (refuses to overwrite an already-installed shim; refuses to use sudo;
prints clear instructions if the install directory is not writable).

If your `claude` binary is in a system path you cannot write to (e.g.,
`/usr/bin/claude`), the helper exits with instructions; install claude into
a user-writable path first (e.g., via `npm i -g @anthropic-ai/claude-code`
into `~/.npm-global/`).

## cctakeover transition

If you previously used `cctakeover`, run:
    bash scripts/install-cctakeover-alias.sh

This appends `alias cctakeover='croam'` to your `~/.zshrc` (or `~/.bashrc`),
preserving muscle memory while you transition to the new tool.

## Tests

    uv run pytest

Runs Tier 1 (synthetic fixtures, no real services). Set `CROAM_E2E=1` to also
run Tier 2 (one disposable real-claude session at /tmp/croam-e2e/):

    CROAM_E2E=1 uv run pytest

## License

License pending. The codebase is currently for private use by the author and
not yet released under any public license.
```

Key constraints on the README:
- Use ONLY plain ASCII. No `[LABEL]` redaction tags. No emoji. No em dash, en dash, or smart quotes (per CLAUDE.md global rules).
- The shim install steps must work when copy-pasted by a user with no prior context.
- The "Configuration" section MUST point at `docs/specs/2026-04-30-croam-design.md` section 10 explicitly. Do NOT duplicate the schema.
- Verb cheat sheet stays one-liner per verb.

### 2. `scripts/install-shim.sh`

Location: `/home/tunc/Sync/Programs/croam/scripts/install-shim.sh`. Mode 0755.

Behavior:

```
Usage:
  install-shim.sh             # install (idempotent)
  install-shim.sh --self-check  # check prerequisites only, no changes
  install-shim.sh --uninstall   # reverse the install (rename claude-real back to claude)
  install-shim.sh --help        # show usage and exit 0
```

Skeleton:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Resolve `claude` on PATH. If absent, exit 1 with message.
# If `claude-real` already exists in the same dir as `claude`, the shim is already installed.
# If the install dir is not writable by current user, print instructions and exit 1 (do NOT sudo).
# Otherwise: mv claude -> claude-real; write a new claude wrapper; chmod +x.

main() {
    case "${1:-install}" in
        --help|-h) print_help; exit 0 ;;
        --self-check) self_check; exit $? ;;
        --uninstall) uninstall; exit $? ;;
        install|"") install; exit $? ;;
        *) echo "FAIL: unknown arg: $1" >&2; print_help; exit 2 ;;
    esac
}

self_check() {
    # 1. Check that `claude` is on PATH.
    # 2. Check that bash is available (we are running in it; tautological but clear).
    # 3. Check that croam is on PATH (so the wrapper will work post-install).
    # 4. Print one line per check: [OK]/[FAIL] description.
    # 5. Exit 0 if all OK, 1 if any FAIL.
    ...
}

install() {
    # 1. Resolve `claude` -> abs_path via `command -v claude`.
    # 2. If `file abs_path` contains "shell script", treat as already installed: print message, exit 0.
    # 3. Compute install_dir = dirname(abs_path).
    # 4. If install_dir is not writable: print "ERROR: cannot write to <dir>; install claude into a user-writable path first" and exit 1. NEVER call sudo.
    # 5. If `<install_dir>/claude-real` already exists: print "shim already installed (claude-real present)"; just rewrite the claude wrapper to be safe; exit 0.
    # 6. mv "<install_dir>/claude" "<install_dir>/claude-real"
    # 7. Write the wrapper script. Verify chmod 0755.
    # 8. Verify: `command -v claude` still returns the wrapper path; `head -1` matches the shebang.
    # 9. Print success message.
}

uninstall() {
    # 1. Find the wrapper at the path returned by `command -v claude`.
    # 2. Verify it IS our wrapper (file <path> contains "shell script" AND grep "croam launch" succeeds).
    # 3. Verify "<dir>/claude-real" exists.
    # 4. rm wrapper; mv claude-real -> claude.
    # 5. Print success message.
    # 6. If anything is unexpected, print FAIL: <reason> and exit 1 -- do NOT touch the filesystem.
}
```

Constraints (must be reflected in the script):

- **No sudo**. Ever. If the script needs sudo to proceed, it exits 1 with: `ERROR: cannot write to <install_dir>. Install claude into a user-writable path (e.g., via 'npm i -g @anthropic-ai/claude-code' with NPM_PREFIX=~/.npm-global) and re-run.`
- **Atomic safety**. Use `mv` (not `cp` then `rm`) to preserve atomicity. If anything fails between `mv claude -> claude-real` and `write claude wrapper`, the user is left with `claude-real` but no `claude` -- the script must trap on EXIT and revert (`mv claude-real -> claude` if the wrapper write failed).
- **Idempotent**. Running twice is a no-op the second time. The detection is: `[ -f "<dir>/claude-real" ] && file "<dir>/claude" | grep -q "shell script"` -> already installed.
- **Self-check exit semantics**: 0 = all checks passed, 1 = at least one check failed. Each check prints `[OK] desc` or `[FAIL] desc -- reason` to stdout. Match the format of `croam doctor`.
- **Wrapper script body** (exact text written to `<install_dir>/claude`):
  ```bash
  #!/usr/bin/env bash
  # Auto-generated by croam install-shim.sh. Do not edit.
  exec croam launch "$@"
  ```

### 3. `scripts/install-cctakeover-alias.sh`

Location: `/home/tunc/Sync/Programs/croam/scripts/install-cctakeover-alias.sh`. Mode 0755.

Behavior:

```
Usage:
  install-cctakeover-alias.sh             # install (idempotent)
  install-cctakeover-alias.sh --uninstall # remove the alias line
  install-cctakeover-alias.sh --help      # show usage and exit 0
```

Skeleton:

```bash
#!/usr/bin/env bash
set -euo pipefail

ALIAS_LINE="alias cctakeover='croam'  # added by croam install-cctakeover-alias.sh"

resolve_rc_file() {
    # If $SHELL ends in /zsh: "$HOME/.zshrc"
    # else: "$HOME/.bashrc"
    case "${SHELL:-}" in
        */zsh) echo "$HOME/.zshrc" ;;
        *) echo "$HOME/.bashrc" ;;
    esac
}

main() {
    rc=$(resolve_rc_file)
    case "${1:-install}" in
        --help|-h) print_help; exit 0 ;;
        --uninstall) uninstall "$rc"; exit $? ;;
        install|"") install "$rc"; exit $? ;;
        *) echo "FAIL: unknown arg: $1" >&2; print_help; exit 2 ;;
    esac
}

install() {
    rc=$1
    # 1. Touch the rc file if it doesn't exist.
    # 2. If the rc already contains the marker comment "added by croam install-cctakeover-alias.sh": exit 0 with "alias already installed".
    # 3. Append a newline + ALIAS_LINE to the file.
    # 4. Print "installed alias to <rc>; run 'source <rc>' or open a new shell to activate".
}

uninstall() {
    rc=$1
    # 1. If rc doesn't exist: exit 0 (nothing to do).
    # 2. Remove any line containing the marker comment via temp-file rewrite (sed -i is fine since this is bash; but write to a tmpfile and mv for atomicity).
    # 3. Print "removed alias from <rc>" or "alias not present".
}
```

Constraints:

- **Marker-based idempotency**. The detection MUST be the marker comment string, not the alias text alone (so a user who hand-typed `alias cctakeover='croam'` for some other reason isn't flagged as already installed by us, and uninstall doesn't accidentally remove their hand-typed line).
- **Atomicity**. Write to `<rc>.tmp`, then `mv <rc>.tmp <rc>`. Never modify the file in-place with redirected append if the failure could leave a partial line.
- **Respects $HOME**. All paths are derived from `$HOME`, never hard-coded `/home/tunc/...`. This is what makes the test fixture work (the test sets `HOME=tmp_path`).

### 4. `tests/test_install_scripts.py`

Location: `/home/tunc/Sync/Programs/croam/tests/test_install_scripts.py`.

The tests run the shell scripts as subprocesses against a synthetic `$HOME` rooted at `tmp_path`. They never touch the user's real `~/.zshrc` or system `claude`.

Required tests (one function each):

```python
from __future__ import annotations
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SHIM = PROJECT_ROOT / "scripts" / "install-shim.sh"
INSTALL_ALIAS = PROJECT_ROOT / "scripts" / "install-cctakeover-alias.sh"


@pytest.fixture
def fake_claude_dir(tmp_path: Path) -> Path:
    """Return a tmp_path subdir with a fake claude binary and a fake croam binary."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_claude = bin_dir / "claude"
    fake_claude.write_text("#!/usr/bin/env bash\necho fake-claude-real \"$@\"\n")
    fake_claude.chmod(0o755)
    fake_croam = bin_dir / "croam"
    fake_croam.write_text("#!/usr/bin/env bash\necho fake-croam \"$@\"\n")
    fake_croam.chmod(0o755)
    return bin_dir


def _run(cmd: list[str], env_path: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": f"{env_path}:/usr/bin:/bin", "HOME": str(env_path.parent)}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)


def test_install_shim_self_check_passes_when_prereqs_met(fake_claude_dir: Path) -> None:
    res = _run(["bash", str(INSTALL_SHIM), "--self-check"], fake_claude_dir)
    assert res.returncode == 0, res.stderr
    assert "[OK] claude on PATH" in res.stdout
    assert "[OK] croam on PATH" in res.stdout


def test_install_shim_self_check_fails_when_claude_missing(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # No claude binary, only croam.
    croam = bin_dir / "croam"
    croam.write_text("#!/usr/bin/env bash\n")
    croam.chmod(0o755)
    res = _run(["bash", str(INSTALL_SHIM), "--self-check"], bin_dir)
    assert res.returncode == 1
    assert "[FAIL]" in res.stdout
    assert "claude" in res.stdout


def test_install_shim_renames_and_writes_wrapper(fake_claude_dir: Path) -> None:
    res = _run(["bash", str(INSTALL_SHIM)], fake_claude_dir)
    assert res.returncode == 0, res.stderr
    assert (fake_claude_dir / "claude-real").exists()
    wrapper = fake_claude_dir / "claude"
    assert wrapper.exists()
    body = wrapper.read_text()
    assert "exec croam launch" in body
    assert wrapper.stat().st_mode & 0o111  # executable


def test_install_shim_is_idempotent(fake_claude_dir: Path) -> None:
    r1 = _run(["bash", str(INSTALL_SHIM)], fake_claude_dir)
    assert r1.returncode == 0
    r2 = _run(["bash", str(INSTALL_SHIM)], fake_claude_dir)
    assert r2.returncode == 0
    assert "already installed" in r2.stdout.lower()
    # Second run does NOT re-rename claude-real (the original real binary).
    real = (fake_claude_dir / "claude-real").read_text()
    assert "fake-claude-real" in real


def test_install_shim_refuses_sudo_when_dir_not_writable(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_claude = bin_dir / "claude"
    fake_claude.write_text("#!/usr/bin/env bash\n")
    fake_claude.chmod(0o755)
    croam = bin_dir / "croam"
    croam.write_text("#!/usr/bin/env bash\n")
    croam.chmod(0o755)
    # Make the directory non-writable for the current user.
    bin_dir.chmod(0o555)
    try:
        res = _run(["bash", str(INSTALL_SHIM)], bin_dir)
        assert res.returncode == 1
        assert "cannot write" in res.stderr.lower() or "cannot write" in res.stdout.lower()
        # Should NOT have called sudo or escalated.
        assert "sudo" not in res.stdout.lower()
    finally:
        bin_dir.chmod(0o755)  # restore so pytest can clean up tmp_path


def test_install_shim_uninstall_restores_original(fake_claude_dir: Path) -> None:
    _run(["bash", str(INSTALL_SHIM)], fake_claude_dir)
    res = _run(["bash", str(INSTALL_SHIM), "--uninstall"], fake_claude_dir)
    assert res.returncode == 0
    assert (fake_claude_dir / "claude").exists()
    assert not (fake_claude_dir / "claude-real").exists()
    body = (fake_claude_dir / "claude").read_text()
    assert "fake-claude-real" in body  # original restored


def test_install_alias_appends_marker(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    rc = home / ".bashrc"
    rc.write_text("# existing content\n")
    res = subprocess.run(
        ["bash", str(INSTALL_ALIAS)],
        env={"HOME": str(home), "SHELL": "/bin/bash", "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=10,
    )
    assert res.returncode == 0
    body = rc.read_text()
    assert "alias cctakeover='croam'" in body
    assert "added by croam install-cctakeover-alias.sh" in body


def test_install_alias_picks_zshrc_when_shell_is_zsh(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    res = subprocess.run(
        ["bash", str(INSTALL_ALIAS)],
        env={"HOME": str(home), "SHELL": "/bin/zsh", "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=10,
    )
    assert res.returncode == 0
    assert (home / ".zshrc").exists()
    assert not (home / ".bashrc").exists()
    assert "alias cctakeover='croam'" in (home / ".zshrc").read_text()


def test_install_alias_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "SHELL": "/bin/bash", "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", str(INSTALL_ALIAS)], env=env, check=True, timeout=10)
    res = subprocess.run(["bash", str(INSTALL_ALIAS)], env=env, capture_output=True, text=True, timeout=10)
    assert res.returncode == 0
    body = (home / ".bashrc").read_text()
    # The marker line should appear exactly once.
    assert body.count("added by croam install-cctakeover-alias.sh") == 1


def test_install_alias_uninstall_removes_marker_line(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "SHELL": "/bin/bash", "PATH": "/usr/bin:/bin"}
    subprocess.run(["bash", str(INSTALL_ALIAS)], env=env, check=True, timeout=10)
    res = subprocess.run(
        ["bash", str(INSTALL_ALIAS), "--uninstall"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert res.returncode == 0
    body = (home / ".bashrc").read_text() if (home / ".bashrc").exists() else ""
    assert "added by croam install-cctakeover-alias.sh" not in body
```

Key invariants enforced:

- Tests NEVER call `subprocess.run` with the user's real `HOME`. Every test passes an explicit `env={"HOME": str(tmp_path / "home"), ...}` to subprocess.
- Tests do NOT rely on the conftest `home` fixture for the install-script tests (those operate in a fresh subprocess; the env is built explicitly inline).
- The fake `claude` and fake `croam` scripts are not real binaries; they are bash scripts with the right shebang. `file` will report them as "shell script" -- which matches the real claude case (the user's actual `/usr/bin/claude` is a node shebang script). This is fine because `install-shim.sh` looks for `croam launch` in the body (not just "shell script") to decide if the wrapper is OURS.

One subtlety: the `test_install_shim_renames_and_writes_wrapper` test creates a fake `claude` that itself is a shell script (because we cannot easily fake an ELF binary in a test). The shim install logic must distinguish "any shell script" from "our shim". The check is: open the file, look for the marker `# Auto-generated by croam install-shim.sh`. If absent, it's not our shim and we proceed.

Update step 2 of `install()` accordingly:
```
2. If `file abs_path` contains "shell script" AND `grep -q "Auto-generated by croam install-shim.sh" abs_path`, treat as already installed: print message, exit 0.
```

### 5. Final lint / type pass

Run from project root:

```
uv run ruff check .                  # must exit 0
uv run ruff format --check .         # must exit 0
uv run pyright src/croam             # must exit 0 (warnings tolerated, errors not)
```

If any of these surface fixable issues, fix them in-place. If they surface issues that touch contested files (modules under `src/croam/` owned by earlier phases), the fix is to log the item in this phase's summary as a follow-up rather than to modify the contested file -- the brief is explicit on this: "Be willing to log a 'follow-up' item rather than silently fixing." However, lint/format auto-fixes that ruff applies via `uv run ruff format .` and `uv run ruff check --fix .` are allowed; they are mechanical and reversible. Type errors that require code changes go on the follow-up list.

### 6. Coverage check

```
uv run pytest --cov=src/croam --cov-report=term --cov-fail-under=80
```

Must exit 0. If coverage falls below 80%, the brief says: this is a wrap-up phase, not a cleanup phase. Add the gap to the follow-up list in the summary; do not invent tests in `tests/test_*.py` for code owned by other phases unless the gap is in install-script-related code that this phase introduced.

### 7. `pyproject.toml` version verify

Read `/home/tunc/Sync/Programs/croam/pyproject.toml`. Confirm `version = "0.1.0"`. If it is anything else, edit to "0.1.0". This is a sanity check, not a release.

---

## Implementation order

1. Read `pyproject.toml`. Verify `version = "0.1.0"`.
2. Write `scripts/install-shim.sh`. `chmod +x`. Run `bash scripts/install-shim.sh --help` to sanity-check the script parses and prints usage.
3. Write `scripts/install-cctakeover-alias.sh`. `chmod +x`. Run `bash scripts/install-cctakeover-alias.sh --help` similarly.
4. Write `tests/test_install_scripts.py`. Run `uv run pytest tests/test_install_scripts.py -v`. Iterate until all pass.
5. Write `README.md`. Verify by reading it back; check that all bash blocks are syntactically valid (no smart quotes, no em dash, no missing `EOF`).
6. Run the full test suite: `uv run pytest`. Must exit 0 with coverage >= 80%.
7. Run `CROAM_E2E=1 uv run pytest`. Must exit 0.
8. Run lint/type: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright src/croam`. Fix or log follow-ups.
9. Capture observed `claude` shape on the host: `file $(which claude) > /tmp/croam-claude-shape.txt 2>&1`. Paste the output verbatim into the phase summary's "Evidence Captured" section. This documents what the install script actually faces in the real world (a node shebang wrapper, not a binary -- the script's logic must already handle this).
10. Write the phase summary at `docs/agent/project-start/summaries/PHASE_11_SUMMARY.md`. Update `docs/agent/project-start/STATUS.md`.

---

## Dependencies

**Requires**: Phase 10 complete (integration tests round 1 passing). All earlier phases (1-10) complete.
- Phase 10 is the last phase that adds tests to the suite; this phase's coverage check piggy-backs on its work.

**Enables**: Project ships. No further phases.

---

## Completion Criteria

- [ ] `README.md` exists at the project root, contains all eight required sections (description, install, bootstrap, verbs, configuration, shim install, cctakeover, tests, license), uses ASCII only, contains no `[LABEL]` redaction tags.
- [ ] `scripts/install-shim.sh` exists, mode 0755, supports `install`/`--self-check`/`--uninstall`/`--help`. NEVER calls sudo. Idempotent. EXIT-trap reverts the rename if the wrapper write fails.
- [ ] `scripts/install-cctakeover-alias.sh` exists, mode 0755, supports `install`/`--uninstall`/`--help`. Marker-comment-based idempotency. Atomic write via tmp-file + mv.
- [ ] `tests/test_install_scripts.py` covers self-check (pass + fail), install + idempotency, sudo-refusal, uninstall, alias install + idempotency + uninstall, shell-rc selection by `$SHELL`. All pass.
- [ ] `pyproject.toml` `version` is `"0.1.0"`.
- [ ] `uv run pytest` exits 0.
- [ ] `CROAM_E2E=1 uv run pytest` exits 0.
- [ ] `uv run pytest --cov=src/croam --cov-fail-under=80` exits 0.
- [ ] `uv run ruff check .` exits 0.
- [ ] `uv run ruff format --check .` exits 0.
- [ ] `uv run pyright src/croam` exits 0 (or follow-ups documented).
- [ ] Phase summary at `docs/agent/project-start/summaries/PHASE_11_SUMMARY.md` written. `docs/agent/project-start/STATUS.md` updated.

---

## Testing Requirements

The test module `tests/test_install_scripts.py` is the verification harness for this phase's deliverables. Specifically:

- **Self-check pass case**: fake `claude` and fake `croam` on PATH, `--self-check` exits 0 with `[OK]` lines.
- **Self-check fail case**: only `croam` on PATH (no `claude`), `--self-check` exits 1 with at least one `[FAIL]` line mentioning claude.
- **Install rename + wrapper**: after `bash install-shim.sh`, `claude-real` exists with the original body, `claude` exists with the wrapper body containing `exec croam launch`, both have mode 0755.
- **Idempotency**: running `install-shim.sh` twice is a no-op the second time (output mentions "already installed"; `claude-real` is unchanged).
- **Sudo refusal**: when the install dir lacks write permission for the current user, `install-shim.sh` exits 1 with a message about not being able to write, and stdout/stderr contains no occurrence of `sudo`.
- **Uninstall**: after install + uninstall, `claude-real` is gone, `claude` is the original body.
- **Alias install + marker**: `~/.bashrc` (or `~/.zshrc` per `$SHELL`) gains the alias line and the marker comment.
- **Alias rc selection**: `SHELL=/bin/zsh` -> writes to `.zshrc`; `SHELL=/bin/bash` -> writes to `.bashrc`; missing `SHELL` -> defaults to `.bashrc`.
- **Alias idempotency**: running the alias install twice yields exactly one occurrence of the marker line.
- **Alias uninstall**: removes the marker line cleanly; running uninstall on a missing rc file is a no-op exit 0.

All tests run as part of the default `uv run pytest`. They use `subprocess.run` with explicit `env={...}` parameters; they do NOT inherit the user's real `HOME`, `SHELL`, or `PATH`.

---

## Functional QA

This phase ships Surface 1 (CLI verbs end-to-end via install) per FUNCTIONAL_QA_STRATEGY.md, exercised through Loop A (First-run sanity).

- [ ] **(install surface, Loop A)** Run `bash scripts/install-shim.sh --self-check` against a tmp_path-rooted fake `$PATH` containing only fake `claude` and fake `croam` scripts. Expect exit 0, stdout containing `[OK] claude on PATH` and `[OK] croam on PATH`. Capture stdout and exit code into the phase summary. Cross-reference: this is the same self-check shape Phase 9's `croam doctor` uses.
- [ ] **(install surface, Loop A)** Run `bash scripts/install-shim.sh` twice in sequence against the same tmp_path-rooted fake `$PATH`. First run: exit 0, `<dir>/claude-real` is the original `claude` body, `<dir>/claude` is the new wrapper. Second run: exit 0, output contains "already installed", `<dir>/claude-real` body is unchanged. Paste both runs' stdout + the file contents into the summary.
- [ ] **(install surface, Loop A)** Run `bash scripts/install-cctakeover-alias.sh` against a tmp_path-rooted `$HOME` with `SHELL=/bin/bash`. Expect exit 0, `<HOME>/.bashrc` ends with the alias line and the marker comment. Run a second time; assert the marker appears exactly once.
- [ ] **(install surface, Loop A)** From the project root, run `uv tool install --editable .` (in a tmp venv -- see capture instructions below). Then `cd /tmp` and run `croam --help`. Expect exit 0, stdout lists every verb (`ls`, `attach`, `peek`, `claim`, `fork`, `launch`, `doctor`). Paste the help output. THEN uninstall via `uv tool uninstall croam`. (If running on the user's real machine where `croam` is or isn't already installed, prefer doing this against `UV_TOOL_DIR=$(mktemp -d)` so it does not contaminate the real tool list.)
- [ ] **(install surface, Loop A)** Run `uv run pytest` with no env vars. Expect exit 0; capture the final summary line (`N passed`). Then run `CROAM_E2E=1 uv run pytest`. Expect exit 0; capture the final summary line. Coverage report should show >= 80% on `src/croam/`.
- [ ] **(install surface, Loop A)** After install-shim runs in the tmp_path fake `$PATH`, run `<tmp>/bin/claude --version`. Because the fake `croam` script in the fixture echoes its argv, the output should contain `fake-croam launch --version`. This proves the wrapper-to-croam handoff works. Capture the exact stdout.

Anti-patterns from FUNCTIONAL_QA_STRATEGY.md particularly relevant here:

- **A. Tests that don't redirect HOME silently corrupt the user's real `~/.claude` (and now: `~/.zshrc`)**. The install-script tests MUST pass `HOME=tmp_path` to subprocess. NEVER let the install-cctakeover-alias.sh test inherit the real HOME -- it would append to your actual `~/.zshrc`.
- **C. Tests that mock tmux miss session-naming and socket-isolation bugs**. Not directly applicable here (this phase doesn't touch tmux), but the analog is: tests that mock `subprocess.run` to fake the install scripts miss real bash behavior. We run real bash against real tmp files.

---

## Helpers Required

None. The brief explicitly states "No helpers proposed". The install scripts include `--uninstall` flags so reversal is built in; no out-of-band helper needed.

---

## External Interfaces Consumed

- **The `claude` binary's shape on the host**
  - **Consumed by**: `scripts/install-shim.sh` (must distinguish "real claude" from "already-installed shim").
  - **How to capture**: `file $(which claude) 2>&1; head -3 $(which claude) 2>&1` -- run from a normal user shell. Paste the output verbatim into the phase summary's "Evidence Captured" section. Expectation: claude is typically a node shebang script (`#!/usr/bin/env node` or `#!/usr/bin/env -S node ...`), not an ELF binary, so `file` reports "POSIX shell script" or "a Node.js script". The install-shim must therefore use BODY content (`grep "croam launch"` or `grep "Auto-generated by croam"`) to detect "is this our wrapper", not the bare `file` output.
  - **If not observable**: use the dummy fake binary in the test fixture (a bash script). The install script's BODY-content detection makes both shapes safe.

- **The user's shell rc files (`~/.zshrc`, `~/.bashrc`)**
  - **Consumed by**: `scripts/install-cctakeover-alias.sh`.
  - **How to capture**: `file $HOME/.zshrc $HOME/.bashrc 2>/dev/null; wc -l $HOME/.zshrc $HOME/.bashrc 2>/dev/null` from a normal user shell on at least one host. Paste the output. This documents that the rc file is plain text, possibly multi-thousand lines, and our append-with-marker approach is safe against existing content.
  - **If not observable**: not applicable -- the test fixture creates synthetic rc files at `tmp_path/home/.bashrc` and the script's behavior is fully deterministic against them.

---

## Notes

- This phase is the project wrap-up. It introduces ZERO new functionality. If during the lint/type pass you uncover a real bug in a Phase 1-10 module, the correct response is: log it as a follow-up in the phase summary's "Follow-ups" section, do NOT silently fix it. The conductor's review caches will surface the gap. The exception: ruff auto-fixes (`uv run ruff format .`, `uv run ruff check --fix .`) are mechanical and reversible -- those are fine to apply.
- The README is the only user-facing prose in the project. Spend time on the verb cheat sheet and the shim install steps; these are the parts a real user reads first. Keep prose minimal per the global communication style; technical correctness over flowery descriptions.
- `install-shim.sh` interaction with `npm`-installed claude (the most common shape on the user's system): claude lives at something like `~/.npm-global/bin/claude` and is a small shebang script. `mv` works fine; the wrapper sits in the same dir. Running the wrapper invokes `croam launch`, which Phase 5's shim logic forwards to `claude-real` after deciding tmux-vs-passthrough.
- `install-shim.sh` interaction with system-managed claude (`/usr/bin/claude`): the install dir is not user-writable. The script detects this and exits 1 with the message: `ERROR: cannot write to /usr/bin. Install claude into a user-writable path (e.g., ~/.npm-global/bin via 'npm config set prefix ~/.npm-global && npm i -g @anthropic-ai/claude-code') and re-run.` The user fixes their install location, re-runs, and the shim installs cleanly.
- The cctakeover alias is purely transitional. It is OK if the user removes it later by hand or via `--uninstall`. The alias does NOT need to be reinstalled on shell-config changes; it is a one-shot.
- License section in the README: explicitly note "License pending. Private use by the author until further notice." Do NOT pick a license speculatively.
- ASCII-only for shell scripts as well as the README. No unicode glyphs in `[OK]`/`[FAIL]` markers; use bare brackets and ASCII letters.
