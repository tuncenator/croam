"""Tests for src/croam/commands/ls.py via the CLI surface."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from croam.cli import app


@pytest.fixture
def runner():
    return CliRunner()


def _write_config(home: Path, hostname: str = "stormtree", extra_hosts: str = "") -> Path:
    """Write a minimal config.toml. Returns config path."""
    cfg = home / ".config" / "croam" / "config.toml"
    content = f'[self]\nhostname = "{hostname}"\n\n[hosts.{hostname}]\nssh = "{hostname}"\n'
    if extra_hosts:
        content += extra_hosts
    cfg.write_text(content)
    return cfg


def _seed_session(
    home: Path, state_root: Path, hostname: str, cwd: Path, *, updated_at_ms: int | None = None
) -> str:
    """Create a synthetic JSONL + assertion, return sid."""
    from tests._helpers.synth_assertions import build_assertion, write_assertions_file
    from tests._helpers.synth_jsonl import build_jsonl

    sid = str(uuid.uuid4())
    build_jsonl(home, sid, cwd)

    now = datetime.now(UTC)
    if updated_at_ms is not None:
        # Store the right asserted_at for the last_days filter to work
        asserted = datetime.fromtimestamp(updated_at_ms / 1000, tz=UTC)
    else:
        asserted = now
    assertion = build_assertion(
        sid,
        hostname,
        asserted,
        cwd_normalized=f"~/{cwd.relative_to(home)}" if cwd.is_relative_to(home) else str(cwd),
    )
    existing = {}
    ownership_path = state_root / hostname / "ownership.json"
    if ownership_path.exists():
        from croam.ownership import read_local_assertions

        existing = dict(read_local_assertions(state_root, hostname))
    existing[sid] = assertion
    write_assertions_file(state_root, hostname, existing)
    return sid


# ---------------------------------------------------------------------------
# test_ls_json_empty
# ---------------------------------------------------------------------------


def test_ls_json_empty(home: Path, state_root: Path, runner):
    """Empty state -> exit 0, stdout == '[]'."""
    _write_config(home)
    result = runner.invoke(app, ["--json", "ls"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "[]"


# ---------------------------------------------------------------------------
# test_ls_returns_zero_with_empty_state
# ---------------------------------------------------------------------------


def test_ls_returns_zero_with_empty_state(home: Path, state_root: Path, runner):
    """No sessions, text mode -> exit 0, empty stdout."""
    _write_config(home)
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# test_ls_json_one_local
# ---------------------------------------------------------------------------


def test_ls_json_one_local(home: Path, state_root: Path, runner, monkeypatch: pytest.MonkeyPatch):
    """One local session -> schema check, owner == self_hostname, last_activity ISO8601."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)

    sid = _seed_session(home, state_root, "stormtree", cwd)

    result = runner.invoke(app, ["--json", "ls"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert len(rows) == 1
    row = rows[0]
    for key in (
        "sid",
        "owner",
        "host_reachable",
        "status",
        "cwd",
        "last_activity",
        "is_orphan",
        "name",
    ):
        assert key in row, f"missing key {key!r}"
    assert row["sid"] == sid
    assert row["owner"] == "stormtree"
    assert row["is_orphan"] is False
    if row["last_activity"] is not None:
        assert re.match(r"\d{4}-\d{2}-\d{2}T", row["last_activity"])


# ---------------------------------------------------------------------------
# test_ls_text_mode
# ---------------------------------------------------------------------------


def test_ls_text_mode(home: Path, state_root: Path, runner, monkeypatch: pytest.MonkeyPatch):
    """Text mode: at least one line containing first 8 chars of sid."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)

    sid = _seed_session(home, state_root, "stormtree", cwd)

    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0, result.output
    assert sid[:8] in result.output


# ---------------------------------------------------------------------------
# test_ls_filter_pwd
# ---------------------------------------------------------------------------


def test_ls_filter_pwd(home: Path, state_root: Path, runner, monkeypatch: pytest.MonkeyPatch):
    """With 2 sessions in different cwds, only the one matching cwd is returned."""
    _write_config(home)
    cwd_a = home / "proj_a"
    cwd_b = home / "proj_b"
    cwd_a.mkdir(parents=True)
    cwd_b.mkdir(parents=True)

    sid_a = _seed_session(home, state_root, "stormtree", cwd_a)
    _sid_b = _seed_session(home, state_root, "stormtree", cwd_b)

    monkeypatch.chdir(cwd_a)

    result = runner.invoke(app, ["--json", "ls"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    sids = [r["sid"] for r in rows]
    assert sid_a in sids
    assert _sid_b not in sids


# ---------------------------------------------------------------------------
# test_ls_all_flag
# ---------------------------------------------------------------------------


def test_ls_all_flag(home: Path, state_root: Path, runner):
    """--all: reads ownership from all host subdirs, returns entries from both."""
    # Config with two hosts
    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\n'
    _write_config(home, extra_hosts=cfg_extra)

    cwd_a = home / "proj_a"
    cwd_a.mkdir(parents=True)
    sid_local = _seed_session(home, state_root, "stormtree", cwd_a)

    # Seed a vicar assertion directly
    from tests._helpers.synth_assertions import build_assertion, write_assertions_file

    sid_vicar = str(uuid.uuid4())
    # Create vicar dir and seed ownership
    (state_root / "vicar").mkdir(parents=True, exist_ok=True)
    vicar_assertion = build_assertion(
        sid_vicar,
        "vicar",
        datetime.now(UTC),
        cwd_normalized="~/remote-proj",
    )
    write_assertions_file(state_root, "vicar", {sid_vicar: vicar_assertion})

    result = runner.invoke(app, ["--all", "--json", "ls"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    sids = [r["sid"] for r in rows]
    assert sid_local in sids
    assert sid_vicar in sids


# ---------------------------------------------------------------------------
# test_ls_host_filter
# ---------------------------------------------------------------------------


def test_ls_host_filter(home: Path, state_root: Path, runner):
    """--host vicar: returns only vicar entries."""
    cfg_extra = '\n[hosts.vicar]\nssh = "vicar"\n'
    _write_config(home, extra_hosts=cfg_extra)

    cwd_a = home / "proj_a"
    cwd_a.mkdir(parents=True)
    _sid_local = _seed_session(home, state_root, "stormtree", cwd_a)

    from tests._helpers.synth_assertions import build_assertion, write_assertions_file

    sid_vicar = str(uuid.uuid4())
    (state_root / "vicar").mkdir(parents=True, exist_ok=True)
    vicar_assertion = build_assertion(
        sid_vicar,
        "vicar",
        datetime.now(UTC),
        cwd_normalized="~/remote-proj",
    )
    write_assertions_file(state_root, "vicar", {sid_vicar: vicar_assertion})

    result = runner.invoke(app, ["--all", "--host", "vicar", "--json", "ls"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert len(rows) == 1
    assert rows[0]["owner"] == "vicar"


# ---------------------------------------------------------------------------
# test_ls_orphans_hidden_by_default
# ---------------------------------------------------------------------------


def test_ls_orphans_hidden_by_default(
    home: Path, state_root: Path, runner, monkeypatch: pytest.MonkeyPatch
):
    """JSONL on disk with no assertion -> empty list without --orphans."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)

    from tests._helpers.synth_jsonl import build_jsonl

    _sid = str(uuid.uuid4())
    build_jsonl(home, _sid, cwd)  # no assertion written

    result = runner.invoke(app, ["--json", "ls"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert rows == []


# ---------------------------------------------------------------------------
# test_ls_orphans_with_flag
# ---------------------------------------------------------------------------


def test_ls_orphans_with_flag(
    home: Path, state_root: Path, runner, monkeypatch: pytest.MonkeyPatch
):
    """--orphans shows orphan JSONL with is_orphan=True and owner=None."""
    _write_config(home)
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)

    from tests._helpers.synth_jsonl import build_jsonl

    sid = str(uuid.uuid4())
    build_jsonl(home, sid, cwd)

    result = runner.invoke(app, ["--orphans", "--json", "ls"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert len(rows) == 1
    assert rows[0]["is_orphan"] is True
    assert rows[0]["owner"] is None


# ---------------------------------------------------------------------------
# test_ls_last_window
# ---------------------------------------------------------------------------


def test_ls_last_window(home: Path, state_root: Path, runner):
    """--last 30: only sessions with last_activity within 30 days."""
    _write_config(home)

    cwd = home / "proj"
    cwd.mkdir(parents=True)

    now = datetime.now(UTC)
    ten_days_ago_ms = int((now - timedelta(days=10)).timestamp() * 1000)
    hundred_days_ago_ms = int((now - timedelta(days=100)).timestamp() * 1000)

    sid_recent = _seed_session(home, state_root, "stormtree", cwd, updated_at_ms=ten_days_ago_ms)
    _sid_old = _seed_session(home, state_root, "stormtree", cwd, updated_at_ms=hundred_days_ago_ms)

    result = runner.invoke(app, ["--all", "--last", "30", "--json", "ls"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    sids = [r["sid"] for r in rows]
    assert sid_recent in sids
    assert _sid_old not in sids
