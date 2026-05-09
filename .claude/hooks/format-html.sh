#!/usr/bin/env bash
# PostToolUse hook: auto-format Django HTML templates after Edit/Write.
# Mirrors the formatting step that pre-commit runs (skips lint + type-check):
#   - djlint reformat   (`djlint --reformat`)
# Reads the tool_input JSON from stdin; no-op on non-.html paths.
set -euo pipefail

fp=$(python3 -c "import sys, json; print(json.load(sys.stdin).get('tool_input', {}).get('file_path', ''))")
[[ "$fp" == *.html ]] || exit 0

uvx djlint --reformat "$fp" >/dev/null 2>&1 || true
