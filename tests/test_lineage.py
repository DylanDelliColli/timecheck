"""Lineage contracts exercised through evidence-verified builds and real SQLite."""
import hashlib
import json

import pytest

from test_integration import SNAPSHOTS, build, change, cli, dataset, rows
from test_integrity import clone


def unknown_usage(doc):
    for claim in doc['claims']:
        if claim['predicate'] == 'uses_caliber':
            claim['valid_years'] = {'from': None, 'to': None, 'from_evidence': None, 'to_evidence': None}


def without_production(doc):
    doc['claims'] = [c for c in doc['claims'] if c['predicate'] != 'produced']


@pytest.mark.parametrize('view', ['v_lineage', 'v_lineage_all'])
@pytest.mark.parametrize('years', ['usage', 'produced', 'unknown'])
def test_lineage_year_source(dataset, tmp_path, view, years):
    if years != 'usage':
        change(dataset, 'references/alpha.json', unknown_usage)
    if years == 'unknown':
        change(dataset, 'references/alpha.json', without_production)
    result, report = build(dataset, tmp_path, '--strict')
    assert result.returncode == 0, (result.stderr, report['errors'])
    alpha, = [r for r in rows(tmp_path, view) if r['reference_id'] == 'reference:alpha']
    assert alpha['year_source'] == years
    assert (alpha['year_from'], alpha['year_to'], alpha['year_to_kind'], alpha['year_from_sort']) == (
        (None, None, 'unknown', 9999) if years == 'unknown' else (2000, 2005, 'year', 2000))
    assert alpha['claim_id'] == 'clm-aaaaaaaaam'
    usage, = [r for r in rows(tmp_path, 'v_reference_calibers' + ('_all' if view.endswith('_all') else ''))
              if r['reference_id'] == 'reference:alpha']
    assert usage['year_from'] == (2000 if years == 'usage' else None)


@pytest.mark.parametrize('view', ['v_lineage', 'v_lineage_all'])
@pytest.mark.parametrize('bound', ['from', 'to'])
def test_partial_usage_keeps_unknown_bound(dataset, tmp_path, view, bound):
    def partial(doc):
        doc['claims'][1]['valid_years'].update({bound: None, bound + '_evidence': None})
    change(dataset, 'references/alpha.json', partial)
    result, report = build(dataset, tmp_path, '--strict')
    assert result.returncode == 0, report['errors']
    alpha, = [r for r in rows(tmp_path, view) if r['reference_id'] == 'reference:alpha']
    assert alpha['year_source'] == 'usage'
    assert alpha['year_' + bound] is None


@pytest.mark.parametrize('view', ['v_lineage', 'v_lineage_all'])
def test_unknown_usage_multiplies_competing_production_intervals(dataset, tmp_path, view):
    change(dataset, 'references/alpha.json', unknown_usage)
    raw = next(SNAPSHOTS.iterdir()).read_bytes() + b'<p>Alpha was produced from 1999 to 2005.</p>'
    sha = hashlib.sha256(raw).hexdigest()
    snapshots = tmp_path / 'snapshots'
    snapshots.mkdir()
    (snapshots / (sha + '.bin')).write_bytes(raw)
    change(dataset, 'sources/example.json', lambda d: d.update(snapshot_sha256=sha))
    secondary = json.loads((dataset / 'sources/example.json').read_text())
    secondary.update(id='source:secondary', trust_tier='secondary')
    (dataset / 'sources/secondary.json').write_text(json.dumps(secondary))
    def compete(doc):
        claim = clone(doc['claims'][2])
        claim['object']['years']['from'] = 1999
        claim['contested'] = True
        claim['evidence'][0].update(source='source:secondary', quote='Alpha was produced from 1999 to 2005.')
        doc['claims'].append(claim)
    change(dataset, 'references/alpha.json', compete)
    result = cli('build', '--strict', '--data-dir', dataset, '--snapshot-dir', snapshots,
                 '--out', tmp_path / 'graph.sqlite', '--report', tmp_path / 'report.json')
    assert result.returncode == 0, result.stderr
    alpha = [r for r in rows(tmp_path, view) if r['reference_id'] == 'reference:alpha']
    assert len(alpha) == 2
    assert all(r['disputed'] == 1 and r['year_source'] == 'produced' for r in alpha)
    assert {(r['year_from'], r['contested'], r['has_primary']) for r in alpha} == {(2000, 0, 1), (1999, 1, 0)}


@pytest.mark.parametrize('view', ['v_lineage', 'v_lineage_all'])
def test_production_fallback_obeys_status_selection(dataset, tmp_path, view):
    change(dataset, 'references/alpha.json', unknown_usage)
    def propose(doc):
        doc['claims'][2]['status'] = 'proposed'
        doc['claims'][2].pop('review')
    change(dataset, 'references/alpha.json', propose)
    result, report = build(dataset, tmp_path, '--strict')
    assert result.returncode == 0, report['errors']
    alpha, = [r for r in rows(tmp_path, view) if r['reference_id'] == 'reference:alpha']
    assert alpha['year_source'] == ('produced' if view.endswith('_all') else 'unknown')


@pytest.mark.parametrize('view', ['v_lineage_diff', 'v_lineage_diff_all'])
@pytest.mark.parametrize('duplicate', [False, True])
def test_single_calibers_diff_without_years(dataset, tmp_path, view, duplicate):
    for file in ['references/alpha.json', 'references/beta.json']:
        change(dataset, file, unknown_usage)
        change(dataset, file, without_production)
    if duplicate:
        change(dataset, 'references/alpha.json', lambda d: d['claims'].append(clone(d['claims'][1])))
    result, report = build(dataset, tmp_path, '--strict')
    assert result.returncode == 0, report['errors']
    diff = rows(tmp_path, view)
    assert len(diff) == 12
    by_attribute = {r['attribute']: r for r in diff}
    assert (by_attribute['caliber']['before_value'], by_attribute['caliber']['after_value'],
            by_attribute['caliber']['changed']) == ('caliber:one', 'caliber:two-top', 1)
    assert by_attribute['jewels']['changed'] == 1
    assert by_attribute['winding']['changed'] == 0
    assert by_attribute['introduced']['changed'] is None  # Undocumented attributes remain unknown.
    assert by_attribute['years']['before_value'] == by_attribute['years']['after_value'] == 'unknown-unknown'
    assert by_attribute['years']['changed'] == 0


@pytest.mark.parametrize('view', ['v_lineage_diff', 'v_lineage_diff_all'])
@pytest.mark.parametrize('side', ['alpha', 'beta'])
@pytest.mark.parametrize('ordering', ['unknown', 'partial', 'known'])
def test_multicaliber_ordering(dataset, tmp_path, view, side, ordering):
    file = f'references/{side}.json'
    if ordering != 'known':
        change(dataset, file, unknown_usage)
        change(dataset, file, without_production)
    def add(doc):
        claim = clone(doc['claims'][1])
        claim['object']['entity'] = 'caliber:two'
        if ordering != 'unknown':
            ev = claim['evidence'][0]['id']
            claim['valid_years'] = {'from': 2002, 'to': 2004, 'from_evidence': ev, 'to_evidence': ev}
        doc['claims'].append(claim)
    change(dataset, file, add)
    result, report = build(dataset, tmp_path, '--strict')
    assert result.returncode == 0, report['errors']
    diff = rows(tmp_path, view)
    assert len(diff) == 12
    if ordering != 'known':
        assert all(r['changed'] is None and r['before_value'] is None and r['after_value'] is None for r in diff)
    else:
        caliber = next(r for r in diff if r['attribute'] == 'caliber')
        assert caliber['before_value' if side == 'alpha' else 'after_value'] == 'caliber:two'
        assert caliber['changed'] == 1


@pytest.mark.parametrize('view', ['v_lineage_diff', 'v_lineage_diff_all'])
def test_diff_years_use_production_and_its_evidence(dataset, tmp_path, view):
    change(dataset, 'references/alpha.json', unknown_usage)
    result, report = build(dataset, tmp_path, '--strict')
    assert result.returncode == 0, report['errors']
    years = next(r for r in rows(tmp_path, view) if r['attribute'] == 'years')
    assert (years['before_value'], years['after_value'], years['changed']) == ('2000-2005', '2006-present', 1)
    assert years['before_evidence_id'] == 'ev-aaaaaaaaaq'
    caliber = next(r for r in rows(tmp_path, view) if r['attribute'] == 'caliber')
    assert caliber['before_evidence_id'] == 'ev-aaaaaaaaam'


@pytest.mark.parametrize('view', ['v_lineage_diff', 'v_lineage_diff_all'])
@pytest.mark.parametrize('unknown_end', [False, True])
def test_mixed_usage_and_production_starts_cannot_order_calibers(dataset, tmp_path, view, unknown_end):
    change(dataset, 'references/alpha.json', unknown_usage)
    def earlier(doc):
        claim = clone(doc['claims'][1])
        claim['object']['entity'] = 'caliber:two'
        ev = claim['evidence'][0]['id']
        claim['valid_years'] = {'from': 1998, 'to': None if unknown_end else 1999,
                                'from_evidence': ev, 'to_evidence': None if unknown_end else ev}
        doc['claims'].append(claim)
    change(dataset, 'references/alpha.json', earlier)
    result, report = build(dataset, tmp_path, '--strict')
    assert result.returncode == 0, report['errors']
    diff = rows(tmp_path, view)
    assert len(diff) == 12 and all(r['changed'] is None for r in diff)


@pytest.mark.parametrize('view', ['v_lineage_diff', 'v_lineage_diff_all'])
@pytest.mark.parametrize('side', ['alpha', 'beta'])
@pytest.mark.parametrize('ordering', ['production', 'mixed', 'tie', 'known'])
@pytest.mark.parametrize('duplicate', [False, True])
def test_sourced_multicaliber_chronology(dataset, tmp_path, view, side, ordering, duplicate):
    """The evaluator's unknown-usage case, plus own-year ties and known neighbors."""
    # Every altered usage has a faithful, machine-matched synthetic quote.
    quotes = []
    def usages(doc):
        original = doc['claims'][1]
        other = clone(original)
        other['object']['entity'] = 'caliber:two'
        first_start = 2000 if side == 'alpha' else 2006
        second_start = first_start if ordering == 'tie' else first_start + 2
        for claim, start in [(original, first_start), (other, second_start)]:
            known = ordering in {'known', 'tie'} or (ordering == 'mixed' and claim is other)
            name = {'caliber:one': 'One', 'caliber:two': 'Two', 'caliber:two-top': 'Two Top'}[claim['object']['entity']]
            quote = f'Reference {side.title()} used caliber {name}; '
            quote += f'usage began in {start}, and its end year is unknown.' if known else 'the individual usage years are unknown.'
            claim['evidence'][0]['quote'] = quote
            ev = claim['evidence'][0]['id']
            claim['valid_years'] = {'from': start if known else None, 'to': None,
                                    'from_evidence': ev if known else None, 'to_evidence': None}
            quotes.append(quote)
        doc['claims'].append(other)
        if duplicate:
            doc['claims'].append(clone(original))
            doc['claims'].append(clone(other))
    change(dataset, f'references/{side}.json', usages)
    # Alpha's production remains 2000–2005. Beta has no production in the
    # baseline; give it a sourced fallback too so both edge sides are covered.
    if side == 'beta':
        production = clone(json.loads((dataset / 'references/alpha.json').read_text())['claims'][2])
        ev = production['evidence'][0]['id']
        production['object']['years'] = {'from': 2006, 'to': 'present', 'from_evidence': ev, 'to_evidence': ev}
        production['evidence'][0]['quote'] = 'Beta was produced from 2006 to the present.'
        quotes.append(production['evidence'][0]['quote'])
        change(dataset, 'references/beta.json', lambda d: d['claims'].append(production))
    raw = next(SNAPSHOTS.iterdir()).read_bytes() + ('<p>' + '</p><p>'.join(quotes) + '</p>').encode()
    sha = hashlib.sha256(raw).hexdigest()
    snapshots = tmp_path / 'snapshots'
    snapshots.mkdir()
    (snapshots / (sha + '.bin')).write_bytes(raw)
    change(dataset, 'sources/example.json', lambda d: d.update(snapshot_sha256=sha))
    result = cli('build', '--strict', '--data-dir', dataset, '--snapshot-dir', snapshots,
                 '--out', tmp_path / 'graph.sqlite', '--report', tmp_path / 'report.json')
    assert result.returncode == 0, result.stderr
    diff = rows(tmp_path, view)
    assert len(diff) == 12  # One row per attribute, including ambiguous edges.
    query = cli('query', 'v_lineage_diff', '--db', tmp_path / 'graph.sqlite', '--json',
                *(['--include-proposed'] if view.endswith('_all') else []))
    assert query.returncode == 0, query.stderr
    assert json.loads(query.stdout) == diff
    if ordering == 'known':
        caliber = next(r for r in diff if r['attribute'] == 'caliber')
        assert (caliber['before_value'], caliber['after_value'], caliber['changed']) == (
            ('caliber:two', 'caliber:two-top', 1) if side == 'alpha' else ('caliber:one', 'caliber:two-top', 1))
    else:
        assert all(all(r[column] is None for column in (
            'before_value', 'after_value', 'changed', 'before_status', 'after_status',
            'before_evidence_id', 'after_evidence_id')) for r in diff)
    if ordering == 'production':
        lineage = rows(tmp_path, 'v_lineage_all' if view.endswith('_all') else 'v_lineage')
        affected = [r for r in lineage if r['reference_id'] == f'reference:{side}']
        assert all(r['year_source'] == 'produced' for r in affected)


@pytest.mark.parametrize('view', ['v_lineage_diff', 'v_lineage_diff_all'])
def test_missing_caliber_retains_unknown_comparisons(dataset, tmp_path, view):
    change(dataset, 'references/alpha.json', lambda d: d.update(
        claims=[c for c in d['claims'] if c['predicate'] != 'uses_caliber']))
    result, report = build(dataset, tmp_path, '--strict')
    assert result.returncode == 0, report['errors']
    diff = rows(tmp_path, view)
    assert len(diff) == 12 and all(r['changed'] is None for r in diff)
