"""Reusable fake-fzf shell script generator for picker tests."""

from __future__ import annotations

import stat
from pathlib import Path


def _shell_quote(s: str) -> str:
    """Single-quote a string for safe inclusion in a bash printf '%s' argument."""
    return "'" + s.replace("'", "'\\''") + "'"


def make_fake_fzf(
    tmp_path: Path,
    *,
    output: str,
    exit_code: int = 0,
    write_keyfile: str | None = None,
) -> Path:
    """Create an executable fake-fzf script that emits `output` and exits with `exit_code`.

    The script discards its stdin (fzf would consume it; for tests we don't need to round-trip).
    If `write_keyfile` is set, the script extracts the keyfile path from its argv
    (looking for --bind=p:execute-silent(echo p > KEYFILE)+accept) and writes the value.
    Returns the path to the script. Caller passes it as `fzf_binary=str(path)`.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "fake_fzf"

    keyfile_logic = ""
    if write_keyfile is not None:
        keyfile_logic = (
            "# Extract keyfile path from argv and write the action key.\n"
            "for arg in \"$@\"; do\n"
            "  if [[ \"$arg\" == --bind=p:execute-silent* ]]; then\n"
            "    KEYFILE=$(echo \"$arg\" | sed 's/.*echo .* > //;s/).*//') \n"
            f"    printf '%s' {_shell_quote(write_keyfile)} > \"$KEYFILE\"\n"
            "    break\n"
            "  fi\n"
            "done\n"
        )

    body = (
        "#!/bin/bash\n"
        "cat > /dev/null\n"
        f"{keyfile_logic}"
        f"printf '%s' {_shell_quote(output)}\n"
        f"exit {exit_code}\n"
    )
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script
