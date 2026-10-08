"""A real 500-reference/150-caliber graph exercises all canonical views."""
import base64
import hashlib
import json
import sqlite3
import time

from timecheck.build import build

VIEWS = ['v_reference_calibers', 'v_caliber_family', 'v_shared_dna',
         'v_lineage', 'v_lineage_diff', 'v_evidence']


def test_six_views_under_five_seconds(tmp_path):
    data, snapshots = tmp_path / 'data', tmp_path / 'snapshots'
    snapshots.mkdir()
    raw = b'Synthetic graph evidence documents membership, ancestry, usage, and specifications.'
    sha = hashlib.sha256(raw).hexdigest()
    (snapshots / (sha + '.bin')).write_bytes(raw)
    counter = 0
    def claim(predicate, obj, years=False):
        nonlocal counter
        counter += 1
        suffix = base64.b32encode(counter.to_bytes(6, 'big')).decode().lower().rstrip('=')
        ev = 'ev-' + suffix
        c = {'id': 'clm-' + suffix, 'predicate': predicate, 'object': obj,
             'status': 'verified', 'contested': False,
             'review': {'by': 'synthetic-reviewer', 'at': '2026-10-08T23:00:00Z'},
             'evidence': [{'id': ev, 'source': 'source:synthetic', 'quote': raw.decode(),
                           'locator': 'synthetic paragraph', 'match_mode': 'exact'}]}
        if years:
            c['valid_years'] = {'from': 2000, 'to': 2020, 'from_evidence': ev, 'to_evidence': ev}
        return c
    def write(folder, ident, kind, claims):
        path = data / folder / (ident.split(':')[1] + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'schema_version': 1, 'id': ident, 'kind': kind,
                                    'display_name': ident, 'aliases': [], 'claims': claims}))
    write('brands', 'brand:synthetic', 'brand', [])
    write('lines', 'line:synthetic', 'line', [claim('owned_by', {'entity': 'brand:synthetic'})])
    # Fifteen families, each with a base and nine derivatives: a plausible star
    # exposes branching while keeping this workload independent of invented facts.
    for n in range(150):
        claims = [claim('made_by', {'entity': 'brand:synthetic'}),
                  claim('jewels', {'value': 17 + n % 10, 'unit': 'count'})]
        if n % 10:
            claims.append(claim('derived_from', {'entity': f'caliber:c{n // 10 * 10}'}))
        write('calibers', f'caliber:c{n}', 'caliber', claims)
    for n in range(500):
        claims = [claim('in_line', {'entity': 'line:synthetic'}),
                  claim('uses_caliber', {'entity': f'caliber:c{n % 150}'}, True)]
        if n and n % 10:
            claims.append(claim('succeeds', {'entity': f'reference:r{n-1}'}))
        write('references', f'reference:r{n}', 'reference', claims)
    (data / 'sources').mkdir()
    (data / 'sources/synthetic.json').write_text(json.dumps({
        'schema_version': 1, 'id': 'source:synthetic', 'kind': 'source',
        'url': 'https://example.org/synthetic', 'publisher': 'Project test',
        'trust_tier': 'primary', 'reuse_class': 'open', 'licence': 'CC0-1.0',
        'content_type': 'text', 'archive_url': 'https://web.archive.org/web/20261008120000id_/https://example.org/synthetic',
        'snapshot_sha256': sha, 'retrieved_at': '2026-10-08', 'notes': 'Synthetic only'}))
    code, report = build(data_dir=data, snapshot_dir=snapshots, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 0, report['errors']
    timings = {}
    with sqlite3.connect(tmp_path / 'graph.sqlite') as db:
        # Abort an unexpectedly slow query, avoiding an unbounded CI process.
        for suffix in ('', '_all'):
            for view in VIEWS:
                start = time.perf_counter()
                db.set_progress_handler(lambda: int(time.perf_counter() - start >= 5), 10000)
                rows = db.execute('SELECT * FROM ' + view + suffix).fetchall()
                timings[view + suffix] = time.perf_counter() - start
                assert rows
                assert timings[view + suffix] < 5
                if view in {'v_reference_calibers', 'v_lineage'}:
                    assert len(rows) == 500
                if view == 'v_caliber_family':
                    assert len(rows) == 1350
                if view == 'v_lineage_diff':
                    assert len(rows) == 450 * 12
    assert sum(timings.values()) < 5
    print('view query seconds:', json.dumps(timings, sort_keys=True))
