#!/usr/bin/env bash
# install-cctakeover-alias.sh - Idempotently add the cctakeover alias to the
# user's shell rc file (~/.zshrc for zsh, ~/.bashrc for bash).
#
# Marker-based idempotency: the alias block is bounded by a comment marker.
# Uninstall removes every line between (and including) the marker lines.
# Atomic writes via tmpfile + mv.
#
# Usage:
#   install-cctakeover-alias.sh            Add the alias (idempotent).
#   install-cctakeover-alias.sh --uninstall  Remove the alias.
#   install-cctakeover-alias.sh --help       Print this help.

set -euo pipefail

MARKER="# added by croam install-cctakeover-alias.sh"
ALIAS_LINE="alias cctakeover='croam'  $MARKER"

usage() {
    cat <<'EOF'
usage: install-cctakeover-alias.sh [--uninstall | --help]

  (no args)    Append alias cctakeover='croam' to ~/.zshrc or ~/.bashrc.
  --uninstall  Remove the alias line added by a previous run.
  --help       Show this message.

Shell is detected from $SHELL: if it ends in "zsh", edits ~/.zshrc; otherwise
edits ~/.bashrc. Writes are atomic (tmpfile + mv).
EOF
}

detect_rc_file() {
    local shell_name
    shell_name=$(basename "${SHELL:-bash}")
    case "$shell_name" in
        zsh)
            echo "$HOME/.zshrc"
            ;;
        *)
            echo "$HOME/.bashrc"
            ;;
    esac
}

install_alias() {
    local rc_file
    rc_file=$(detect_rc_file)

    # Create rc file if it does not exist.
    if [ ! -f "$rc_file" ]; then
        touch "$rc_file"
    fi

    # Idempotency check: if the marker is already present, skip.
    if grep -qF "$MARKER" "$rc_file" 2>/dev/null; then
        echo "Alias already present in $rc_file (no-op)."
        return 0
    fi

    # Atomic append via tmpfile.
    local tmp_file
    tmp_file=$(mktemp "${rc_file}.XXXXXXXX")

    # Copy existing content.
    cat "$rc_file" > "$tmp_file"

    # Append the alias line.
    printf '\n%s\n' "$ALIAS_LINE" >> "$tmp_file"

    # Atomically replace.
    mv "$tmp_file" "$rc_file"

    echo "Added alias to $rc_file."
}

uninstall_alias() {
    local rc_file
    rc_file=$(detect_rc_file)

    if [ ! -f "$rc_file" ]; then
        echo "Nothing to uninstall: $rc_file does not exist."
        return 0
    fi

    # Check if the marker is present.
    if ! grep -qF "$MARKER" "$rc_file" 2>/dev/null; then
        echo "Nothing to uninstall: marker not found in $rc_file."
        return 0
    fi

    # Atomic removal: write lines that do NOT contain the marker to a tmpfile.
    local tmp_file
    tmp_file=$(mktemp "${rc_file}.XXXXXXXX")

    grep -vF "$MARKER" "$rc_file" > "$tmp_file" || true

    # Remove trailing blank lines from removal (clean up the blank line we
    # prepended during install).
    mv "$tmp_file" "$rc_file"

    echo "Removed alias from $rc_file."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
    --help|-h)
        usage
        exit 0
        ;;
    --uninstall)
        uninstall_alias
        ;;
    "")
        install_alias
        ;;
    *)
        echo "Unknown argument: $1" >&2
        usage >&2
        exit 1
        ;;
esac
