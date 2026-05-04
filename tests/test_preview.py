"""Tests for src/croam/preview.py: conversation tail extraction and preview rendering."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# extract_conversation_tail tests
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    """Write a list of dicts as JSONL lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_msg(role: str, text: str, idx: int = 0) -> dict:
    """Build a minimal JSONL entry of type user or assistant."""
    return {
        "type": role,
        "message": {"role": role, "content": text},
        "uuid": str(uuid.uuid4()),
        "timestamp": 1000 + idx,
    }


def test_extract_conversation_tail_happy_path_last_n(home):
    """JSONL with 15 user+assistant messages returns last 10."""
    from croam.preview import extract_conversation_tail

    jsonl = home / "test_tail.jsonl"
    entries = []
    for i in range(15):
        role = "user" if i % 2 == 0 else "assistant"
        entries.append(_make_msg(role, f"message {i}", i))
    _write_jsonl(jsonl, entries)

    result = extract_conversation_tail(jsonl, n=10)
    assert len(result) == 10
    # Should be the last 10 messages (indices 5..14).
    assert result[0] == ("user", "message 5") or result[0] == ("assistant", "message 5")
    assert result[-1][1] == "message 14"


def test_extract_conversation_tail_short_transcript(home):
    """JSONL with 3 messages returns all 3."""
    from croam.preview import extract_conversation_tail

    jsonl = home / "test_short.jsonl"
    entries = [
        _make_msg("user", "hello", 0),
        _make_msg("assistant", "hi there", 1),
        _make_msg("user", "thanks", 2),
    ]
    _write_jsonl(jsonl, entries)

    result = extract_conversation_tail(jsonl, n=10)
    assert len(result) == 3
    assert result[0] == ("user", "hello")
    assert result[1] == ("assistant", "hi there")
    assert result[2] == ("user", "thanks")


def test_extract_conversation_tail_truncation(home):
    """Messages over max_msg_chars are truncated with '...'."""
    from croam.preview import extract_conversation_tail

    jsonl = home / "test_trunc.jsonl"
    long_text = "x" * 300
    entries = [_make_msg("user", long_text, 0)]
    _write_jsonl(jsonl, entries)

    result = extract_conversation_tail(jsonl, n=10, max_msg_chars=200)
    assert len(result) == 1
    role, text = result[0]
    assert role == "user"
    assert len(text) == 203  # 200 + len("...")
    assert text.endswith("...")
    assert text[:200] == "x" * 200


def test_extract_conversation_tail_skips_non_user_assistant(home):
    """Only user/assistant messages included; tool_use, system, last-prompt skipped."""
    from croam.preview import extract_conversation_tail

    jsonl = home / "test_mixed.jsonl"
    entries = [
        {"type": "last-prompt", "leafUuid": str(uuid.uuid4())},
        {"type": "permission-mode", "permissionMode": "default"},
        _make_msg("user", "first user msg", 0),
        {"type": "tool_use", "message": {"content": "tool stuff"}, "uuid": str(uuid.uuid4())},
        _make_msg("assistant", "assistant reply", 1),
        {"type": "system", "message": {"content": "system msg"}, "uuid": str(uuid.uuid4())},
        _make_msg("user", "second user msg", 2),
    ]
    _write_jsonl(jsonl, entries)

    result = extract_conversation_tail(jsonl, n=10)
    assert len(result) == 3
    assert result[0] == ("user", "first user msg")
    assert result[1] == ("assistant", "assistant reply")
    assert result[2] == ("user", "second user msg")


def test_extract_conversation_tail_empty_file(home):
    """Empty file returns empty list."""
    from croam.preview import extract_conversation_tail

    jsonl = home / "test_empty.jsonl"
    jsonl.write_text("")

    result = extract_conversation_tail(jsonl)
    assert result == []


def test_extract_conversation_tail_file_not_found(home):
    """Nonexistent file returns empty list (no crash)."""
    from croam.preview import extract_conversation_tail

    result = extract_conversation_tail(home / "nonexistent.jsonl")
    assert result == []


# ---------------------------------------------------------------------------
# render_preview tests
# ---------------------------------------------------------------------------


def _setup_session(
    home: Path,
    sid: str,
    *,
    cwd: Path | None = None,
    owner: str = "stormtree",
    pid: int | None = 42,
    status: str = "idle",
    messages: list[tuple[str, str]] | None = None,
) -> None:
    """Create the on-disk structures render_preview needs: transcript, metadata, ownership."""
    if cwd is None:
        cwd = home / "Programs" / "croam"
    cwd.mkdir(parents=True, exist_ok=True)

    # Transcript JSONL under ~/.claude/projects/<encoded>/<sid>.jsonl.
    from tests._helpers.synth_jsonl import _encode_cwd

    encoded = _encode_cwd(cwd)
    proj_dir = home / ".claude" / "projects" / encoded
    proj_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = proj_dir / f"{sid}.jsonl"

    entries: list[dict] = []
    if messages:
        for i, (role, text) in enumerate(messages):
            entries.append(_make_msg(role, text, i))
    _write_jsonl(jsonl_path, entries)

    # Session metadata under ~/.claude/sessions/<pid>.json.
    if pid is not None:
        from tests._helpers.synth_session import build_session_metadata

        build_session_metadata(home, pid, sid, cwd, status=status)

    # Ownership assertion under ~/.local/share/croam/<owner>/ownership.json.
    state_root = home / ".local" / "share" / "croam"
    owner_dir = state_root / owner
    owner_dir.mkdir(parents=True, exist_ok=True)
    ownership_file = owner_dir / "ownership.json"
    # Read existing or start fresh.
    existing: dict = {}
    if ownership_file.exists():
        existing = json.loads(ownership_file.read_text())
    existing[sid] = {
        "owner": owner,
        "asserted_at": "2026-05-04T10:00:00+00:00",
        "action": "create",
        "cwd_normalized": str(cwd),
        "previous_owner": None,
    }
    ownership_file.write_text(json.dumps(existing))


def test_render_preview_full(home):
    """Full preview with known session data contains metadata and messages."""
    from croam.preview import render_preview

    sid = "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee"
    cwd = home / "Programs" / "croam"
    msgs = [
        ("user", "help me debug the auth flow"),
        ("assistant", "I'll look at the authentication middleware..."),
        ("user", "the token refresh is failing"),
        ("assistant", "Let me check the refresh endpoint..."),
        ("user", "that fixed it, thanks"),
    ]
    _setup_session(home, sid, cwd=cwd, owner="stormtree", pid=42, status="idle", messages=msgs)

    output = render_preview(sid, home)
    # Metadata block.
    assert "Owner:" in output
    assert "stormtree" in output
    assert "Status:" in output
    assert "CWD:" in output
    assert "Actions:" in output
    # Fish-truncated cwd: home/Programs/croam -> ~/P/croam.
    assert "~/P/croam" in output
    # Conversation tail.
    assert "[user] help me debug the auth flow" in output
    assert "[assistant]" in output
    assert "that fixed it, thanks" in output


def test_render_preview_session_not_found(home):
    """Nonexistent sid produces graceful fallback, not a crash."""
    from croam.preview import render_preview

    output = render_preview("nonexistent-sid-0000-1111-222222222222", home)
    assert "nonexistent-sid" in output
    assert "not found" in output.lower() or "preview unavailable" in output.lower()


def test_render_preview_no_transcript_messages(home):
    """Session with empty transcript shows metadata but indicates no transcript."""
    from croam.preview import render_preview

    sid = "bbbb2222-cccc-dddd-eeee-ffffffffffff"
    _setup_session(home, sid, owner="vicar", pid=99, status="busy", messages=[])

    output = render_preview(sid, home)
    assert "Owner:" in output
    assert "vicar" in output
    assert "(no transcript)" in output.lower() or "(no messages)" in output.lower()


def test_render_preview_archived_session(home):
    """Session with no pid (archived) shows archived status."""
    from croam.preview import render_preview

    sid = "cccc3333-dddd-eeee-ffff-000000000000"
    msgs = [("user", "hello"), ("assistant", "hi")]
    _setup_session(home, sid, owner="stormtree", pid=None, status="idle", messages=msgs)

    output = render_preview(sid, home)
    assert "archived" in output.lower()
