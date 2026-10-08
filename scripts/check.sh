#!/usr/bin/env bash
set -euo pipefail
.venv/bin/python -m pytest -q
.venv/bin/timecheck build --strict --snapshot-dir tests/snapshots
