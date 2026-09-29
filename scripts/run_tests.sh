#!/usr/bin/env bash
# Run every check used for release validation.
#   scripts/run_tests.sh            # full suite (browser tests skip themselves if Playwright/Chromium is missing)
#   NITTAQ_SKIP_BROWSER=1 scripts/run_tests.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== knowledge =="
python3 scripts/check_knowledge.py --check
echo "== project =="
python3 scripts/validate_project.py
if command -v ruff >/dev/null 2>&1; then
  echo "== ruff =="
  ruff check .
fi
if command -v mypy >/dev/null 2>&1; then
  echo "== mypy =="
  mypy
fi
echo "== tests =="
python3 -m unittest discover -s tests -t . -v
