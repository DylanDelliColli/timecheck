#!/usr/bin/env bash
set -euo pipefail
.venv/bin/python -m pytest -q
.venv/bin/timecheck build --strict --data-dir tests/fixtures/data --snapshot-dir tests/snapshots --out build/check-fixtures.sqlite --report build/check-fixtures-report.json
.venv/bin/timecheck build --strict --no-evidence --data-dir data --out build/check-data.sqlite
