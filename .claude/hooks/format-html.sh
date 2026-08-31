#!/usr/bin/env bash
# PostToolUse hook: auto-format Django HTML templates after Edit/Write.
# Mirrors the formatting step that pre-commit runs (skips lint + type-check):
#   - djlint reformat   (`djlint --reformat`)
# Reads the tool_input JSON from stdin; no-op on non-.html paths.
#
# The djlint version is pinned to match .pre-commit-config.yaml. Newer djlint
# collapses short tags onto one line where this version expands them, so an
# unpinned `uvx djlint` writes formatting that CI then rejects.
set -euo pipefail

fp=$(python3 -c "import sys, json; print(json.load(sys.stdin).get('tool_input', {}).get('file_path', ''))")
[[ "$fp" == *.html ]] || exit 0

uvx djlint@1.36.4 --reformat "$fp" >/dev/null 2>&1 || true
