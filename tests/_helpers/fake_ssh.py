"""Backing module for the ssh_shim fixture.

Fake-ssh script body and the (host, argv) -> fixture path encoding.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# The fake ssh script body. __FIXTURES_DIR__ is a literal placeholder
# replaced by the conftest at install time.
SSH_SHIM_SCRIPT = (
    "#!/usr/bin/env python3\n"
    '"""Fake ssh shim for croam tests. Reads canned responses from disk."""\n'
    r"""import hashlib
import json
import os
import sys
import time

FIXTURES_DIR = "__FIXTURES_DIR__"


def parse_args(argv):
    # Drop ssh option flags (-o KEY=VAL, -i KEY, -p PORT, -F CONFIG) and
    # find the host (first positional that doesn't look like a flag value).
    skip = False
    pos = []
    for tok in argv[1:]:
        if skip:
            skip = False
            continue
        if tok in ("-o", "-i", "-p", "-F", "-l", "-c", "-J"):
            skip = True
            continue
        if tok.startswith("-"):
            continue
        pos.append(tok)
    if not pos:
        return None, []
    return pos[0], pos[1:]


def main():
    host, command = parse_args(sys.argv)
    if host is None:
        sys.stderr.write("fake-ssh: no host argument\n")
        sys.exit(255)
    cmd_blob = json.dumps(command, sort_keys=True).encode("utf-8")
    h = hashlib.sha1(cmd_blob).hexdigest()[:16]
    fixture = os.path.join(FIXTURES_DIR, f"{host}__{h}.json")
    if not os.path.exists(fixture):
        sys.stderr.write(f"fake-ssh: no fixture for ({host!r}, {command!r}) -> {fixture}\n")
        sys.exit(255)
    with open(fixture) as f:
        data = json.load(f)
    delay = float(data.get("delay_s") or 0)
    if delay > 0:
        time.sleep(delay)
    sys.stdout.write(data.get("stdout", ""))
    sys.stderr.write(data.get("stderr", ""))
    sys.exit(int(data.get("exit_code", 0)))


if __name__ == "__main__":
    main()
"""
)


def fixture_path_for(fixtures_dir: Path, host: str, argv: list[str]) -> Path:
    """Compute the fixture file path for a (host, argv) pair.

    The fake-ssh shim and the test-side registry must agree on this encoding.
    """
    cmd_blob = json.dumps(argv, sort_keys=True).encode("utf-8")
    h = hashlib.sha1(cmd_blob).hexdigest()[:16]
    return fixtures_dir / f"{host}__{h}.json"
