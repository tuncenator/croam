"""Tests for src/croam/transcript.py: render_static_transcript."""

from __future__ import annotations

import io
import json
from pathlib import Path

from croam.transcript import (
    _extract_text,
    render_static_transcript,
)


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(rec) for rec in lines) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# _extract_text unit tests (home fixture required by the conftest safety guard)
# ---------------------------------------------------------------------------


def test_extract_text_plain_string(home: Path):
    assert _extract_text("hello world") == "hello world"


def test_extract_text_dict_string_content(home: Path):
    assert _extract_text({"role": "user", "content": "hi"}) == "hi"


def test_extract_text_dict_list_content(home: Path):
    blocks = [{"type": "text", "text": "block"}]
    assert _extract_text({"role": "user", "content": blocks}) == "block"


def test_extract_text_dict_list_multiple_blocks(home: Path):
    blocks = [{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}]
    assert _extract_text({"role": "user", "content": blocks}) == "foobar"


def test_extract_text_dict_list_skips_non_text_blocks(home: Path):
    blocks = [{"type": "image", "url": "http://..."}, {"type": "text", "text": "real"}]
    assert _extract_text({"role": "user", "content": blocks}) == "real"


def test_extract_text_unknown_falls_back_to_json_dumps(home: Path):
    val = 42
    result = _extract_text(val)
    assert result == json.dumps(val)


# ---------------------------------------------------------------------------
# render_static_transcript: file missing
# ---------------------------------------------------------------------------


def test_missing_file_returns_1(home: Path):
    fp = io.StringIO()
    path = home / "nonexistent.jsonl"
    rc = render_static_transcript(path, fp=fp)
    assert rc == 1
    assert "transcript not found" in fp.getvalue()
    assert str(path) in fp.getvalue()


# ---------------------------------------------------------------------------
# render_static_transcript: empty file
# ---------------------------------------------------------------------------


def test_empty_file_returns_0(home: Path, tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == ""


# ---------------------------------------------------------------------------
# render_static_transcript: metadata-only
# ---------------------------------------------------------------------------


def test_metadata_only_no_output(home: Path, tmp_path: Path):
    lines = [
        {"type": "last-prompt", "leafUuid": "abc", "sessionId": "s1"},
        {"type": "permission-mode", "permissionMode": "default"},
        {"type": "attachment", "content": "..."},
        {"type": "file-history-snapshot", "data": {}},
        {"type": "tool_use", "id": "t1"},
        {"type": "tool_result", "id": "t1"},
        {"type": "system", "message": "hello"},
    ]
    p = tmp_path / "meta.jsonl"
    _write_jsonl(p, lines)
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == ""


# ---------------------------------------------------------------------------
# render_static_transcript: user string message
# ---------------------------------------------------------------------------


def test_user_string_message(tmp_path: Path, home: Path):
    lines = [{"type": "user", "message": "hello"}]
    p = tmp_path / "t.jsonl"
    _write_jsonl(p, lines)
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == "[user] hello\n"


# ---------------------------------------------------------------------------
# render_static_transcript: user dict {role, content: "hi"}
# ---------------------------------------------------------------------------


def test_user_dict_content_string(tmp_path: Path, home: Path):
    lines = [{"type": "user", "message": {"role": "user", "content": "hi"}}]
    p = tmp_path / "t.jsonl"
    _write_jsonl(p, lines)
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == "[user] hi\n"


# ---------------------------------------------------------------------------
# render_static_transcript: user dict {role, content: [{type:"text", text:"block"}]}
# ---------------------------------------------------------------------------


def test_user_dict_content_list_block(tmp_path: Path, home: Path):
    blocks = [{"type": "text", "text": "block"}]
    lines = [{"type": "user", "message": {"role": "user", "content": blocks}}]
    p = tmp_path / "t.jsonl"
    _write_jsonl(p, lines)
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == "[user] block\n"


# ---------------------------------------------------------------------------
# render_static_transcript: assistant message
# ---------------------------------------------------------------------------


def test_assistant_message(tmp_path: Path, home: Path):
    lines = [{"type": "assistant", "message": "thinking..."}]
    p = tmp_path / "t.jsonl"
    _write_jsonl(p, lines)
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == "[assistant] thinking...\n"


# ---------------------------------------------------------------------------
# render_static_transcript: skips other types
# ---------------------------------------------------------------------------


def test_skips_other_types(tmp_path: Path, home: Path):
    lines = [
        {"type": "tool_use", "id": "t1", "name": "bash"},
        {"type": "user", "message": "real"},
        {"type": "tool_result", "id": "t1", "output": "done"},
    ]
    p = tmp_path / "t.jsonl"
    _write_jsonl(p, lines)
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == "[user] real\n"


# ---------------------------------------------------------------------------
# render_static_transcript: unicode emitted verbatim
# ---------------------------------------------------------------------------


def test_unicode_verbatim(tmp_path: Path, home: Path):
    msg = "hello éà中文"
    lines = [{"type": "user", "message": msg}]
    p = tmp_path / "t.jsonl"
    _write_jsonl(p, lines)
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == f"[user] {msg}\n"


# ---------------------------------------------------------------------------
# render_static_transcript: malformed line skipped, others render
# ---------------------------------------------------------------------------


def test_malformed_line_skipped(tmp_path: Path, home: Path):
    p = tmp_path / "t.jsonl"
    content = (
        '{"type":"user","message":"first"}\n'
        "NOT VALID JSON AT ALL\n"
        '{"type":"user","message":"second"}\n'
    )
    p.write_text(content, encoding="utf-8")
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert "[user] first\n" in fp.getvalue()
    assert "[user] second\n" in fp.getvalue()


# ---------------------------------------------------------------------------
# render_static_transcript: multiple records ordered correctly
# ---------------------------------------------------------------------------


def test_multiple_records_in_order(tmp_path: Path, home: Path):
    lines = [
        {"type": "user", "message": "q1"},
        {"type": "assistant", "message": "a1"},
        {"type": "user", "message": "q2"},
    ]
    p = tmp_path / "t.jsonl"
    _write_jsonl(p, lines)
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == "[user] q1\n[assistant] a1\n[user] q2\n"


# ---------------------------------------------------------------------------
# render_static_transcript: OSError on read (permissions)
# ---------------------------------------------------------------------------


def test_unreadable_file_returns_1(tmp_path: Path, home: Path):
    """File exists but cannot be read (permissions) -> returns 1, writes message."""
    import stat

    p = tmp_path / "noperm.jsonl"
    p.write_text('{"type":"user","message":"x"}\n', encoding="utf-8")
    p.chmod(0)
    try:
        fp = io.StringIO()
        rc = render_static_transcript(p, fp=fp)
        assert rc == 1
        assert "transcript not found" in fp.getvalue()
    finally:
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ---------------------------------------------------------------------------
# render_static_transcript: blank lines are skipped silently
# ---------------------------------------------------------------------------


def test_blank_lines_skipped(tmp_path: Path, home: Path):
    """Blank lines between records are skipped silently."""
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"type":"user","message":"hi"}\n\n\n{"type":"user","message":"bye"}\n',
        encoding="utf-8",
    )
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == "[user] hi\n[user] bye\n"


# ---------------------------------------------------------------------------
# render_static_transcript: non-dict JSON line is skipped
# ---------------------------------------------------------------------------


def test_non_dict_json_line_skipped(tmp_path: Path, home: Path):
    """A valid JSON line that is not a dict (e.g. an array) is silently skipped."""
    p = tmp_path / "t.jsonl"
    p.write_text(
        '["not","a","dict"]\n{"type":"user","message":"real"}\n',
        encoding="utf-8",
    )
    fp = io.StringIO()
    rc = render_static_transcript(p, fp=fp)
    assert rc == 0
    assert fp.getvalue() == "[user] real\n"
