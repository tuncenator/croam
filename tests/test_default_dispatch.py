"""Tests for commands/default.py:_dispatch (Phase 7 wiring)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from croam.picker import PickerRow


def _make_row(
    sid: str | None = None, reach_word: str = "reachable", cwd_word: str = "present"
) -> PickerRow:
    return PickerRow(
        sid=sid or str(uuid.uuid4()),
        glyph="o",
        status_word="idle",
        reach_word=reach_word,
        cwd_word=cwd_word,
        host="stormtree",
        last="-",
        cwd_display="~/proj",
        name="test-session",
    )


def _make_config(home: Path, state_root: Path, hostname: str = "stormtree"):
    """Create a minimal Config for dispatch tests."""
    from croam.config import load_config

    cfg = home / ".config" / "croam" / "config.toml"
    cfg.write_text(f'[self]\nhostname = "{hostname}"\n\n[hosts.{hostname}]\nssh = "{hostname}"\n')
    return load_config(cfg)


def _dispatch(expect_key, selected, ctx_obj, config, home):
    from croam.commands.default import _dispatch as _d

    return _d(
        expect_key=expect_key,
        selected=selected,
        ctx_obj=ctx_obj,
        config=config,
        home=home,
    )


# ---------------------------------------------------------------------------
# Single-row: enter -> attach
# ---------------------------------------------------------------------------


def test_dispatch_enter_calls_attach(home: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Empty expect_key -> attach.run called."""
    config = _make_config(home, state_root)
    row = _make_row()
    captured: dict = {}

    def fake_attach_run(sid, ctx_obj, config, home, **kw):
        captured["sid"] = sid
        captured["called"] = "attach"
        return 0

    monkeypatch.setattr("croam.commands.attach.run", fake_attach_run)
    rc = _dispatch("", [row], {}, config, home)
    assert rc == 0
    assert captured.get("called") == "attach"
    assert captured.get("sid") == row.sid


# ---------------------------------------------------------------------------
# Single-row: "p" -> peek
# ---------------------------------------------------------------------------


def test_dispatch_p_calls_peek(home: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Key 'p' -> peek.run called."""
    config = _make_config(home, state_root)
    row = _make_row()
    captured: dict = {}

    def fake_peek_run(sid, ctx_obj, config, home, **kw):
        captured["sid"] = sid
        captured["called"] = "peek"
        return 0

    monkeypatch.setattr("croam.commands.peek.run", fake_peek_run)
    rc = _dispatch("p", [row], {}, config, home)
    assert rc == 0
    assert captured.get("called") == "peek"


# ---------------------------------------------------------------------------
# ctrl-r: re-runs run_picker
# ---------------------------------------------------------------------------


def test_dispatch_ctrl_r_reruns_picker(
    home: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """ctrl-r -> calls run_picker again, returns its value."""
    config = _make_config(home, state_root)
    row = _make_row()
    captured: dict = {}

    def fake_run_picker(**kw):
        captured["called"] = "run_picker"
        return 77

    monkeypatch.setattr("croam.commands.default.run_picker", fake_run_picker)
    rc = _dispatch("ctrl-r", [row], {}, config, home)
    assert rc == 77
    assert captured.get("called") == "run_picker"


# ---------------------------------------------------------------------------
# "c" / "C" -> claim (raises SessionNotFound for unknown sid)
# ---------------------------------------------------------------------------


def test_dispatch_c_claims_session(home: Path, state_root: Path):
    from croam.errors import SessionNotFound

    config = _make_config(home, state_root)
    row = _make_row()
    with pytest.raises(SessionNotFound):
        _dispatch("c", [row], {}, config, home)


def test_dispatch_C_claims_session_here(home: Path, state_root: Path):
    from croam.errors import SessionNotFound

    config = _make_config(home, state_root)
    row = _make_row()
    with pytest.raises(SessionNotFound):
        _dispatch("C", [row], {}, config, home)


# ---------------------------------------------------------------------------
# "f" / "F" -> fork (raises SessionNotFound for missing JSONL)
# ---------------------------------------------------------------------------


def test_dispatch_f_forks_session(home: Path, state_root: Path):
    from croam.errors import SessionNotFound

    config = _make_config(home, state_root)
    row = _make_row()
    with pytest.raises(SessionNotFound):
        _dispatch("f", [row], {}, config, home)


def test_dispatch_F_forks_session_here(home: Path, state_root: Path):
    from croam.errors import SessionNotFound

    config = _make_config(home, state_root)
    row = _make_row()
    with pytest.raises(SessionNotFound):
        _dispatch("F", [row], {}, config, home)


# ---------------------------------------------------------------------------
# Unknown key: returns 0 without crashing
# ---------------------------------------------------------------------------


def test_dispatch_unknown_key_returns_0(home: Path, state_root: Path):
    config = _make_config(home, state_root)
    row = _make_row()
    rc = _dispatch("z", [row], {}, config, home)
    assert rc == 0


# ---------------------------------------------------------------------------
# Multi-row: action in intersection -> iterate all rows
# ---------------------------------------------------------------------------


def test_dispatch_multi_row_attach(home: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Multi-row enter -> attach runs for each row."""
    config = _make_config(home, state_root)
    rows = [_make_row(), _make_row()]
    called: list[str] = []

    def fake_attach_run(sid, ctx_obj, cfg, h, **kw):
        called.append(sid)
        return 0

    monkeypatch.setattr("croam.commands.attach.run", fake_attach_run)
    rc = _dispatch("", rows, {}, config, home)
    assert rc == 0
    assert called == [rows[0].sid, rows[1].sid]


# ---------------------------------------------------------------------------
# Multi-row: action NOT in intersection -> returns 0
# ---------------------------------------------------------------------------


def test_dispatch_multi_row_action_not_in_intersection(
    home: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch
):
    """Multi-row enter with unreachable rows -> attach not in intersection -> 0."""
    config = _make_config(home, state_root)
    # reach_word="unreachable" means attach not in per-row safe actions
    rows = [_make_row(reach_word="unreachable"), _make_row(reach_word="unreachable")]
    called: list[str] = []

    def fake_attach_run(sid, ctx_obj, cfg, h, **kw):
        called.append(sid)
        return 0

    monkeypatch.setattr("croam.commands.attach.run", fake_attach_run)
    rc = _dispatch("", rows, {}, config, home)
    assert rc == 0
    assert called == []  # never called because attach not in intersection


# ---------------------------------------------------------------------------
# Multi-row peek: peek is always in intersection
# ---------------------------------------------------------------------------


def test_dispatch_multi_row_peek(home: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Multi-row 'p' -> peek runs for each row (peek always in intersection)."""
    config = _make_config(home, state_root)
    rows = [_make_row(), _make_row()]
    called: list[str] = []

    def fake_peek_run(sid, ctx_obj, cfg, h, **kw):
        called.append(sid)
        return 0

    monkeypatch.setattr("croam.commands.peek.run", fake_peek_run)
    rc = _dispatch("p", rows, {}, config, home)
    assert rc == 0
    assert called == [rows[0].sid, rows[1].sid]
