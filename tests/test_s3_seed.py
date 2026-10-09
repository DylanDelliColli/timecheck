"""Query the vintage Seamaster seed through the real build, SQLite, and CLI."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from timecheck.build import build


@pytest.fixture(scope="module")
def seamaster_seed(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    target = json.loads((root / "data/targets/omega-seamaster-1960s-70s.json").read_text())
    output = tmp_path_factory.mktemp("seamaster-seed")
    database = output / "seed.sqlite"
    code, report = build(data_dir=root / "data", out=database,
                         report=output / "report.json", strict=True, no_evidence=True)
    assert code == 0, (report["errors"], report["warnings"])
    return root, database, target, report


def test_seamaster_inventory_has_primary_movements_and_provenance(seamaster_seed):
    _, database, target, report = seamaster_seed
    targets = set(target["references"])
    assert target["line"] == "line:omega-seamaster"
    assert len(targets) >= 20
    with sqlite3.connect(database) as db:
        rows = db.execute(
            "SELECT reference_id, caliber_id, has_primary, grade "
            "FROM v_reference_calibers_all WHERE reference_id LIKE 'reference:omega-%'"
        ).fetchall()
        assert targets <= {row[0] for row in rows}
        fallback = {'reference:omega-st-166-0024', 'reference:omega-st-165-0010',
                    'reference:omega-st-166-0087'}
        assert targets - fallback <= {row[0] for row in rows if row[2] == 1}
        assert all(row[2] == 0 for row in rows if row[0] in fallback)
        members = {row[0] for row in db.execute(
            "SELECT reference_id FROM v_lineage_all WHERE line_id = 'line:omega-seamaster'")}
        assert targets <= members
        calibers = {row[1] for row in rows if row[0] in targets}
        assert {'caliber:omega-552', 'caliber:omega-565',
                'caliber:omega-1002', 'caliber:omega-1012'} <= calibers
        assert all(row[3] == 'unknown' for row in rows if row[0] in targets)
        assert db.execute('SELECT COUNT(*) FROM v_evidence_all').fetchone()[0] == report['evidence_count']


def test_seamaster_unknown_years_remain_unknown(seamaster_seed):
    root, database, target, _ = seamaster_seed
    for reference in target['references']:
        document = json.loads((root / 'data/references' / (reference.split(':')[1] + '.json')).read_text())
        for claim in document['claims']:
            if claim['predicate'] == 'uses_caliber':
                assert claim['valid_years'] == {
                    'from': None, 'to': None, 'from_evidence': None, 'to_evidence': None}
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM claim WHERE subject_id LIKE 'reference:omega-%' "
            "AND predicate = 'produced'").fetchone()[0] == 0


def test_seamaster_cli_preserves_pilot_and_exposes_proposed_variants(seamaster_seed):
    _, database, target, _ = seamaster_seed
    command = [sys.executable, '-m', 'timecheck', 'query', 'v_reference_calibers',
               '--db', str(database), '--where', "reference_id LIKE 'reference:omega-%'", '--json']
    default = json.loads(subprocess.run(command, text=True, capture_output=True, check=True).stdout)
    assert {row['caliber_id'] for row in default if row['reference_id'] ==
            'reference:omega-st-166-0002'} >= {'caliber:omega-562', 'caliber:omega-565'}
    inclusive = json.loads(subprocess.run(command + ['--include-proposed', '--primary-only'],
                                         text=True, capture_output=True, check=True).stdout)
    fallback = {'reference:omega-st-166-0024', 'reference:omega-st-165-0010',
                'reference:omega-st-166-0087'}
    assert set(target['references']) - fallback <= {row['reference_id'] for row in inclusive}
    assert not fallback & {row['reference_id'] for row in inclusive}
    assert all(row['status'] == 'verified' for row in default)


def test_seamaster_variants_and_documented_specs_remain_auditable(seamaster_seed):
    root, database, target, report = seamaster_seed
    with sqlite3.connect(database) as db:
        for reference, expected in {
            'reference:omega-st-165-0014': {'caliber:omega-550', 'caliber:omega-552'},
            'reference:omega-st-166-0023': {'caliber:omega-562', 'caliber:omega-565'},
            'reference:omega-st-166-0027': {'caliber:omega-562', 'caliber:omega-565'},
        }.items():
            assert {row[0] for row in db.execute(
                'SELECT caliber_id FROM v_reference_calibers_all WHERE reference_id = ?',
                (reference,))} == expected
        attributes = db.execute(
            "SELECT c.predicate, o.value FROM claim c "
            "JOIN claim_object o ON o.claim_id = c.id "
            "WHERE c.subject_id = 'caliber:omega-1002'").fetchall()
        assert ('hacking', 'true') in attributes
        assert ('beat_rate', '28800') in attributes
        assert db.execute(
            "SELECT COUNT(*) FROM evidence WHERE match_mode = 'manual' "
            "AND source_id = 'source:omega-552-technical-guide-20261009'"
        ).fetchone()[0] == 4
    coverage = report['coverage']['line:omega-seamaster']
    assert coverage['target'] == len(target['references']) == 20
    with sqlite3.connect(database) as db:
        verified = {row[0] for row in db.execute(
            "SELECT reference_id FROM v_lineage WHERE line_id = 'line:omega-seamaster' "
            "AND caliber_id IS NOT NULL")}
    assert coverage['covered'] == len(set(target['references']) & verified)
