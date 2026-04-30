"""Default (no-verb) picker dispatch. Stubbed in Phase 6, step 1; fleshed out at step 5."""

from __future__ import annotations

from pathlib import Path

from croam.config import Config


def run_picker(*, config: Config, home: Path, ctx_obj: dict) -> int:
    """Orchestrate: discover -> render -> launch -> dispatch. Stub until step 5."""
    raise NotImplementedError("Phase 6 step 5 fills this in")
