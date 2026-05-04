"""Tests for Phase 2 display formatting: fish_truncate_path and extract_first_user_message.

These tests follow TDD: written BEFORE the implementation. They will fail until
fish_truncate_path and extract_first_user_message are added to picker.py.
"""

from __future__ import annotations

import json
import uuid

import pytest

from tests._helpers.synth_jsonl import build_jsonl

# ---------------------------------------------------------------------------
# fish_truncate_path tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,home_arg,expected",
    [
        # Standard deep path -- each intermediate component truncated to first char.
        ("/home/tunc/Programs/onlayer-x/internal/iam", "/home/tunc", "~/P/o/i/iam"),
        # Two-component path after home prefix.
        ("/home/tunc/Programs/croam", "/home/tunc", "~/P/croam"),
        # Path IS home.
        ("/home/tunc", "/home/tunc", "~"),
        # No home prefix: absolute path, components truncated.
        ("/opt/services/myapp", "/home/tunc", "/o/s/myapp"),
        # Root only.
        ("/", "/home/tunc", "/"),
        # Single component, nothing to truncate.
        ("/usr", "/home/tunc", "/usr"),
        # Dotfile component: keep dot + first char.
        ("/home/tunc/.config/croam", "/home/tunc", "~/.c/croam"),
        # Tilde-prefixed input: already starts with ~/, treat it correctly.
        ("~/Programs/croam", "/home/tunc", "~/P/croam"),
    ],
)
def test_fish_truncate_path(home, path, home_arg, expected):
    from croam.picker import fish_truncate_path

    result = fish_truncate_path(path, home_arg)
    assert result == expected


def test_fish_truncate_path_single_after_home(home):
    """Single component after home prefix: return as-is (~/croam, not ~/c)."""
    from croam.picker import fish_truncate_path

    result = fish_truncate_path("/home/tunc/croam", "/home/tunc")
    assert result == "~/croam"


def test_fish_truncate_path_home_with_trailing_slash(home):
    """home arg ends with /: still works."""
    from croam.picker import fish_truncate_path

    result = fish_truncate_path("/home/tunc/Programs/croam", "/home/tunc/")
    # Should still produce ~/P/croam (strip trailing slash from home before matching).
    assert result == "~/P/croam"


# ---------------------------------------------------------------------------
# extract_first_user_message tests
# ---------------------------------------------------------------------------


def test_extract_first_user_message_happy_path(home):
    """Transcript with user messages returns first one."""
    from croam.picker import extract_first_user_message

    sid = str(uuid.uuid4())
    cwd = home / "Projects" / "test"
    jsonl_path = build_jsonl(home, sid, cwd, n_user=1)

    result = extract_first_user_message(jsonl_path)
    assert result == "synthetic prompt 0"


def test_extract_first_user_message_truncation(home):
    """Message longer than max_chars gets truncated and appended with '...'."""
    from croam.picker import extract_first_user_message

    sid = str(uuid.uuid4())

    # Write a custom JSONL with a long message.
    encoded = "-Projects-test"
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = proj_dir / f"{sid}.jsonl"

    long_msg = "a" * 100  # longer than default 80
    lines = [
        {"type": "last-prompt", "leafUuid": str(uuid.uuid4()), "sessionId": sid},
        {
            "type": "user",
            "message": {"role": "user", "content": long_msg},
            "uuid": str(uuid.uuid4()),
            "timestamp": 1000,
        },
    ]
    with jsonl_path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    result = extract_first_user_message(jsonl_path)
    assert result is not None
    assert len(result) == 83  # 80 + len("...")
    assert result.endswith("...")
    assert result[:80] == "a" * 80


def test_extract_first_user_message_skips_empty_content(home):
    """Skips empty user messages, returns next non-empty one."""
    from croam.picker import extract_first_user_message

    sid = str(uuid.uuid4())
    encoded = "-Projects-test"
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = proj_dir / f"{sid}.jsonl"

    lines = [
        {"type": "last-prompt", "leafUuid": str(uuid.uuid4()), "sessionId": sid},
        {
            "type": "user",
            "message": {"role": "user", "content": ""},
            "uuid": str(uuid.uuid4()),
        },
        {
            "type": "user",
            "message": {"role": "user", "content": "   "},
            "uuid": str(uuid.uuid4()),
        },
        {
            "type": "user",
            "message": {"role": "user", "content": "real message here"},
            "uuid": str(uuid.uuid4()),
        },
    ]
    with jsonl_path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    result = extract_first_user_message(jsonl_path)
    assert result == "real message here"


def test_extract_first_user_message_no_user_lines(home):
    """No user messages -> returns None."""
    from croam.picker import extract_first_user_message

    sid = str(uuid.uuid4())
    encoded = "-Projects-test"
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = proj_dir / f"{sid}.jsonl"

    lines = [
        {"type": "last-prompt", "leafUuid": str(uuid.uuid4()), "sessionId": sid},
        {"type": "permission-mode", "permissionMode": "default"},
    ]
    with jsonl_path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    result = extract_first_user_message(jsonl_path)
    assert result is None


def test_extract_first_user_message_file_not_found(home):
    """Nonexistent path returns None."""
    from croam.picker import extract_first_user_message

    result = extract_first_user_message(home / "does_not_exist.jsonl")
    assert result is None


def test_extract_first_user_message_malformed_json_skipped(home):
    """Malformed JSON lines are skipped; valid user message still returned."""
    from croam.picker import extract_first_user_message

    sid = str(uuid.uuid4())
    encoded = "-Projects-test2"
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = proj_dir / f"{sid}.jsonl"

    with jsonl_path.open("w", encoding="utf-8") as f:
        f.write("not json at all\n")
        f.write("{broken json\n")
        line = {
            "type": "user",
            "message": {"role": "user", "content": "good message"},
            "uuid": str(uuid.uuid4()),
        }
        f.write(json.dumps(line) + "\n")

    result = extract_first_user_message(jsonl_path)
    assert result == "good message"


def test_extract_first_user_message_multi_block_content(home):
    """Handles content as list of blocks (realistic JSONL shape)."""
    from croam.picker import extract_first_user_message

    sid = str(uuid.uuid4())
    encoded = "-Projects-test3"
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = proj_dir / f"{sid}.jsonl"

    # Realistic JSONL with tool_use lines before the first user text message.
    with jsonl_path.open("w", encoding="utf-8") as f:
        # A tool_result line (not "user" type): should be skipped.
        f.write(
            json.dumps(
                {
                    "type": "tool_result",
                    "message": {"role": "user", "content": "tool output"},
                }
            )
            + "\n"
        )
        # User message with multi-block content.
        f.write(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "help me debug"},
                            {"type": "text", "text": " the auth flow"},
                        ],
                    },
                    "uuid": str(uuid.uuid4()),
                }
            )
            + "\n"
        )

    result = extract_first_user_message(jsonl_path)
    assert result == "help me debug the auth flow"


def test_extract_first_user_message_custom_max_chars(home):
    """max_chars parameter is respected."""
    from croam.picker import extract_first_user_message

    sid = str(uuid.uuid4())
    encoded = "-Projects-maxchars"
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = proj_dir / f"{sid}.jsonl"

    with jsonl_path.open("w", encoding="utf-8") as f:
        line = {
            "type": "user",
            "message": {"role": "user", "content": "hello world"},
            "uuid": str(uuid.uuid4()),
        }
        f.write(json.dumps(line) + "\n")

    # With max_chars=5, "hello" should be truncated.
    result = extract_first_user_message(jsonl_path, max_chars=5)
    assert result is not None
    assert result == "hello..."
    assert len(result) == 8  # 5 + 3


# ---------------------------------------------------------------------------
# render_rows integration tests
# ---------------------------------------------------------------------------


def test_render_rows_cwd_display_is_fish_truncated(home):
    """cwd_display in picker rows uses fish-style truncation."""
    from datetime import UTC, datetime

    from croam.hosts import HostStatus
    from croam.ownership import Assertion
    from croam.picker import render_rows
    from croam.sessions import ClaudeSession

    NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
    sid = str(uuid.uuid4())
    cwd = home / "Programs" / "onlayer" / "internal" / "iam"
    cwd.mkdir(parents=True, exist_ok=True)

    jsonl_path = build_jsonl(home, sid, cwd, n_user=0)

    sessions = [
        ClaudeSession(
            sid=sid,
            cwd=cwd,
            transcript_path=jsonl_path,
            pid=None,
            status=None,
            started_at_ms=None,
            updated_at_ms=None,
            name="my session",
            version=None,
        )
    ]
    assertions = {
        sid: Assertion(
            sid=sid,
            owner="self",
            asserted_at=NOW,
            action="create",
            cwd_normalized=str(cwd),
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
    # cwd is home/Programs/onlayer/internal/iam -> ~/P/o/i/iam
    assert rows[0].cwd_display == "~/P/o/i/iam"


def test_render_rows_unnamed_session_uses_first_user_message(home):
    """Unnamed session (name=None) gets first user message as name."""
    from datetime import UTC, datetime

    from croam.hosts import HostStatus
    from croam.ownership import Assertion
    from croam.picker import render_rows
    from croam.sessions import ClaudeSession

    NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
    sid = str(uuid.uuid4())
    cwd = home / "Programs" / "debug"
    cwd.mkdir(parents=True, exist_ok=True)

    # Build JSONL with a custom user message.
    encoded = "-Programs-debug"
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = proj_dir / f"{sid}.jsonl"

    with jsonl_path.open("w", encoding="utf-8") as f:
        line = {
            "type": "user",
            "message": {"role": "user", "content": "help me debug the auth flow"},
            "uuid": str(uuid.uuid4()),
        }
        f.write(json.dumps(line) + "\n")

    sessions = [
        ClaudeSession(
            sid=sid,
            cwd=cwd,
            transcript_path=jsonl_path,
            pid=None,
            status=None,
            started_at_ms=None,
            updated_at_ms=None,
            name=None,  # unnamed
            version=None,
        )
    ]
    assertions = {
        sid: Assertion(
            sid=sid,
            owner="self",
            asserted_at=NOW,
            action="create",
            cwd_normalized=str(cwd),
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
    assert rows[0].name == "help me debug the auth flow"


def test_render_rows_named_session_keeps_session_name(home):
    """Named session still uses session.name even if transcript has user messages."""
    from datetime import UTC, datetime

    from croam.hosts import HostStatus
    from croam.ownership import Assertion
    from croam.picker import render_rows
    from croam.sessions import ClaudeSession

    NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
    sid = str(uuid.uuid4())
    cwd = home / "Programs" / "named"
    cwd.mkdir(parents=True, exist_ok=True)

    jsonl_path = build_jsonl(home, sid, cwd, n_user=1)

    sessions = [
        ClaudeSession(
            sid=sid,
            cwd=cwd,
            transcript_path=jsonl_path,
            pid=None,
            status=None,
            started_at_ms=None,
            updated_at_ms=None,
            name="my explicit session name",
            version=None,
        )
    ]
    assertions = {
        sid: Assertion(
            sid=sid,
            owner="self",
            asserted_at=NOW,
            action="create",
            cwd_normalized=str(cwd),
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
    assert rows[0].name == "my explicit session name"


def test_render_rows_unnamed_no_transcript_falls_back_to_sid(home):
    """Unnamed session with no readable transcript falls back to sid[:8]."""
    from datetime import UTC, datetime

    from croam.hosts import HostStatus
    from croam.ownership import Assertion
    from croam.picker import render_rows
    from croam.sessions import ClaudeSession

    NOW = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
    sid = str(uuid.uuid4())
    cwd = home / "Programs" / "missing"
    cwd.mkdir(parents=True, exist_ok=True)

    nonexistent_transcript = home / "does_not_exist.jsonl"

    sessions = [
        ClaudeSession(
            sid=sid,
            cwd=cwd,
            transcript_path=nonexistent_transcript,
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
            cwd_normalized=str(cwd),
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
    assert rows[0].name == sid[:8]
