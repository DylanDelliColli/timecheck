"""Seed integration: build the real graph and query cross-brand movement hosts."""
import json
from pathlib import Path
import sqlite3

from timecheck.build import build

ROOT = Path(__file__).resolve().parents[1]


def test_s4_host_family_coverage(tmp_path):
    database = tmp_path / 'seed.sqlite'
    code, report = build(data_dir=ROOT / 'data', out=database,
                         report=tmp_path / 'report.json', strict=True, no_evidence=True)
    assert code == 0, (report['errors'], report['warnings'])
    coverage = report['coverage']['family:eta-sellita-hosts']
    target = json.loads((ROOT / 'data/targets/eta-sellita-hosts.json').read_text())
    with sqlite3.connect(database) as db:
        # Includes grades, generic SW200/SW300 and the sourced Mühle derivative.
        hosts = {row[0] for row in db.execute('''
            WITH roots(id) AS (VALUES
                ('caliber:eta-2824-2'), ('caliber:eta-2892-a2'), ('caliber:eta-7750'),
                ('caliber:sellita-sw200-1'), ('caliber:sellita-sw300-1'), ('caliber:sellita-sw500')
            ), family(id) AS (
                SELECT id FROM roots UNION
                SELECT related_id FROM v_caliber_family_all WHERE caliber_id IN roots
            )
            SELECT DISTINCT reference_id FROM v_reference_calibers_all
            WHERE caliber_id IN family
        ''')}
        verified = {row[0] for row in db.execute(
            'SELECT DISTINCT reference_id FROM v_reference_calibers')}
    assert len(hosts) == 25
    assert set(target['references']) == hosts
    assert coverage == {'target': len(hosts), 'covered': len(hosts & verified),
                        'missing': sorted(hosts - verified)}
    assert {'reference:hamilton-h70615133', 'reference:steinhart-ocean-one-black',
            'reference:muhle-m1-25-21-lb'} <= hosts


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
        # The pinned historical SW200-1 guide names all four executions.
        grades = db.execute('''
            SELECT DISTINCT label.value
            FROM claim parent
            JOIN claim_object target ON target.claim_id=parent.id
            JOIN claim name ON name.subject_id=parent.subject_id
                AND name.predicate='grade_name'
            JOIN claim_object label ON label.claim_id=name.id
            WHERE parent.predicate='grade_of' AND target.entity_id=?
        ''', ('caliber:sellita-sw200-1',)).fetchall()
        assert {row[0] for row in grades} == {'Standard', 'Special', 'Premium', 'chronometer'}
        # Grade labels preserve the maker's quoted vocabulary, including its spelling.
        expected_grades = {
            'sellita-sw200-1-standard': 'Standard',
            'sellita-sw200-1-elabore': 'Special',
            'sellita-sw200-1-top': 'Premium',
            'sellita-sw200-1-chronometer': 'chronometer',
            'sellita-sw300-elabore': 'Elaboré',
            'sellita-sw300-1-chronometer': 'chronometer',
            'eta-2892-a2-elabore': 'Elaborated',
            'eta-2892-a2-top': 'Top',
            'eta-2892-a2-chronometer': 'Chronometer',
            'eta-7750-elabore': 'Elaborated',
            'eta-7750-top': 'Top',
            'eta-7750-chronometer': 'Chronometer',
        }
        for slug, grade in expected_grades.items():
            assert db.execute(
                "SELECT value FROM claim JOIN claim_object ON claim_id=claim.id "
                "WHERE subject_id=? AND predicate='grade_name'",
                ('caliber:' + slug,),
            ).fetchall() == [(grade,)], slug
        # Both quoted maker names and common synonyms resolve to the retained identities.
        for slug, names in {
            'sellita-sw200-1-top': ('Sellita SW200-1 Premium', 'Sellita SW200-1 Top'),
            'sellita-sw200-1-elabore': ('Sellita SW200-1 Special', 'Sellita SW200-1 élaboré'),
            'eta-2892-a2-elabore': ('ETA 2892-A2 Elaborated', 'ETA 2892-A2 élaboré'),
            'eta-7750-elabore': ('ETA 7750 Elaborated', 'ETA 7750 élaboré'),
        }.items():
            for name in names:
                assert db.execute(
                    'SELECT caliber.id FROM caliber, json_each(caliber.aliases) AS alias '
                    'WHERE alias.value=?', (name,),
                ).fetchall() == [('caliber:' + slug,)], name
        # A named Riviera configuration replaces the uncited generic Classima host.
        assert db.execute(
            'SELECT caliber_id FROM v_reference_calibers_all WHERE reference_id=?',
            ('reference:baume-mercier-10620',),
        ).fetchall() == [('caliber:sellita-sw200',)]
        assert not db.execute('SELECT 1 FROM reference WHERE id=?',
                              ('reference:baume-mercier-classima-42mm',)).fetchone()
        # Generic SW200 and SW200-1 remain separate identities.
        assert db.execute('SELECT COUNT(*) FROM caliber WHERE id IN (?,?)',
                          ('caliber:sellita-sw200', 'caliber:sellita-sw200-1')).fetchone()[0] == 2
