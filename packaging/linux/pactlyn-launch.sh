#!/usr/bin/env bash
# pactlyn-launch.sh — Fallback launcher for Pactlyn.
#
# This script is useful if you haven't run install-user.sh yet, or if you're
# launching Pactlyn directly from the repository without a system-wide install.
#
# Priority order:
#   1. Installed command  (~/.local/bin/pactlyn via `uv tool install`)
#   2. Repo virtual-env   (uv run pactlyn from the repo directory)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# ── ensure ~/.local/bin is on PATH (desktop sessions often don't load .bashrc)
export PATH="$HOME/.local/bin:$PATH"

# ── helper: check Ollama is reachable ─────────────────────────────────────────
check_ollama() {
    if ! curl -sf http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
        echo ""
        echo "⚠  Ollama is not running."
        echo "   Start it with:  ollama serve"
        echo "   (Pactlyn will still open but AI features will be unavailable)"
        echo ""
    fi
}

check_ollama

# ── 1. Use the installed command if available ──────────────────────────────────
if command -v pactlyn &>/dev/null; then
    exec pactlyn "$@"
fi

# ── 2. Fall back to uv run from the repo ──────────────────────────────────────
if command -v uv &>/dev/null && [[ -f "$REPO_DIR/pyproject.toml" ]]; then
    echo "ℹ  pactlyn not installed globally — launching from repository via uv..."
    echo "   Run  ./packaging/linux/install-user.sh  once to get a proper app launcher."
    echo ""
    cd "$REPO_DIR"
    exec uv run pactlyn "$@"
fi

# ── 3. Nothing worked ─────────────────────────────────────────────────────────
echo "✖  Could not launch Pactlyn." >&2
echo "   Please run the installer first:" >&2
echo "     cd $(realpath "$REPO_DIR")" >&2
echo "     ./packaging/linux/install-user.sh" >&2
exit 1
