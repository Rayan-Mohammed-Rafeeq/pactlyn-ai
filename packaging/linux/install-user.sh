#!/usr/bin/env bash
# install-user.sh — Install Pactlyn for the current user (no root required).
#
# What this script does:
#   1. Checks prerequisites (Python 3.11+, uv)
#   2. Installs the pactlyn command into ~/.local/bin via `uv tool install`
#   3. Runs the first-time database migration
#   4. Installs a desktop launcher + icon so Pactlyn appears in your app menu
#
# Usage (run from the pactlyn-ai repository root):
#   ./packaging/linux/install-user.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

# ── helpers ────────────────────────────────────────────────────────────────────
info()    { echo "  ✔  $*"; }
warn()    { echo "  ⚠  $*"; }
error()   { echo "  ✖  $*" >&2; exit 1; }
section() { echo; echo "── $* ──────────────────────────────────────────"; }

# ── 1. Check Python ────────────────────────────────────────────────────────────
section "Checking prerequisites"

PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(sys.version_info[:2])')
        if "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    error "Python 3.11 or newer is required but was not found.
       Install it with:  sudo apt install python3.11  (Ubuntu/Debian)
                    or:  https://www.python.org/downloads/"
fi
info "Python OK  ($($PYTHON --version))"

# ── 2. Check / install uv ──────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    warn "uv not found — installing now (requires internet)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1091
    source "$HOME/.local/bin/env" 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv &>/dev/null; then
    error "uv installation failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
fi
info "uv OK  ($(uv --version))"

# ── 3. Install pactlyn command ─────────────────────────────────────────────────
section "Installing Pactlyn"

uv tool install "$REPO_DIR" --force
info "pactlyn command installed → $(command -v pactlyn 2>/dev/null || echo '~/.local/bin/pactlyn')"

# Make sure ~/.local/bin is on PATH for this session
export PATH="$HOME/.local/bin:$PATH"

# ── 4. Initialise / migrate database ──────────────────────────────────────────
section "Setting up database"

# Run alembic through the tool-installed environment so it uses the correct
# Python and finds the project's migration files.
PACTLYN_TOOL_DIR="$(uv tool dir)/pactlyn"
if [[ -f "$PACTLYN_TOOL_DIR/bin/python" ]]; then
    "$PACTLYN_TOOL_DIR/bin/python" -m alembic -c "$REPO_DIR/alembic.ini" upgrade head \
        && info "Database ready" \
        || warn "Database migration step failed — the app will try again on first launch."
else
    # Fallback: use uv run from the repo
    uv run --project "$REPO_DIR" alembic upgrade head \
        && info "Database ready" \
        || warn "Database migration step failed — the app will try again on first launch."
fi

# ── 5. Install desktop launcher + icon ────────────────────────────────────────
section "Installing desktop launcher"

prefix="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "$prefix/applications" "$prefix/icons/hicolor/scalable/apps"

install -m 0644 \
    "$REPO_DIR/packaging/linux/io.pactlyn.desktop.desktop" \
    "$prefix/applications/io.pactlyn.desktop.desktop"

install -m 0644 \
    "$REPO_DIR/src/pactlyn/ui/pactlyn.svg" \
    "$prefix/icons/hicolor/scalable/apps/io.pactlyn.desktop.svg"

update-desktop-database "$prefix/applications" 2>/dev/null || true
gtk-update-icon-cache -f -t "$prefix/icons/hicolor" 2>/dev/null || true

info "Desktop launcher installed"

# ── Done ───────────────────────────────────────────────────────────────────────
echo
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Pactlyn is installed!                                       ║"
echo "║                                                              ║"
echo "║  Launch from your app menu  →  search 'Pactlyn'             ║"
echo "║  Or from terminal           →  pactlyn                      ║"
echo "║                                                              ║"
echo "║  Before first use, make sure Ollama is running:             ║"
echo "║    ollama serve                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo
