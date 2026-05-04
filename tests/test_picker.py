"""Tests for src/croam/picker.py.

Phase 6: 9 tests covering pure formatters, render_rows, fzf argv construction,
launch_picker happy/cancel/no-match/error paths, and compute_action_intersection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from croam.errors import CroamError
from croam.picker import (
    PickerRow,
    build_fzf_argv,
    compute_action_intersection,
    format_input_lines,
    format_last_column,
    launch_picker,
)
from tests._helpers.fake_fzf import make_fake_fzf

NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "ms_ago,expected",
    [
        (None, "-"),
        (30_000, "0m"),
        (14 * 60 * 1_000, "14m"),
        (60 * 60 * 1_000, "1h"),
        (47 * 60 * 60 * 1_000, "47h"),
        (48 * 60 * 60 * 1_000, "2D"),
        (5 * 24 * 60 * 60 * 1_000, "5D"),
        (30 * 24 * 60 * 60 * 1_000, "30D"),
        (31 * 24 * 60 * 60 * 1_000, "1M"),
        (60 * 24 * 60 * 60 * 1_000, "2M"),
    ],
)
def test_format_last_column(home, ms_ago, expected):
    if ms_ago is None:
        result = format_last_column(None, NOW)
    else:
        ms_now = int(NOW.timestamp() * 1000)
        result = format_last_column(ms_now - ms_ago, NOW)
    assert result == expected


def test_format_input_lines_exact_shape(home):
    rows = [
        PickerRow(
            sid="abc12345-aaaa-bbbb-cccc-111111111111",
            glyph="o",
            status_word="running-idle",
            reach_word="reachable",
            cwd_word="present",
            host="stormtree",
            last="2m",
            cwd_display="~/Programs/onlayer-x",
            name="iso27001 controls draft",
        ),
        PickerRow(
            sid="def45678-2222-3333-4444-555555555555",
            glyph="O",
            status_word="unreachable",
            reach_word="unreachable",
            cwd_word="missing-cwd",
            host="vicar",
            last="1d",
            cwd_display="/home/work/onlayer-eu",
            name="refactor mart_*",
        ),
    ]
    out = format_input_lines(rows)
    expected = (
        "abc12345-aaaa-bbbb-cccc-111111111111\to\trunning-idle\t"
        "reachable\tpresent\tstormtree\t2m\t~/Programs/onlayer-x\t"
        "iso27001 controls draft\n"
        "def45678-2222-3333-4444-555555555555\tO\tunreachable\t"
        "unreachable\tmissing-cwd\tvicar\t1d\t/home/work/onlayer-eu\t"
        "refactor mart_*\n"
    )
    assert out == expected


def test_format_input_lines_scrubs_tabs_and_newlines(home):
    row = PickerRow(
        sid="x",
        glyph="o",
        status_word="running-idle",
        reach_word="reachable",
        cwd_word="present",
        host="h",
        last="-",
        cwd_display="~",
        name="a\tb\nc",
    )
    out = format_input_lines([row])
    # Name column (last field) should have no tabs.
    assert "\t" not in out.split("\n")[0].split("\t")[-1]
    # Only the trailing newline.
    assert out.count("\n") == 1


def test_format_input_lines_empty(home):
    assert format_input_lines([]) == ""


def test_render_rows_with_lineage(home):
    """A sid with a lineage entry has [<parent>-F#<n>] appended to its name."""
    pytest.importorskip("croam.sessions")
    pytest.importorskip("croam.ownership")

    from croam.hosts import HostStatus
    from croam.ownership import Assertion
    from croam.picker import render_rows
    from croam.sessions import ClaudeSession

    parent_sid = "abc12345-pppp-aaaa-rrrr-eeeeeeeeeeee"
    fork_sid = "fff45678-ffff-oooo-rrrr-kkkkkkkkkkkk"

    sessions = [
        ClaudeSession(
            sid=fork_sid,
            cwd=home / "Programs/croam",
            transcript_path=home / ".claude/projects/-x/x.jsonl",
            pid=None,
            status=None,
            started_at_ms=None,
            updated_at_ms=None,
            name=None,
            version=None,
        )
    ]
    assertions = {
        fork_sid: Assertion(
            sid=fork_sid,
            owner="self",
            asserted_at=NOW,
            action="create",
            cwd_normalized="~/Programs/croam",
            previous_owner=None,
        )
    }
    host_statuses = {"self": HostStatus(name="self", reachable=True, last_probed=NOW, error=None)}

    from types import SimpleNamespace

    lineage = {fork_sid: SimpleNamespace(parent_sid=parent_sid, fork_n=1)}
    rows = render_rows(
        sessions=sessions,
        assertions=assertions,
        host_statuses=host_statuses,
        pwd=None,
        lineage=lineage,
        now=NOW,
    )
    assert len(rows) == 1
    assert "[abc123-F#1]" in rows[0].name


def test_render_rows_missing_cwd(home):
    """A session whose cwd doesn't exist locally has cwd_word == 'missing-cwd'."""
    pytest.importorskip("croam.sessions")

    from croam.hosts import HostStatus
    from croam.ownership import Assertion
    from croam.picker import render_rows
    from croam.sessions import ClaudeSession

    nonexistent = home / "does/not/exist"
    sid = "missing-cwd-sid-aaaa-bbbb-cccccccccccc"
    sessions = [
        ClaudeSession(
            sid=sid,
            cwd=nonexistent,
            transcript_path=home / ".claude/projects/-x/x.jsonl",
            pid=None,
            status=None,
            started_at_ms=None,
            updated_at_ms=None,
            name=None,
            version=None,
        )
    ]
    assertions = {
        sid: Assertion(
            sid=sid,
            owner="self",
            asserted_at=NOW,
            action="create",
            cwd_normalized=str(nonexistent),
            previous_owner=None,
        )
    }
    host_statuses = {"self": HostStatus(name="self", reachable=True, last_probed=NOW, error=None)}
    rows = render_rows(
        sessions=sessions,
        assertions=assertions,
        host_statuses=host_statuses,
        pwd=None,
        lineage={},
        now=NOW,
    )
    assert len(rows) == 1
    assert rows[0].cwd_word == "missing-cwd"


def test_compute_action_intersection_excludes_claim_and_fork_when_unreachable_or_missing(home):
    """Per spec section 4: mixed selection drops claim/fork."""
    row_local = PickerRow(
        sid="a",
        glyph="o",
        status_word="running-idle",
        reach_word="reachable",
        cwd_word="present",
        host="self",
        last="2m",
        cwd_display="~",
        name="a",
    )
    row_remote_unreachable = PickerRow(
        sid="b",
        glyph="O",
        status_word="unreachable",
        reach_word="unreachable",
        cwd_word="missing-cwd",
        host="vicar",
        last="3h",
        cwd_display="/x",
        name="b",
    )
    result = compute_action_intersection([row_local, row_remote_unreachable], self_hostname="self")
    assert "claim" not in result
    assert "fork" not in result
    assert "peek" in result
    assert "fork-here" in result


def test_compute_action_intersection_empty(home):
    assert compute_action_intersection([], self_hostname="self") == set()


def test_build_fzf_argv_includes_required_flags(home):
    argv = build_fzf_argv(filter_pwd=Path("/home/tunc/Programs/croam"))
    assert "--multi" in argv
    assert "--ansi" in argv
    assert "--with-nth=2,6,7,8,9" in argv
    assert "--expect=p,c,f,C,F,ctrl-r" in argv
    assert any("--bind=multi:transform-header" in a for a in argv)
    assert any(a.startswith("--query=") and "/home/tunc/Programs/croam" in a for a in argv)


def test_build_fzf_argv_no_pwd(home):
    argv = build_fzf_argv(filter_pwd=None)
    assert not any(a.startswith("--query=") for a in argv)


def test_launch_picker_happy_path(home, tmp_path, monkeypatch):
    """fake-fzf prints '<key>\\n<row1>\\n<row2>'; assert (key, [row1, row2])."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    rows = [
        PickerRow(
            sid="row1-sid",
            glyph="o",
            status_word="running-idle",
            reach_word="reachable",
            cwd_word="present",
            host="h",
            last="-",
            cwd_display="~",
            name="r1",
        ),
        PickerRow(
            sid="row2-sid",
            glyph="o",
            status_word="running-idle",
            reach_word="reachable",
            cwd_word="present",
            host="h",
            last="-",
            cwd_display="~",
            name="r2",
        ),
    ]
    fake = make_fake_fzf(
        tmp_path,
        output=(
            "p\n"
            "row1-sid\to\trunning-idle\treachable\tpresent\th\t-\t~\tr1\n"
            "row2-sid\to\trunning-idle\treachable\tpresent\th\t-\t~\tr2\n"
        ),
        exit_code=0,
    )
    key, selected = launch_picker(rows, filter_pwd=None, fzf_binary=str(fake))
    assert key == "p"
    assert [r.sid for r in selected] == ["row1-sid", "row2-sid"]


def test_launch_picker_cancel(home, tmp_path, monkeypatch):
    """rc=130 (Ctrl-C cancel) returns ("", []). Must actually launch the subprocess."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    dummy_row = PickerRow(
        sid="cancel-sid",
        glyph="o",
        status_word="archived",
        reach_word="reachable",
        cwd_word="present",
        host="h",
        last="-",
        cwd_display="~",
        name="cancel-test",
    )
    fake = make_fake_fzf(tmp_path, output="", exit_code=130)
    key, selected = launch_picker([dummy_row], filter_pwd=None, fzf_binary=str(fake))
    assert key == ""
    assert selected == []


def test_launch_picker_no_match(home, tmp_path, monkeypatch):
    """rc=1 (no match) returns ("", []). Must actually launch the subprocess."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    dummy_row = PickerRow(
        sid="nomatch-sid",
        glyph="o",
        status_word="archived",
        reach_word="reachable",
        cwd_word="present",
        host="h",
        last="-",
        cwd_display="~",
        name="nomatch-test",
    )
    fake = make_fake_fzf(tmp_path, output="", exit_code=1)
    key, selected = launch_picker([dummy_row], filter_pwd=None, fzf_binary=str(fake))
    assert key == ""
    assert selected == []


def test_launch_picker_error(home, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    fake = make_fake_fzf(tmp_path, output="", exit_code=2)
    dummy_row = PickerRow(
        sid="x",
        glyph="o",
        status_word="archived",
        reach_word="reachable",
        cwd_word="present",
        host="h",
        last="-",
        cwd_display="~",
        name="x",
    )
    with pytest.raises(CroamError, match=r"fzf exited with code 2"):
        launch_picker([dummy_row], filter_pwd=None, fzf_binary=str(fake))


def test_launch_picker_refuses_non_tty(home, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(CroamError, match=r"interactive terminal"):
        launch_picker([], filter_pwd=None)
