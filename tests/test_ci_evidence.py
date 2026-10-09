"""Real git base/head comparisons composed with build and SQLite."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest
from test_integration import dataset, SNAPSHOTS

ROOT = Path(__file__).resolve().parents[1]


def helper():
    spec = importlib.util.spec_from_file_location('ci_evidence', ROOT / 'scripts/verify_evidence.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.mark.parametrize('edit', ['status', 'quote', 'source', 'new', 'deleted_source'])
def test_revision_comparison_and_real_partial_build(dataset, tmp_path, edit):
    repo = tmp_path / 'repo'; repo.mkdir(); shutil.move(dataset, repo / 'data')
    git(repo, 'init', '-q'); git(repo, 'config', 'user.email', 'test@example.org'); git(repo, 'config', 'user.name', 'Test')
    git(repo, 'add', 'data'); git(repo, 'commit', '-qm', 'base'); base = git(repo, 'rev-parse', 'HEAD')
    path = repo / 'data/references/alpha.json'; doc = json.loads(path.read_text())
    ident = doc['claims'][1]['evidence'][0]['id']
    if edit == 'status':
        for p in (repo / 'data').glob('*/*.json'):
            d = json.loads(p.read_text())
            for c in d.get('claims', []) if isinstance(d, dict) else []: c.update(status='proposed'); c.pop('review', None)
            p.write_text(json.dumps(d))
    elif edit == 'quote':
        doc['claims'][1]['evidence'][0]['quote'] += ' This is absent.'; path.write_text(json.dumps(doc))
    elif edit == 'new':
        ev = dict(doc['claims'][1]['evidence'][0], id='ev-zzzzzzzzzz')
        doc['claims'][1]['evidence'].append(ev); path.write_text(json.dumps(doc)); ident = ev['id']
    elif edit == 'source':
        p = repo / 'data/sources/example.json'; d = json.loads(p.read_text()); d['snapshot_sha256'] = '0' * 64; p.write_text(json.dumps(d))
    else:
        (repo / 'data/sources/example.json').unlink()
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'head'); head = git(repo, 'rev-parse', 'HEAD')
    # Uncommitted edits must not affect comparison against the requested revisions.
    if edit == 'status': path.write_text('{}')
    selected = helper().changed_evidence(repo, base, head)
    assert selected == (set() if edit == 'status' else {ident} if edit in {'quote', 'new'} else
                        {e['id'] for p in (repo / 'data').glob('*/*.json') for d in [json.loads(p.read_text())] for c in (d.get('claims', []) if isinstance(d, dict) else []) for e in c['evidence']})
    git(repo, 'checkout', '--', 'data')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_evidence.py'),
                             '--base', base, '--head', head, '--snapshot-dir', str(SNAPSHOTS),
                             '--out', str(tmp_path / 'graph.sqlite'), '--report', str(tmp_path / 'report.json')],
                            cwd=repo, capture_output=True, text=True)
    code = result.returncode; report = json.loads((tmp_path / 'report.json').read_text())
    assert json.loads(result.stdout.splitlines()[0])['selected_evidence_ids'] == sorted(selected)
    assert code == (2 if edit in {'quote', 'source', 'deleted_source'} else 0)
    if edit == 'status':
        assert set(report['evidence_verification'].values()) == {'unchecked'}
        with sqlite3.connect(tmp_path / 'graph.sqlite') as db:
            assert db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 23
    if edit == 'quote': assert report['errors_by_class'] == {'quote_not_found': 1}


def test_sample_is_bounded_deterministic_and_rotates():
    module = helper()
    sources = {f'source:{i}': {'snapshot_sha256': str(i), 'archive_url': str(i), 'content_type': 'html'} for i in range(30)}
    claims = [{'evidence': [{'id': f'ev-{i}', 'source': f'source:{i}', 'match_mode': 'exact'}]} for i in range(30)]
    a = module.sample_evidence(claims, sources, day=100, size=5)
    assert len(a) == 5 and a == module.sample_evidence(claims, sources, day=100, size=5)
    b = module.sample_evidence(claims, sources, day=101, size=5)
    assert len(b) == 5 and a.isdisjoint(b)
    assert module.sample_evidence([], {}, day=100, size=5) == set()
