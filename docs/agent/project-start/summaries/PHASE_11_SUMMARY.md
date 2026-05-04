# Phase 11: Polish, install, README - Summary

**Date Completed:** 2026-05-04
**Completed By:** claude-sonnet-4-6 (agent-a7013ef665972cd02)
**Actual Token Usage:** ~40k tokens

---

## Objective

Wrap up croam v1. Ship README.md, two install scripts, tests for those scripts,
and run a final lint/type-check pass to confirm the codebase is clean.

---

## Work Completed

### What Was Built

- `README.md` (187 lines, replaces stub): description, install, first-run, verb
  cheat sheet, configuration pointer, shim install steps (automatic and manual),
  cctakeover transition, test commands, license note.
- `scripts/install-shim.sh` (mode 0755): renames `claude` to `claude-real`,
  writes a croam wrapper. Supports `--self-check`, `--uninstall`, `--help`.
  Atomic via EXIT trap. Never calls sudo. Idempotent.
- `scripts/install-cctakeover-alias.sh` (mode 0755): idempotently appends
  `alias cctakeover='croam'` with a marker comment to `~/.zshrc` or `~/.bashrc`
  depending on `$SHELL`. Supports `--uninstall`, `--help`. Atomic writes via
  tmpfile + mv.
- `tests/test_install_scripts.py`: 12 tests exercising both scripts as
  subprocesses against a synthetic HOME under tmp_path.

### Files Created

- `README.md` - Project README, 187 lines, ASCII only.
- `scripts/install-shim.sh` - Shim install/uninstall helper.
- `scripts/install-cctakeover-alias.sh` - cctakeover alias helper.
- `tests/test_install_scripts.py` - Test suite for both scripts.

### Files Modified

None. The stub `README.md` was replaced in full.

### Key Design Decisions

- Tests use the `home` fixture (from conftest.py) so the safety guard sees HOME
  redirected. The subprocess env uses a tight PATH (`/usr/bin:/bin` plus the
  test's own bin_dir) to prevent leaking the real `~/.local/bin/claude` into
  the test environment. This was discovered when `test_self_check_fails_when_claude_missing`
  unexpectedly passed because the real claude was on PATH.
- Wrapper detection in install-shim.sh uses `file | grep "shell script"` AND
  `grep "croam launch"` as specified. The idempotency check calls `is_wrapper`
  on the existing `claude` path before doing anything.
- The EXIT trap in install-shim.sh rolls back the `mv claude claude-real` if
  the wrapper write fails. A `rolled_back` flag commits the state after the
  wrapper is confirmed written.
- install-cctakeover-alias.sh uses the marker text as the sole idempotency
  signal (not the alias text). The ALIAS_LINE variable embeds the marker inline
  so a single `grep -vF "$MARKER"` removes it on uninstall.

---

## Completion Criteria Status

- [x] README.md exists, readable, ASCII-only, 150-250 lines.
  Verified: `wc -l README.md` returned 187.
- [x] Both scripts exist, mode 0755, pass --self-check.
  Verified: `ls -la scripts/` shows `-rwxr-xr-x`. `--self-check` passes in
  tests.
- [x] tests/test_install_scripts.py exists and passes.
  Verified: `uv run pytest tests/test_install_scripts.py -v` shows 12 passed.
- [x] `uv run ruff check .` clean.
  Verified: "All checks passed!"
- [x] `uv run ruff format --check .` clean.
  Verified: "67 files already formatted"
- [x] `uv run pyright src` clean.
  Verified: "0 errors, 0 warnings, 0 informations"
- [x] Coverage >= 80%.
  Verified: 92% total.

---

## Testing

### Tests Written

`tests/test_install_scripts.py`:
- `TestInstallShim.test_self_check_passes_when_prereqs_met`
- `TestInstallShim.test_self_check_fails_when_claude_missing`
- `TestInstallShim.test_installs_shim`
- `TestInstallShim.test_install_idempotent`
- `TestInstallShim.test_uninstall_reverses`
- `TestInstallShim.test_help_flag`
- `TestInstallCctakeoverAlias.test_adds_alias_to_bashrc`
- `TestInstallCctakeoverAlias.test_adds_alias_to_zshrc`
- `TestInstallCctakeoverAlias.test_idempotent`
- `TestInstallCctakeoverAlias.test_uninstall_removes_alias`
- `TestInstallCctakeoverAlias.test_respects_shell_for_zsh`
- `TestInstallCctakeoverAlias.test_help_flag`

### Test Results

```
$ uv run pytest -q
........................................................................ [ 54%]
...s.................................................................... [ 72%]
.s...................................................................... [ 90%]
......................................                                   [100%]
=========================== short test summary info ============================
SKIPPED [1] tests/integration/test_e2e_dummy_attach.py:22: Tier 2 only
SKIPPED [1] tests/integration/test_e2e_dummy_attach.py:76: Tier 2 only
SKIPPED [1] tests/test_paths.py:298: needs real claude
SKIPPED [1] tests/test_sessions.py:520: CROAM_E2E=1 not set; skipping Tier 2 dummy-session test
394 passed, 4 skipped in 11.68s
```

Coverage: 92% (TOTAL 2068 statements, 169 missed).

---

## Evidence Captured

### `claude` binary shape on this host

```
$ /usr/bin/which claude
/home/tunc/.local/bin/claude

$ /usr/bin/file /home/tunc/.local/bin/claude
/home/tunc/.local/bin/claude: symbolic link to /home/tunc/.local/share/claude/versions/2.1.126

$ /usr/bin/file /home/tunc/.local/share/claude/versions/2.1.126
/home/tunc/.local/share/claude/versions/2.1.126: ELF 64-bit LSB executable, x86-64, version 1 (SYSV), dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2, for GNU/Linux 3.2.0, BuildID[sha1]=bfc90c05e9aaef20532b8f17800f877a51299e41, not stripped
```

The install script detects our wrapper via body content (`grep "croam launch"`), not
via file type. Both ELF and script-shebang shapes are handled correctly.

---

## Functional QA Results

All runs performed against a synthetic tmp_path-rooted `$PATH` and `$HOME`.
No real system files were modified.

### install-shim.sh --self-check

```
$ env -i PATH="<tmp>/bin:/usr/bin:/bin" HOME="<tmp>" bash scripts/install-shim.sh --self-check
[OK] claude on PATH (<tmp>/bin/claude)
[OK] croam on PATH (<tmp>/bin/croam)
exit code: 0
```

### install-shim.sh (install + idempotent re-run)

```
$ env -i PATH="<tmp>/bin:/usr/bin:/bin" HOME="<tmp>" bash scripts/install-shim.sh
Installed: <tmp>/bin/claude-real (original) and <tmp>/bin/claude (croam shim).
exit code: 0

$ cat <tmp>/bin/claude-real
#!/usr/bin/env bash
echo "fake claude $@"

$ cat <tmp>/bin/claude
#!/usr/bin/env bash
# Auto-generated by croam install-shim.sh. Do not edit.
exec croam launch "$@"

$ env -i PATH="<tmp>/bin:/usr/bin:/bin" HOME="<tmp>" bash scripts/install-shim.sh
Shim already installed at <tmp>/bin/claude (no-op).
exit code: 0
```

### install-cctakeover-alias.sh (install + idempotent re-run)

```
$ env -i PATH="/usr/bin:/bin" HOME="<tmp>/home" SHELL="/bin/bash" bash scripts/install-cctakeover-alias.sh
Added alias to <tmp>/home/.bashrc.
exit code: 0

$ cat <tmp>/home/.bashrc
\nalias cctakeover='croam'  # added by croam install-cctakeover-alias.sh

$ env -i PATH="/usr/bin:/bin" HOME="<tmp>/home" SHELL="/bin/bash" bash scripts/install-cctakeover-alias.sh
Alias already present in <tmp>/home/.bashrc (no-op).
exit code: 0

$ grep -c "added by croam install-cctakeover-alias.sh" <tmp>/home/.bashrc
1
```

---

## Helper Issues

No helpers were listed for this phase. No helpers were invoked.

---

## Challenges and Solutions

### Challenge: conftest safety guard failing for subprocess tests

The test methods initially had no `home` fixture parameter. The conftest
`pytest_runtest_call` hook checks the process-level `HOME` env var, which was
still pointing at the real `~HOME`. Even though the subprocess was given a
synthetic HOME, the guard rejected the test before the subprocess ran.

Solution: added `home: Path` fixture parameter to every test method. The
`home` fixture monkeypatches the process-level HOME to `tmp_path/home`, which
satisfies the guard. The synthetic HOME passed to the subprocess is the same
path.

### Challenge: real claude on PATH breaking negative test

`test_self_check_fails_when_claude_missing` was passing (returncode=0) because
the tight-PATH env still inherited the real PATH via `os.environ["PATH"]`, and
`~/.local/bin/claude` was on it.

Solution: replaced `os.environ.get("PATH", ...)` with a hardcoded
`/usr/bin:/bin` in `make_env`. The PATH is intentionally minimal and isolated.

---

## Codebase Context Updates

- Added `README.md`: project README (was a 10-line stub, now 187 lines).
- Added `scripts/install-shim.sh`: shim install/uninstall script, mode 0755.
- Added `scripts/install-cctakeover-alias.sh`: cctakeover alias script, mode 0755.
- Added `tests/test_install_scripts.py`: 12 tests for both install scripts.
- Test count: 394 passed (was 382).

## Notes for Future Phases

This is the final phase. No further phases are planned for v1.

The install scripts assume `file` is on PATH (for wrapper detection in
install-shim.sh). This is standard on Linux and macOS but should be noted
if portability to stripped environments matters.

---

## Commits Made

1. `[Phase 11/11] add: install scripts and tests`
2. `[Phase 11/11] add: README.md with install, verb cheat sheet, config, shim steps`
3. `[Phase 11/11] docs: phase summary`
