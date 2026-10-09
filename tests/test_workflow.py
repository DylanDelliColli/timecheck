"""Validate the scheduled full verifier and run its command on real fixture data."""
import json
from pathlib import Path
import shlex
import sqlite3
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_nightly_schedule_verifies_full_graph(tmp_path):
    # BaseLoader preserves GitHub's `on` key and scalars as strings.
    workflow = yaml.load((ROOT / '.github/workflows/check.yml').read_text(), Loader=yaml.BaseLoader)
    schedules = workflow['on']['schedule']
    assert schedules and all(item['cron'].split()[2:] == ['*', '*', '*'] for item in schedules)
    job = workflow['jobs']['scheduled-evidence']
    assert job['if'] == "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
    checkout, = [step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@')]
    assert checkout['with']['ref'] == 'release/v1'
    command, = [step['run'] for step in job['steps'] if step.get('name') == 'Full live archive verification']
    # Execute the workflow's real full-build invocation using local evidence
    # instead of contacting archives or writing to shared runtime paths.
    result = subprocess.run(shlex.split(command) + [
        '--data-dir', str(ROOT / 'tests/fixtures/data'),
        '--snapshot-dir', str(ROOT / 'tests/snapshots'),
        '--out', str(tmp_path / 'graph.sqlite'), '--report', str(tmp_path / 'report.json')],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / 'report.json').read_text())
    assert set(report['evidence_verification'].values()) == {'verified'}
    with sqlite3.connect(tmp_path / 'graph.sqlite') as db:
        assert len(report['evidence_verification']) == db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]
