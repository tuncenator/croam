"""Hidden `croam emit-state` verb implementation. Wired by Phase 6's cli.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from croam.hosts import emit_state


def emit_state_cmd(home: Path, state_root: Path, hostname: str) -> int:
    """Print the per-host state JSON to stdout. Returns 0 on success."""
    payload = emit_state(home, state_root, hostname)
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    return 0
