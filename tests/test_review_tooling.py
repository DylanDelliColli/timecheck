"""Review transitions exercise real build reports, file edits and SQLite views."""
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / 'tests/snapshots'


def cli(*args):
    return subprocess.run([sys.executable, '-m', 'timecheck', *map(str, args)],
                          capture_output=True, text=True)


@pytest.fixture
def graph(tmp_path):
    data = tmp_path / 'data'
    shutil.copytree(ROOT / 'tests/fixtures/data', data)
    for path in data.glob('*/*.json'):
        doc = json.loads(path.read_text())
        for claim in doc.get('claims', []) if isinstance(doc, dict) else []:
            claim['status'] = 'proposed'
            claim.pop('review', None)
        path.write_text(json.dumps(doc))
    return data


def build(data, tmp_path, *flags):
    result = cli('build', '--data-dir', data, '--snapshot-dir', SNAPSHOTS,
                 '--out', tmp_path / 'graph.sqlite', '--report', tmp_path / 'report.json', *flags)
    return result, json.loads((tmp_path / 'report.json').read_text())


def verify(data, tmp_path, *flags):
    return cli('status', 'verify', '--by', 'independent-review / chief',
               '--at', '2026-10-08T23:30:00Z', '--data-dir', data,
               '--report', tmp_path / 'report.json', *flags)


def test_report_and_review_journey(graph, tmp_path):
    result, report = build(graph, tmp_path, '--strict')
    assert result.returncode == 0, result.stderr
    path = graph / 'references/alpha.json'
    ids = [c['id'] for c in json.loads(path.read_text())['claims']]
    assert report['proposed_claims_by_file'][str(path)] == ids
    assert report['line_claim_counts']['line:example'] == {'proposed': 23, 'verified': 0}
    excluded = ids[-1]
    result = verify(graph, tmp_path, '--files', path, '--except', excluded)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'count': 2, 'claim_ids': ids[:2]}
    claims = json.loads(path.read_text())['claims']
    assert [c['status'] for c in claims] == ['verified', 'verified', 'proposed']
    assert claims[0]['review'] == {'by': 'independent-review / chief', 'at': '2026-10-08T23:30:00Z'}
    assert 'review' not in claims[-1]
    result, report = build(graph, tmp_path, '--strict')
    assert result.returncode == 0, result.stderr
    assert report['line_claim_counts']['line:example'] == {'proposed': 21, 'verified': 2}
    with sqlite3.connect(tmp_path / 'graph.sqlite') as db:
        assert db.execute('SELECT reference_id FROM v_reference_calibers').fetchall() == [('reference:alpha',)]
    again = verify(graph, tmp_path, '--files', path, '--except', excluded)
    assert json.loads(again.stdout)['count'] == 0


@pytest.mark.parametrize('mode', ['unchecked', 'error', 'stale_claim', 'stale_source', 'manual', 'missing', 'wrong_root', 'invalid_at', 'blank_by'])
def test_review_refuses_untrusted_or_ineligible_inputs(graph, tmp_path, mode):
    path = graph / 'references/alpha.json'
    doc = json.loads(path.read_text())
    if mode == 'error':
        doc['claims'][0]['evidence'][0]['quote'] = 'A deliberately missing quote that cannot be verified.'
        path.write_text(json.dumps(doc))
    if mode == 'manual':
        source = graph / 'sources/example.json'
        s = json.loads(source.read_text()); s['content_type'] = 'image_scan'
        source.write_text(json.dumps(s))
        for p in graph.glob('*/*.json'):
            d = json.loads(p.read_text())
            for c in d.get('claims', []) if isinstance(d, dict) else []:
                for e in c['evidence']:
                    e['match_mode'] = 'manual'
            p.write_text(json.dumps(d))
    build(graph, tmp_path, '--no-evidence' if mode == 'unchecked' else '--strict')
    if mode == 'stale_claim':
        doc['claims'][0]['evidence'][0]['quote'] = 'Another quote that was never checked by this report.'
        path.write_text(json.dumps(doc))
    if mode == 'stale_source':
        p = graph / 'sources/example.json'
        s = json.loads(p.read_text()); s['snapshot_sha256'] = '0' * 64
        p.write_text(json.dumps(s))
    if mode == 'missing':
        (tmp_path / 'report.json').unlink()
    flags = []
    if mode == 'wrong_root':
        other = tmp_path / 'other'; shutil.copytree(graph, other); graph = other
    if mode == 'invalid_at':
        flags = ['--at', 'yesterday']
    if mode == 'blank_by':
        flags = ['--by', '   ']
    before = {p: p.read_bytes() for p in graph.glob('*/*.json')}
    result = verify(graph, tmp_path, *flags)
    # Unchecked/error evidence is skipped; stale inputs and manual evidence refuse.
    if mode in {'unchecked', 'error'}:
        assert result.returncode == 0, result.stderr
        changed = json.loads(result.stdout)['claim_ids']
        assert doc['claims'][0]['id'] not in changed
    else:
        assert result.returncode == 2, result.stderr
        assert 'Traceback' not in result.stderr
        diagnostic = {'stale_claim': 'Stale', 'stale_source': 'Stale', 'manual': 'Manual evidence',
                      'missing': 'No such file', 'wrong_root': 'another data directory',
                      'invalid_at': 'ISO datetime', 'blank_by': 'must not be blank'}[mode]
        assert diagnostic in result.stderr
        assert all(p.read_bytes() == raw for p, raw in before.items())


def test_structural_report_still_lists_proposed(graph, tmp_path):
    result, report = build(graph, tmp_path, '--strict', '--no-evidence')
    assert result.returncode == 0
    assert sum(map(len, report['proposed_claims_by_file'].values())) == 23
    assert set(report['evidence_verification'].values()) == {'unchecked'}


def test_unknown_file_and_exception_are_errors(graph, tmp_path):
    build(graph, tmp_path, '--strict')
    before = (graph / 'references/alpha.json').read_bytes()
    for flags in [('--files', tmp_path / 'outside.json'), ('--except', 'clm-missing')]:
        result = verify(graph, tmp_path, *flags)
        assert result.returncode == 2
        assert (graph / 'references/alpha.json').read_bytes() == before


def test_all_evidence_must_pass_and_only_changed_is_respected(graph, tmp_path):
    path = graph / 'references/alpha.json'
    doc = json.loads(path.read_text())
    extra = dict(doc['claims'][0]['evidence'][0], id='ev-zzzzzzzzzz',
                 quote='A second piece of evidence which is absent from the snapshot.')
    doc['claims'][0]['evidence'].append(extra)
    path.write_text(json.dumps(doc))
    build(graph, tmp_path, '--strict', '--only-changed', path)
    result = verify(graph, tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['claim_ids'] == [c['id'] for c in doc['claims'][1:]]
    # No evidence in unselected files was verified by the partial build.
    beta = json.loads((graph / 'references/beta.json').read_text())
    assert all(c['status'] == 'proposed' for c in beta['claims'])


def test_default_timestamp_and_warning_report(graph, tmp_path):
    from datetime import datetime, timezone
    result = cli('build', '--data-dir', graph, '--offline',
                 '--out', tmp_path / 'graph.sqlite', '--report', tmp_path / 'report.json')
    assert result.returncode == 1
    result = verify(graph, tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)['count'] == 0
    build(graph, tmp_path, '--strict')
    start = datetime.now(timezone.utc)
    result = cli('status', 'verify', '--by', 'review-run / chief', '--data-dir', graph,
                 '--report', tmp_path / 'report.json')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['count'] == 23
    claim = json.loads((graph / 'references/alpha.json').read_text())['claims'][0]
    assert start <= datetime.fromisoformat(claim['review']['at']) <= datetime.now(timezone.utc)


def test_manual_claim_can_be_excluded_without_attestation(graph, tmp_path):
    source = json.loads((graph / 'sources/example.json').read_text())
    source.update(id='source:scan', content_type='image_scan')
    (graph / 'sources/scan.json').write_text(json.dumps(source))
    path = graph / 'references/alpha.json'
    doc = json.loads(path.read_text())
    c = doc['claims'][-1]
    c['evidence'][0].update(source='source:scan', match_mode='manual')
    path.write_text(json.dumps(doc))
    build(graph, tmp_path, '--strict')
    result = verify(graph, tmp_path)
    assert result.returncode == 2 and 'Manual evidence' in result.stderr
    assert all(c['status'] == 'proposed' for c in json.loads(path.read_text())['claims'])
    result = verify(graph, tmp_path, '--except', c['id'])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['count'] == 22
    assert json.loads(path.read_text())['claims'][-1]['status'] == 'proposed'


def test_claim_object_edit_invalidates_evidence_report(graph, tmp_path):
    build(graph, tmp_path, '--strict')
    path = graph / 'references/alpha.json'
    doc = json.loads(path.read_text())
    doc['claims'][1]['object']['entity'] = 'caliber:two'
    path.write_text(json.dumps(doc))
    result = verify(graph, tmp_path)
    assert result.returncode == 2 and 'Stale' in result.stderr
    assert all(c['status'] == 'proposed' for c in json.loads(path.read_text())['claims'])
