#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv &>/dev/null; then
    echo "[!] 'uv' command not found. Please ensure uv is installed and in your PATH."
    exit 1
fi

exec uv run gki "$@"
