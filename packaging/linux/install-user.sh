#!/usr/bin/env bash
set -euo pipefail

prefix="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "$prefix/applications" "$prefix/icons/hicolor/scalable/apps"
install -m 0644 packaging/linux/io.pactlyn.desktop.desktop "$prefix/applications/io.pactlyn.desktop.desktop"
install -m 0644 src/pactlyn/ui/pactlyn.svg "$prefix/icons/hicolor/scalable/apps/io.pactlyn.desktop.svg"
update-desktop-database "$prefix/applications" 2>/dev/null || true
echo "Installed Pactlyn launcher for the current user."
