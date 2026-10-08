"""Seed integration: build the real graph and query cross-brand movement hosts."""
import json
from pathlib import Path
import sqlite3

from timecheck.build import build

ROOT = Path(__file__).resolve().parents[1]


def test_s4_cross_brand_families(tmp_path):
    report = tmp_path / 'report.json'
    db_path = tmp_path / 'seed.sqlite'
    result, _ = build(data_dir=ROOT / 'data', out=db_path, report=report,
                      strict=True, no_evidence=True)
    assert result == 0, json.loads(report.read_text())['errors']
    with sqlite3.connect(db_path) as db:
        for slug in ('eta-2824-2', 'eta-2892-a2', 'eta-7750',
                     'sellita-sw200-1', 'sellita-sw300-1', 'sellita-sw500'):
            assert db.execute('SELECT 1 FROM caliber WHERE id=?',
                              ('caliber:' + slug,)).fetchone(), slug
        # The proposed authoring graph must already support cross-brand discovery.
        # Review promotion belongs to the chief; this test never edits claim status.
        for slug in ('eta-2824-2', 'eta-2892-a2', 'eta-7750'):
            hosts = db.execute('''
                SELECT DISTINCT owner.entity_id
                FROM v_reference_calibers_all r
                JOIN claim membership ON membership.subject_id=r.reference_id
                    AND membership.predicate='in_line'
                JOIN claim_object member ON member.claim_id=membership.id
                JOIN claim ownership ON ownership.subject_id=member.entity_id
                    AND ownership.predicate='owned_by'
                JOIN claim_object owner ON owner.claim_id=ownership.id
                WHERE r.caliber_id=? OR r.caliber_id IN (
                    SELECT related_id FROM v_caliber_family_all WHERE caliber_id=?
                )
            ''', ('caliber:' + slug, 'caliber:' + slug)).fetchall()
            assert len(hosts) >= 2, (slug, hosts)
        for left, right in (
            ('hamilton-h38455781', 'sinn-u50'),
            ('guinand-60-50', 'le-jour-mark-i-001'),
            ('hamilton-h70615133', 'farr-swit-seaplane-day-trip'),
        ):
            assert db.execute(
                'SELECT 1 FROM v_shared_dna_all WHERE reference_id=? AND other_reference_id=?',
                ('reference:' + left, 'reference:' + right),
            ).fetchone(), (left, right)
        assert db.execute(
            'SELECT grade FROM v_reference_calibers_all WHERE reference_id=?',
            ('reference:cw-c60-41c3h31t0kk0-b0',),
        ).fetchone()[0] == 'chronometer'
        # Generic SW200 and SW200-1 remain separate identities.
        assert db.execute('SELECT COUNT(*) FROM caliber WHERE id IN (?,?)',
                          ('caliber:sellita-sw200', 'caliber:sellita-sw200-1')).fetchone()[0] == 2
