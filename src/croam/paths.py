"""Path normalization and claude's encoded-cwd convention.

Linux-only. Windows paths are out of scope.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from croam.errors import ConfigError

_MAX_CANDIDATES = 64


def encode_cwd(cwd: Path | str) -> str:
    """Encode an absolute path to claude's encoded-cwd format.

    Each `/` separator and each leading `.` in a path component becomes `-`.
    Existing `-` characters in segments are preserved verbatim.
    Caller must expand `~` before passing; literal `~` is treated as a
    regular character and will produce odd output.
    Raises ValueError for relative paths (programmer error).
    """
    p = Path(cwd) if isinstance(cwd, str) else cwd
    if not p.is_absolute():
        raise ValueError(f"encode_cwd requires an absolute path; got {p!r}")
    # Path.parts collapses // and strips trailing /
    parts = p.parts  # ('/', 'home', 'tunc', '.claude') for /home/tunc/.claude
    encoded_parts: list[str] = []
    for part in parts:
        if part == "/":
            # Root slash becomes an empty string so the join yields a leading '-'
            encoded_parts.append("")
            continue
        if part.startswith("."):
            # Leading dot becomes '-'; rest of segment preserved
            encoded_parts.append("-" + part[1:])
        else:
            encoded_parts.append(part)
    return "-".join(encoded_parts)


def _decode_suffix_candidates(tokens: list[str]) -> Iterator[list[str]]:
    """Yield all plausible path-component lists from split-on-'-' tokens.

    Each token is a chunk from splitting the encoded suffix on '-'.
    Non-empty tokens may be:
    - A complete path component (dash before it was a separator)
    - The tail of a longer component merged with the previous (dash was literal)

    Empty tokens indicate a '--' sequence:
    - An empty token followed by a non-empty token means the non-empty is a
      dot-prefixed component body (e.g. '' + 'claude' -> '.claude').
    """
    yield from _recurse(tokens, 0, [])


def _recurse(tokens: list[str], idx: int, cur: list[str]) -> Iterator[list[str]]:
    """Build path component lists from tokens[idx:] appended to cur."""
    if idx == len(tokens):
        if cur:
            yield cur
        return

    tok = tokens[idx]

    if tok == "":
        # Empty token = a '-' that was a separator (or part of '--').
        nxt = idx + 1
        if nxt < len(tokens) and tokens[nxt] == "":
            # Double empty = '--'. This means a dot-prefixed component follows.
            body_idx = nxt + 1
            if body_idx < len(tokens) and tokens[body_idx] != "":
                body = tokens[body_idx]
                # Primary: dot-prefixed component
                yield from _recurse(tokens, body_idx + 1, [*cur, "." + body])
                # Secondary: treat '--' as two separators (degenerate, skip empty segment)
                yield from _recurse(tokens, nxt + 1, cur)  # pragma: no cover
            else:
                yield from _recurse(tokens, nxt + 1, cur)  # pragma: no cover
        elif nxt < len(tokens) and tokens[nxt] != "":
            # Single empty before a non-empty token. Two interpretations:
            # (a) Plain separator: the next token starts a new component normally.
            yield from _recurse(tokens, nxt, cur)
            # (b) Dot-prefix marker: the next token is a dot-prefixed component.
            #     This covers the body-split case where '--' produces one '' in
            #     the split (e.g. 'tunc--claude' -> ['tunc', '', 'claude']).
            body = tokens[nxt]
            yield from _recurse(tokens, nxt + 1, [*cur, "." + body])
        else:
            # Trailing separator; yield what we have
            if cur:  # pragma: no cover
                yield cur  # pragma: no cover
    else:
        # Non-empty token. Option A: new component; Option B: merge with previous.
        # Option A: this token starts a new path component
        yield from _recurse(tokens, idx + 1, [*cur, tok])
        # Option B: merge with the last component via literal '-' (only if cur exists)
        if cur:
            yield from _recurse(tokens, idx + 1, [*cur[:-1], cur[-1] + "-" + tok])


def _generate_candidates(encoded: str, host_home: Path | None = None) -> Iterator[Path]:
    """Yield candidate absolute paths for the given encoded string.

    When host_home is provided, the known-prefix strategy is used first:
    if encoded starts with encode_cwd(host_home), strip that prefix and only
    enumerate candidates for the suffix, prepending host_home. This handles
    pytest tmp paths that have many literal dashes.

    Falls back to full enumeration if the prefix does not match.
    Deduplicates via a seen set and caps output at _MAX_CANDIDATES.
    """
    seen: set[tuple[str, ...]] = set()
    count = 0

    def _emit(candidate: Path) -> bool:
        """Emit candidate if not seen, return True if cap reached."""
        nonlocal count
        key = tuple(candidate.parts)
        if key in seen:
            return False  # pragma: no cover -- dedup hit requires specific input shapes
        seen.add(key)
        count += 1
        return count > _MAX_CANDIDATES

    # --- Strategy 1: known-prefix shortcut (when host_home provided) ---
    if host_home is not None:
        home_encoded = encode_cwd(host_home)
        if encoded.startswith(home_encoded):
            # The suffix after the home prefix
            suffix = encoded[len(home_encoded) :]
            if suffix == "":
                # Encoded is exactly host_home
                p = host_home
                if not _emit(p):
                    yield p
            elif suffix.startswith("-"):
                # suffix starts with '-'. Split the full suffix on '-';
                # the first token will be '' (the leading separator), so _recurse
                # will correctly handle it as a separator (single) or dot-prefix (double).
                suffix_tokens = suffix.split("-")
                for parts in _decode_suffix_candidates(suffix_tokens):
                    candidate = Path(str(host_home) + "/" + "/".join(parts))
                    if _emit(candidate):  # pragma: no cover
                        return  # pragma: no cover
                    yield candidate

    # --- Strategy 2: full enumeration without home hint ---
    body = encoded[1:]  # strip leading '-' representing root '/'
    tokens = body.split("-")
    for parts in _decode_suffix_candidates(tokens):
        if not parts:  # pragma: no cover
            continue  # pragma: no cover
        candidate = Path("/" + "/".join(parts))
        if _emit(candidate):  # pragma: no cover
            return  # pragma: no cover
        yield candidate


def _no_probe_best_guess(encoded: str) -> Path:
    """Deterministic best-guess decode without filesystem probing.

    After stripping the leading '-' (root), splits the body on '-'.
    A single empty token in the body-split comes from '--' in the encoded string,
    which means the next token is a dot-prefixed path component.
    Every other '-' is treated as a path separator.
    This is lossy for paths with literal dashes but correct for dot-segment paths.
    """
    body = encoded[1:]  # strip leading '-' (root '/')
    tokens = body.split("-")
    parts: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "":
            # Empty token: came from '--' in encoded string. The next non-empty
            # token is a dot-prefixed component.
            if i + 1 < len(tokens) and tokens[i + 1] != "":
                parts.append("." + tokens[i + 1])
                i += 2
            else:
                # Consecutive empties or trailing empty: skip  # pragma: no cover
                i += 1  # pragma: no cover
        else:
            parts.append(tok)
            i += 1
    return Path("/" + "/".join(parts))


def decode_cwd(encoded: str, host_home: Path | None = None, fs_probe: bool = True) -> Path:
    """Best-effort decode of a claude encoded-cwd string to an absolute Path.

    Decoding is lossy when the original path contains '-'. With fs_probe=True,
    candidates are probed against the filesystem and the first existing path wins.
    With fs_probe=False, returns a deterministic heuristic (every '--' -> '/.',
    every '-' -> '/'), which may be wrong for paths containing literal dashes.
    Raises ConfigError if the input does not start with '-' or if fs_probe=True
    and no candidate exists on the filesystem.
    """
    if not encoded or not encoded.startswith("-"):
        raise ConfigError(
            f"Invalid encoded_cwd: expected leading '-' in {encoded!r}",
            field="encoded_cwd",
            reason=f"expected leading '-' in {encoded!r}",
        )

    if not fs_probe:
        return _no_probe_best_guess(encoded)

    # fs_probe=True: iterate candidates and return first that exists
    for count, candidate in enumerate(_generate_candidates(encoded, host_home), 1):
        if count > _MAX_CANDIDATES:  # pragma: no cover
            break  # pragma: no cover
        if candidate.exists():
            return candidate

    raise ConfigError(
        f"No plausible decode of {encoded!r} exists on filesystem",
        field="encoded_cwd",
        reason=f"no plausible decode of {encoded!r} exists on filesystem",
    )


def normalize_cwd(cwd: Path, host_home: Path) -> str:
    """Return ~/relative if cwd is under host_home, else absolute string.

    Does NOT resolve symlinks; uses literal path components.
    Raises ValueError if cwd is not absolute (defensive).
    """
    if not cwd.is_absolute():
        raise ValueError(f"normalize_cwd requires an absolute path; got {cwd!r}")
    try:
        rel = cwd.relative_to(host_home)
    except ValueError:
        return str(cwd)
    if rel == Path("."):
        return "~"
    return f"~/{rel}"


def denormalize_cwd(normalized: str, host_home: Path) -> Path:
    """Inverse of normalize_cwd. '~' or '~/...' becomes host_home / rest.

    Absolute paths returned as-is.
    Raises ValueError for ~user/... (different-user homes are out of scope).
    """
    if normalized == "~":
        return Path(host_home)
    if normalized.startswith("~/"):
        return Path(host_home) / normalized[2:]
    if normalized.startswith("~"):
        raise ValueError(f"denormalize_cwd does not support ~user/... paths; got {normalized!r}")
    return Path(normalized)
