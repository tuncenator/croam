"""Tests for scripts/install-shim.sh and scripts/install-cctakeover-alias.sh.

These tests run the scripts as subprocesses against a synthetic HOME in tmp_path.
They use the `home` fixture so the conftest safety guard sees HOME redirected.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

# Resolve the scripts directory relative to the project root.
PROJECT_ROOT = Path(__file__).parent.parent
INSTALL_SHIM = PROJECT_ROOT / "scripts" / "install-shim.sh"
INSTALL_ALIAS = PROJECT_ROOT / "scripts" / "install-cctakeover-alias.sh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_script(
    script: Path,
    args: list[str],
    env: dict[str, str],
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a shell script as a subprocess with the given env and args."""
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


def make_fake_claude(bin_dir: Path) -> None:
    """Create a fake `claude` executable in bin_dir."""
    claude = bin_dir / "claude"
    claude.write_text("#!/usr/bin/env bash\necho 'fake claude'\n")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_env(home: Path, bin_dir: Path | None = None, shell: str = "/bin/bash") -> dict[str, str]:
    """Build a minimal env dict for subprocess use.

    Uses a tight PATH (only bin_dir + /usr/bin + /bin) to avoid picking up
    binaries from the user's real PATH (e.g. ~/.local/bin/claude).
    """
    path_parts = [str(bin_dir)] if bin_dir else []
    path_parts.append("/usr/bin")
    path_parts.append("/bin")
    return {
        "HOME": str(home),
        "PATH": ":".join(path_parts),
        "SHELL": shell,
    }


# ---------------------------------------------------------------------------
# install-shim.sh tests
# ---------------------------------------------------------------------------


class TestInstallShim:
    def test_self_check_passes_when_prereqs_met(self, home: Path, tmp_path: Path) -> None:
        """--self-check exits 0 when claude is on PATH."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        make_fake_claude(bin_dir)

        env = make_env(home, bin_dir)
        result = run_script(INSTALL_SHIM, ["--self-check"], env)
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    def test_self_check_fails_when_claude_missing(self, home: Path, tmp_path: Path) -> None:
        """--self-check exits non-zero when claude is not on PATH."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        # deliberately do NOT create fake claude

        env = make_env(home, bin_dir)
        result = run_script(INSTALL_SHIM, ["--self-check"], env)
        assert result.returncode != 0, "expected failure when claude is missing"

    def test_installs_shim(self, home: Path, tmp_path: Path) -> None:
        """install-shim.sh renames claude to claude-real and creates a wrapper."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        make_fake_claude(bin_dir)

        env = make_env(home, bin_dir)
        result = run_script(INSTALL_SHIM, [], env)
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

        # claude-real should exist (original binary renamed)
        claude_real = bin_dir / "claude-real"
        assert claude_real.exists(), "claude-real not found after install"

        # claude wrapper should exist and contain 'croam launch'
        claude_wrapper = bin_dir / "claude"
        assert claude_wrapper.exists(), "claude wrapper not found after install"
        wrapper_text = claude_wrapper.read_text()
        assert "croam launch" in wrapper_text, f"wrapper missing 'croam launch': {wrapper_text!r}"

    def test_install_idempotent(self, home: Path, tmp_path: Path) -> None:
        """Second run is a no-op (exits 0, does not duplicate or corrupt)."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        make_fake_claude(bin_dir)

        env = make_env(home, bin_dir)
        # First install
        result1 = run_script(INSTALL_SHIM, [], env)
        assert result1.returncode == 0, f"first install failed: {result1.stdout!r}"

        # Second install (idempotent)
        result2 = run_script(INSTALL_SHIM, [], env)
        assert result2.returncode == 0, f"second install failed: {result2.stdout!r}"

        # claude-real should still be the original binary
        claude_real = bin_dir / "claude-real"
        assert claude_real.exists(), "claude-real gone after second run"
        original_content = claude_real.read_text()
        assert "fake claude" in original_content, "claude-real content changed after second run"

        # claude wrapper should still have 'croam launch'
        claude_wrapper = bin_dir / "claude"
        assert "croam launch" in claude_wrapper.read_text()

    def test_uninstall_reverses(self, home: Path, tmp_path: Path) -> None:
        """--uninstall renames claude-real back to claude and removes the wrapper."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        make_fake_claude(bin_dir)

        env = make_env(home, bin_dir)
        # Install first
        result = run_script(INSTALL_SHIM, [], env)
        assert result.returncode == 0

        # Now uninstall
        result_un = run_script(INSTALL_SHIM, ["--uninstall"], env)
        assert result_un.returncode == 0, f"uninstall failed: {result_un.stdout!r}"

        # claude should be back (original content)
        claude_path = bin_dir / "claude"
        assert claude_path.exists(), "claude not restored after uninstall"
        assert "fake claude" in claude_path.read_text(), "claude restored with wrong content"

        # claude-real should be gone
        claude_real = bin_dir / "claude-real"
        assert not claude_real.exists(), "claude-real still present after uninstall"

    def test_help_flag(self, home: Path) -> None:
        """--help exits 0 and prints usage."""
        env = make_env(home)
        result = run_script(INSTALL_SHIM, ["--help"], env)
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "usage" in result.stderr.lower()


# ---------------------------------------------------------------------------
# install-cctakeover-alias.sh tests
# ---------------------------------------------------------------------------


class TestInstallCctakeoverAlias:
    MARKER = "# added by croam install-cctakeover-alias.sh"

    def test_adds_alias_to_bashrc(self, home: Path) -> None:
        """Script appends alias to ~/.bashrc when SHELL ends in bash."""
        bashrc = home / ".bashrc"
        bashrc.write_text("# existing bashrc\n")

        env = make_env(home, shell="/bin/bash")
        result = run_script(INSTALL_ALIAS, [], env)
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

        content = bashrc.read_text()
        assert "alias cctakeover='croam'" in content, f"alias not found in .bashrc: {content!r}"
        assert self.MARKER in content, f"marker not found in .bashrc: {content!r}"

    def test_adds_alias_to_zshrc(self, home: Path) -> None:
        """Script appends alias to ~/.zshrc when SHELL ends in zsh."""
        zshrc = home / ".zshrc"
        zshrc.write_text("# existing zshrc\n")

        env = make_env(home, shell="/bin/zsh")
        result = run_script(INSTALL_ALIAS, [], env)
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

        content = zshrc.read_text()
        assert "alias cctakeover='croam'" in content, f"alias not found in .zshrc: {content!r}"
        assert self.MARKER in content, f"marker not found in .zshrc: {content!r}"

    def test_idempotent(self, home: Path) -> None:
        """Second run does not add a second alias line."""
        bashrc = home / ".bashrc"
        bashrc.write_text("")

        env = make_env(home, shell="/bin/bash")
        run_script(INSTALL_ALIAS, [], env)
        run_script(INSTALL_ALIAS, [], env)

        content = bashrc.read_text()
        count = content.count(self.MARKER)
        assert count == 1, f"marker appears {count} times (expected 1): {content!r}"

    def test_uninstall_removes_alias(self, home: Path) -> None:
        """--uninstall removes the alias block added by the script."""
        bashrc = home / ".bashrc"
        bashrc.write_text("# pre-existing line\n")

        env = make_env(home, shell="/bin/bash")
        # Install
        result = run_script(INSTALL_ALIAS, [], env)
        assert result.returncode == 0

        # Uninstall
        result_un = run_script(INSTALL_ALIAS, ["--uninstall"], env)
        assert result_un.returncode == 0, f"uninstall failed: {result_un.stdout!r}"

        content = bashrc.read_text()
        assert "alias cctakeover" not in content, (
            f"alias still present after uninstall: {content!r}"
        )
        assert self.MARKER not in content, f"marker still present after uninstall: {content!r}"
        # Pre-existing content should survive
        assert "pre-existing line" in content

    def test_respects_shell_for_zsh(self, home: Path) -> None:
        """SHELL=/usr/bin/zsh writes to .zshrc, not .bashrc."""
        zshrc = home / ".zshrc"
        zshrc.write_text("")
        bashrc = home / ".bashrc"
        bashrc.write_text("")

        env = make_env(home, shell="/usr/bin/zsh")
        run_script(INSTALL_ALIAS, [], env)

        # alias should be in .zshrc
        assert self.MARKER in zshrc.read_text()
        # .bashrc should be untouched
        assert self.MARKER not in bashrc.read_text()

    def test_help_flag(self, home: Path) -> None:
        """--help exits 0 and prints usage."""
        env = make_env(home)
        result = run_script(INSTALL_ALIAS, ["--help"], env)
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "usage" in result.stderr.lower()
