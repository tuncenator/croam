"""Read-only render of claude JSONL transcripts as plain text.

Phase 7 implements minimal [user] / [assistant] output. Phase 11 may polish
(pagination, syntax-highlight, etc.). This module must never write to files --
read-only by contract.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

from loguru import logger


def _extract_text(message_field: object) -> str:
    """Extract plain text from a JSONL `message` field.

    Handles three observed shapes:
    - plain string: returned as-is
    - dict with `content` as a string: return the string
    - dict with `content` as a list of content-block objects: join text blocks
    Falls back to json.dumps for unknown shapes.
    """
    if isinstance(message_field, str):
        return message_field
    if isinstance(message_field, dict):
        content = message_field.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
    return json.dumps(message_field)


def render_static_transcript(jsonl_path: Path, *, fp: TextIO = sys.stdout) -> int:
    """Render a claude JSONL transcript as plain `[user]` / `[assistant]` lines.

    Skips metadata records (last-prompt, permission-mode, attachment,
    file-history-snapshot, tool_use, tool_result, system, anything else).
    Returns 0 on success, 1 if the file does not exist or is unreadable.
    Phase 11 may polish (paginate, syntax-highlight, etc.). Phase 7 just makes it
    functional.
    """
    if not jsonl_path.exists():
        logger.warning("render_static_transcript: file not found: {}", jsonl_path)
        fp.write(f"croam: transcript not found: {jsonl_path}\n")
        return 1

    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.warning("render_static_transcript: unreadable {}: {}", jsonl_path, e)
        fp.write(f"croam: transcript not found: {jsonl_path}\n")
        return 1

    _EMIT_TYPES = {"user", "assistant"}

    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError as e:
            logger.debug("render_static_transcript: skipping malformed line: {}", e)
            continue
        if not isinstance(obj, dict):
            continue
        msg_type = obj.get("type")
        if msg_type not in _EMIT_TYPES:
            continue
        message = obj.get("message", "")
        text = _extract_text(message)
        fp.write(f"[{msg_type}] {text}\n")

    return 0
