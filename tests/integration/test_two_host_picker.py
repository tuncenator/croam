"""Integration: picker round-trip with two-host synthetic environment.

Verifies that render_rows produces picker rows from merged two-host assertions
and that format_input_lines produces valid fzf wire format.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from tests._helpers.synth_assertions import build_assertion, write_assertions_file
from tests._helpers.synth_jsonl import build_jsonl
from tests._helpers.synth_session import build_session_metadata
from tests.integration.conftest import TwoHostEnv


class TestPickerRowRendering:
    """Picker renders combined assertions from both hosts."""

    def test_rows_include_stormtree_and_vicar_sessions(
        self, two_host_env: TwoHostEnv
    ) -> None:
        """Sessions owned by each host both appear in rendered rows."""
        from croam.ownership import merge_assertions, read_all_assertions
        from croam.picker import render_rows
        from croam.sessions import discover_local_sessions

        st = two_host_env.stormtree
        sid_st = str(uuid.uuid4())
        sid_vc = str(uuid.uuid4())

        cwd = st.home / "projects" / "alpha"
        cwd.mkdir(parents=True)

        # Build JSONLs + session metadata in stormtree's home.
        build_jsonl(st.home, sid_st, cwd)
        build_session_metadata(st.home, 1001, sid_st, cwd)

        build_jsonl(st.home, sid_vc, cwd)
        build_session_metadata(st.home, 1002, sid_vc, cwd)

        # Assertions: stormtree owns sid_st, vicar owns sid_vc.
        t_now = datetime.now(UTC)
        write_assertions_file(
            st.state_root,
            "stormtree",
            {sid_st: build_assertion(sid_st, "stormtree", t_now)},
        )
        write_assertions_file(
            st.state_root,
            "vicar",
            {sid_vc: build_assertion(sid_vc, "vicar", t_now - timedelta(minutes=5))},
        )

        sessions = discover_local_sessions(st.home)
        per_host = read_all_assertions(st.state_root)
        merged = merge_assertions(per_host)

        rows = render_rows(
            sessions=sessions,
            assertions=merged,
            host_statuses={},
            pwd=None,
            lineage={},
        )

        sids_in_rows = {r.sid for r in rows}
        assert sid_st in sids_in_rows
        assert sid_vc in sids_in_rows

    def test_rows_host_field_reflects_owner(self, two_host_env: TwoHostEnv) -> None:
        """Each picker row's host field matches the assertion owner."""
        from croam.ownership import merge_assertions, read_all_assertions
        from croam.picker import render_rows
        from croam.sessions import discover_local_sessions

        st = two_host_env.stormtree
        sid_st = str(uuid.uuid4())
        sid_vc = str(uuid.uuid4())

        cwd = st.home / "work"
        cwd.mkdir(parents=True)

        build_jsonl(st.home, sid_st, cwd)
        build_session_metadata(st.home, 2001, sid_st, cwd)
        build_jsonl(st.home, sid_vc, cwd)
        build_session_metadata(st.home, 2002, sid_vc, cwd)

        t = datetime.now(UTC)
        write_assertions_file(
            st.state_root,
            "stormtree",
            {sid_st: build_assertion(sid_st, "stormtree", t)},
        )
        write_assertions_file(
            st.state_root,
            "vicar",
            {sid_vc: build_assertion(sid_vc, "vicar", t)},
        )

        sessions = discover_local_sessions(st.home)
        merged = merge_assertions(read_all_assertions(st.state_root))

        rows = render_rows(
            sessions=sessions,
            assertions=merged,
            host_statuses={},
            pwd=None,
            lineage={},
        )

        by_sid = {r.sid: r for r in rows}
        assert by_sid[sid_st].host == "stormtree"
        assert by_sid[sid_vc].host == "vicar"

    def test_format_input_lines_produces_tab_delimited_rows(
        self, two_host_env: TwoHostEnv
    ) -> None:
        """format_input_lines output has 9 tab-separated columns per row."""
        from croam.ownership import merge_assertions, read_all_assertions
        from croam.picker import format_input_lines, render_rows
        from croam.sessions import discover_local_sessions

        st = two_host_env.stormtree
        sid = str(uuid.uuid4())
        cwd = st.home / "code"
        cwd.mkdir(parents=True)

        build_jsonl(st.home, sid, cwd)
        build_session_metadata(st.home, 3001, sid, cwd)

        t = datetime.now(UTC)
        write_assertions_file(
            st.state_root,
            "stormtree",
            {sid: build_assertion(sid, "stormtree", t)},
        )

        sessions = discover_local_sessions(st.home)
        merged = merge_assertions(read_all_assertions(st.state_root))
        rows = render_rows(
            sessions=sessions,
            assertions=merged,
            host_statuses={},
            pwd=None,
            lineage={},
        )

        assert rows, "expected at least one row"
        wire = format_input_lines(rows)
        for line in wire.strip().splitlines():
            cols = line.split("\t")
            assert len(cols) == 9, f"expected 9 tab-cols, got {len(cols)}: {line!r}"


class TestPickerActionIntersection:
    """compute_action_intersection with mixed reachability rows."""

    def test_intersection_when_all_reachable(self, two_host_env: TwoHostEnv) -> None:
        """All rows reachable: attach, peek, claim, fork all in intersection."""
        from croam.picker import PickerRow, compute_action_intersection

        rows = [
            PickerRow(
                sid="aaa",
                glyph="o",
                status_word="running-idle",
                reach_word="reachable",
                cwd_word="present",
                host="stormtree",
                last="5m",
                cwd_display="~/code",
                name="my-session",
            ),
            PickerRow(
                sid="bbb",
                glyph="o",
                status_word="archived",
                reach_word="reachable",
                cwd_word="present",
                host="vicar",
                last="1h",
                cwd_display="~/code",
                name="other-session",
            ),
        ]
        result = compute_action_intersection(rows, self_hostname="stormtree")
        assert "peek" in result
        assert "attach" in result

    def test_intersection_when_one_unreachable(self, two_host_env: TwoHostEnv) -> None:
        """One unreachable row: attach removed from intersection."""
        from croam.picker import PickerRow, compute_action_intersection

        rows = [
            PickerRow(
                sid="aaa",
                glyph="o",
                status_word="running-idle",
                reach_word="reachable",
                cwd_word="present",
                host="stormtree",
                last="5m",
                cwd_display="~/code",
                name="s1",
            ),
            PickerRow(
                sid="bbb",
                glyph="O",
                status_word="unreachable",
                reach_word="unreachable",
                cwd_word="missing-cwd",
                host="vicar",
                last="2D",
                cwd_display="~/code",
                name="s2",
            ),
        ]
        result = compute_action_intersection(rows, self_hostname="stormtree")
        assert "attach" not in result
        assert "peek" in result
