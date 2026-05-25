#!/usr/bin/env bash
# PostToolUse hook: auto-format Python files after Edit/Write.
# Mirrors the formatting steps that pre-commit runs (skips lint + type-check):
#   - ruff import sort  (`ruff check --select I --fix`)
#   - ruff formatter    (`ruff format`)
# Reads the tool_input JSON from stdin; no-op on non-.py paths.
set -euo pipefail

fp=$(python3 -c "import sys, json; print(json.load(sys.stdin).get('tool_input', {}).get('file_path', ''))")
[[ "$fp" == *.py ]] || exit 0

uvx ruff check --select I --fix "$fp" >/dev/null 2>&1 || true
uvx ruff format "$fp" >/dev/null 2>&1 || true
