"""Tests for src/croam/paths.py.

Tests 1-13 are Tier 1 (synthetic fixtures only).
Test 14 is Tier 2 (gated on CROAM_E2E=1).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from croam.errors import ConfigError
from croam.paths import decode_cwd, denormalize_cwd, encode_cwd, normalize_cwd
from tests._helpers.synth_jsonl import _encode_cwd as synth_encode_cwd

# ---------------------------------------------------------------------------
# Test 1: encode_cwd against verified examples from the spec table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "input_path, expected",
    [
        ("/tmp/croam-e2e", "-tmp-croam-e2e"),
        ("/home/tunc/.claude", "-home-tunc--claude"),
        ("/home/tunc/.claude/commands", "-home-tunc--claude-commands"),
        ("/home/tunc/Programs/croam", "-home-tunc-Programs-croam"),
        ("/home/tunc/Sync/.config/nvim", "-home-tunc-Sync--config-nvim"),
        (
            "/home/tunc/Sync/Programs/aegis/.claude/worktrees/agent-a4501029b9062dc9a",
            "-home-tunc-Sync-Programs-aegis--claude-worktrees-agent-a4501029b9062dc9a",
        ),
    ],
)
def test_encode_examples(home: Path, input_path: str, expected: str) -> None:
    """Verify encode_cwd against the six spec-table examples."""
    assert encode_cwd(input_path) == expected


# ---------------------------------------------------------------------------
# Test 2: dot-segment encoding for leading-dot components
# ---------------------------------------------------------------------------

def test_encode_dot_segment(home: Path) -> None:
    """Leading-dot components have their dot replaced by '-'."""
    assert encode_cwd("/x/.claude") == "-x--claude"
    assert encode_cwd("/x/.config") == "-x--config"
    assert encode_cwd("/x/.local") == "-x--local"
    # Root-level dot dir: /.claude -> --claude
    assert encode_cwd("/.claude") == "--claude"


# ---------------------------------------------------------------------------
# Test 3: double-slash input is collapsed by Path
# ---------------------------------------------------------------------------

def test_encode_double_slash_collapsed(home: Path) -> None:
    """Double slashes are collapsed by Path.parts; single dash between segments."""
    assert encode_cwd(Path("/foo//bar")) == "-foo-bar"


# ---------------------------------------------------------------------------
# Test 4: relative path raises ValueError
# ---------------------------------------------------------------------------

def test_encode_relative_path_raises(home: Path) -> None:
    """encode_cwd raises ValueError for relative paths (programmer error)."""
    with pytest.raises(ValueError, match="encode_cwd requires an absolute path"):
        encode_cwd("foo/bar")


# ---------------------------------------------------------------------------
# Test 5: decode with fs_probe resolves ambiguity by filesystem existence
# ---------------------------------------------------------------------------

def test_decode_lossy_with_fs_probe(home: Path) -> None:
    """fs_probe picks the candidate that actually exists on disk."""
    # Build the encoded form of <home>/foo/bar
    encoded_foo_bar = "-" + str(home / "foo" / "bar").replace("/", "-")[1:]

    # Only /foo/bar exists: decode should return home/foo/bar
    (home / "foo" / "bar").mkdir(parents=True)
    result = decode_cwd(encoded_foo_bar, host_home=home, fs_probe=True)
    assert result == home / "foo" / "bar"

    # Rebuild: only home/foo-bar exists
    import shutil
    shutil.rmtree(home / "foo")
    (home / "foo-bar").mkdir(parents=True)
    encoded_foo_dash_bar = "-" + str(home / "foo-bar").replace("/", "-")[1:]
    result2 = decode_cwd(encoded_foo_dash_bar, host_home=home, fs_probe=True)
    assert result2 == home / "foo-bar"


# ---------------------------------------------------------------------------
# Test 6: decode without fs_probe returns deterministic best-guess
# ---------------------------------------------------------------------------

def test_decode_no_probe_returns_most_likely(home: Path) -> None:
    """fs_probe=False heuristic: every '--' -> '/.', every '-' -> '/'.
    For -tmp-croam-e2e this yields /tmp/croam/e2e (each '-' is a separator).
    This is the known-lossy result for paths with literal dashes.
    """
    result = decode_cwd("-tmp-croam-e2e", fs_probe=False)
    assert result == Path("/tmp/croam/e2e")


# ---------------------------------------------------------------------------
# Test 7: decode dot-segment path with fs_probe
# ---------------------------------------------------------------------------

def test_decode_dot_segment_with_fs_probe(home: Path) -> None:
    """Dot-segment encoded path decodes to the .dotdir path when it exists."""
    (home / ".claude" / "commands").mkdir(parents=True)
    # encode home/.claude/commands then decode
    encoded = encode_cwd(home / ".claude" / "commands")
    result = decode_cwd(encoded, host_home=home, fs_probe=True)
    assert result == home / ".claude" / "commands"


# ---------------------------------------------------------------------------
# Test 8: decode_cwd raises ConfigError for invalid input
# ---------------------------------------------------------------------------

def test_decode_invalid_input_raises(home: Path) -> None:
    """decode_cwd raises ConfigError when input lacks leading '-' or no path found."""
    with pytest.raises(ConfigError) as exc_info:
        decode_cwd("no-leading-dash", fs_probe=False)
    assert exc_info.value.field == "encoded_cwd"

    with pytest.raises(ConfigError) as exc_info2:
        decode_cwd("", fs_probe=False)
    assert exc_info2.value.field == "encoded_cwd"

    # fs_probe=True with a path guaranteed not to exist raises ConfigError
    with pytest.raises(ConfigError) as exc_info3:
        decode_cwd("-zzzz-nonexistent-xyzzy-99999", host_home=None, fs_probe=True)
    assert exc_info3.value.field == "encoded_cwd"


# ---------------------------------------------------------------------------
# Test 9: normalize_cwd under home
# ---------------------------------------------------------------------------

def test_normalize_under_home(home: Path) -> None:
    """normalize_cwd returns ~/relative for paths under host_home."""
    assert normalize_cwd(home / "Programs/croam", home) == "~/Programs/croam"


# ---------------------------------------------------------------------------
# Test 10: normalize_cwd outside home returns absolute string
# ---------------------------------------------------------------------------

def test_normalize_outside_home(home: Path) -> None:
    """normalize_cwd returns absolute string for paths outside host_home."""
    assert normalize_cwd(Path("/tmp/croam-e2e"), Path("/home/tunc")) == "/tmp/croam-e2e"


# ---------------------------------------------------------------------------
# Test 11: normalize_cwd when cwd equals home
# ---------------------------------------------------------------------------

def test_normalize_equals_home(home: Path) -> None:
    """normalize_cwd returns '~' (no trailing slash) when cwd == host_home."""
    assert normalize_cwd(home, home) == "~"


# ---------------------------------------------------------------------------
# Test 12: denormalize_cwd round-trip
# ---------------------------------------------------------------------------

def test_denormalize_round_trip(home: Path) -> None:
    """denormalize_cwd(normalize_cwd(p)) == p for paths under home."""
    original = home / "x" / "y"
    normalized = normalize_cwd(original, home)
    assert denormalize_cwd(normalized, home) == original


# ---------------------------------------------------------------------------
# Test 13: denormalize_cwd with absolute path
# ---------------------------------------------------------------------------

def test_denormalize_absolute(home: Path) -> None:
    """denormalize_cwd returns Path(normalized) unchanged for absolute paths."""
    assert denormalize_cwd("/tmp/foo", home) == Path("/tmp/foo")


# ---------------------------------------------------------------------------
# Cross-verification: encode_cwd matches synth_jsonl._encode_cwd
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path_str",
    [
        "/tmp/croam-e2e",
        "/home/tunc/Programs/croam",
        "/home/tunc/.claude",
    ],
)
def test_encode_matches_synth_jsonl(home: Path, path_str: str) -> None:
    """paths.encode_cwd and synth_jsonl._encode_cwd must produce identical output."""
    p = Path(path_str)
    assert encode_cwd(p) == synth_encode_cwd(p)


# ---------------------------------------------------------------------------
# Coverage helpers -- exercise internal branches not covered by spec tests
# ---------------------------------------------------------------------------

def test_decode_no_probe_dot_segment(home: Path) -> None:
    """_no_probe_best_guess handles '--' (dot-prefix) correctly."""
    # -home-tunc--claude -> /home/tunc/.claude
    result = decode_cwd("-home-tunc--claude", fs_probe=False)
    assert result == Path("/home/tunc/.claude")


def test_decode_no_probe_with_host_home_no_match(home: Path) -> None:
    """Fallback to strategy-2 when host_home prefix does not match encoded."""
    import tempfile

    # Use a path that does NOT start with encode_cwd(home)
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "aaa"
        d.mkdir()
        encoded = encode_cwd(d)
        # decode with a completely different host_home so prefix doesn't match
        result = decode_cwd(encoded, host_home=home, fs_probe=True)
        assert result == d


def test_decode_exactly_host_home(home: Path) -> None:
    """Decode an encoded string that equals encode_cwd(host_home) exactly."""
    encoded = encode_cwd(home)
    result = decode_cwd(encoded, host_home=home, fs_probe=True)
    assert result == home


def test_decode_no_host_home_uses_strategy2(home: Path) -> None:
    """Without host_home, strategy-2 full enumeration handles simple paths."""
    # /tmp exists on every Linux host
    result = decode_cwd("-tmp", host_home=None, fs_probe=True)
    assert result == Path("/tmp")


def test_decode_dot_segment_no_host_home(home: Path) -> None:
    """Strategy-2 (no host_home) handles dot-segment paths via single-empty branch."""
    import tempfile

    # Use a short path so strategy-2 candidate count stays well under the cap.
    # Create a dotdir under a fresh tmpdir so we control the depth.
    with tempfile.TemporaryDirectory(prefix="s2-") as td:
        dot_dir = Path(td) / ".x"
        dot_dir.mkdir()
        encoded = encode_cwd(dot_dir)
        result = decode_cwd(encoded, host_home=None, fs_probe=True)
        assert result == dot_dir


def test_denormalize_tilde_alone(home: Path) -> None:
    """denormalize_cwd('~', home) returns home."""
    assert denormalize_cwd("~", home) == home


def test_denormalize_tilde_user_raises(home: Path) -> None:
    """denormalize_cwd raises ValueError for ~user/... paths."""
    with pytest.raises(ValueError, match="does not support"):
        denormalize_cwd("~otheruser/foo", home)


def test_normalize_relative_raises(home: Path) -> None:
    """normalize_cwd raises ValueError for relative paths."""
    with pytest.raises(ValueError, match="normalize_cwd requires an absolute path"):
        normalize_cwd(Path("relative/path"), home)


# ---------------------------------------------------------------------------
# Test 14: Tier 2 -- e2e dummy encoding confirmed against real ~/.claude/projects
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.environ.get("CROAM_E2E"), reason="needs real claude")
def test_e2e_dummy_encoding(e2e_dummy: tuple[Path, str]) -> None:
    """Confirm encode_cwd matches real claude directory name for the dummy session."""
    dummy_path, dummy_sid = e2e_dummy
    assert encode_cwd(dummy_path) == "-tmp-croam-e2e"
    # The encoded dir must exist in the user's real ~/.claude/projects
    encoded_dir = Path.home() / ".claude/projects" / "-tmp-croam-e2e"
    assert encoded_dir.is_dir(), f"expected {encoded_dir} to exist"
    assert (encoded_dir / f"{dummy_sid}.jsonl").is_file()
