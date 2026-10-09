"""Coverage accounting across lines, built from verified fixture evidence."""
import json
from pathlib import Path
import shutil
import sqlite3

from timecheck.build import _coverage, build

ROOT = Path(__file__).resolve().parents[1]


def test_family_coverage_deduplicates_verified_hosts(tmp_path):
    targets = tmp_path / 'targets'
    targets.mkdir()
    (targets / 'hosts.json').write_text(json.dumps({
        'schema_version': 1, 'family': 'family:hosts', 'source': 'synthetic',
        'references': ['reference:alpha', 'reference:alpha', 'reference:beta',
                       'reference:missing'],
    }))
    claims = [
        {'subject': 'reference:alpha', 'predicate': 'uses_caliber', 'status': 'verified'},
        {'subject': 'reference:alpha', 'predicate': 'uses_caliber', 'status': 'verified'},
        {'subject': 'reference:beta', 'predicate': 'uses_caliber', 'status': 'proposed'},
        {'subject': 'reference:outside', 'predicate': 'uses_caliber', 'status': 'verified'},
    ]
    errors = []
    assert _coverage(tmp_path, claims, errors) == {
        'family:hosts': {'target': 3, 'covered': 1,
                         'missing': ['reference:beta', 'reference:missing']},
    }
    assert errors == []


def test_family_target_counts_usage_without_verified_line_membership(tmp_path):
    data = tmp_path / 'data'
    shutil.copytree(ROOT / 'tests/fixtures/data', data)
    alpha = data / 'references/alpha.json'
    doc = json.loads(alpha.read_text())
    doc['claims'][0]['status'] = 'proposed'
    alpha.write_text(json.dumps(doc))
    beta = data / 'references/beta.json'
    doc = json.loads(beta.read_text())
    doc['claims'][1]['status'] = 'proposed'
    beta.write_text(json.dumps(doc))
    (data / 'targets/hosts.json').write_text(json.dumps({
        'schema_version': 1, 'family': 'family:hosts', 'source': 'synthetic fixture',
        'references': ['reference:alpha', 'reference:beta', 'reference:gamma',
                       'reference:missing'],
    }))
    database = tmp_path / 'graph.sqlite'
    code, report = build(data_dir=data, snapshot_dir=ROOT / 'tests/snapshots',
                         strict=True, out=database, report=tmp_path / 'report.json')
    assert code == 0, (report['errors'], report['warnings'])
    assert report['coverage']['family:hosts'] == {
        'target': 4, 'covered': 1,
        'missing': ['reference:beta', 'reference:gamma', 'reference:missing'],
    }
    # A line still requires verified membership, as well as verified usage.
    assert report['coverage']['line:example']['covered'] == 0
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT DISTINCT reference_id FROM v_reference_calibers').fetchall() == [
            ('reference:alpha',),
        ]
