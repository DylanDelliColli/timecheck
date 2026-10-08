"""Validate, verify and atomically compile the provenance graph."""
from collections import Counter, defaultdict, deque
from importlib.resources import files
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from .evidence import verify_evidence
from .extract import EXTRACTOR_VERSION
from .normalize import NORM_VERSION
from .validate import load_data, issue
from .status import review_fingerprint


def parse_years(years):
    if not years:
        return None, None, 'unknown', 9999
    start, end = years['from'], years['to']
    return start, end if isinstance(end, int) else None, ('year' if isinstance(end, int) else 'present' if end == 'present' else 'unknown'), start if start is not None else 9999


def compute_disputed(claims):
    groups = defaultdict(list)
    for c in claims:
        if c['status'] == 'verified':
            groups[c['subject'], c['predicate']].append(c)
    disputed = set()
    for (_, pred), group in groups.items():
        if pred == 'uses_caliber':
            for i, a in enumerate(group):
                for b in group[i + 1:]:
                    ay, by = a.get('valid_years'), b.get('valid_years')
                    if not ay or not by or any(y['from'] is None or y['to'] is None for y in (ay, by)):
                        continue
                    end_a = float('inf') if ay['to'] == 'present' else ay['to']
                    end_b = float('inf') if by['to'] == 'present' else by['to']
                    if a['object'] != b['object'] and max(ay['from'], by['from']) <= min(end_a, end_b):
                        disputed.update((a['id'], b['id']))
        elif len({json.dumps({'years': {k: c['object']['years'][k] for k in ('from', 'to')}}
                              if 'years' in c['object'] else c['object'], sort_keys=True)
                  for c in group}) > 1:
            disputed.update(c['id'] for c in group)
    return disputed


def _compile(path, entities, sources, claims, disputed):
    with sqlite3.connect(path) as db:
        db.executescript(files('timecheck').joinpath('sql/schema.sql').read_text())
        for ident, doc in entities.items():
            table = 'brand' if doc['kind'] in {'brand', 'maker', 'authority'} else doc['kind']
            db.execute(f'INSERT INTO {table} VALUES (?,?,?,?)', (ident, doc['kind'], doc['display_name'], json.dumps(doc.get('aliases', []))))
        for s in sources.values():
            db.execute('INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                       tuple(s.get(k, '') for k in ('id','kind','url','publisher','trust_tier','reuse_class','licence','content_type','archive_url','snapshot_sha256','retrieved_at','notes')))
        for c in claims:
            primary = any(sources[e['source']]['trust_tier'] == 'primary' for e in c['evidence'])
            db.execute('INSERT INTO claim VALUES (?,?,?,?,?,?,?)', (c['id'], c['subject'], c['predicate'], c['status'], int(c['id'] in disputed), int(c['contested']), int(primary)))
            o = c['object']
            value = o.get('value')
            if value is not None:
                value = value if isinstance(value, str) else json.dumps(value)
            db.execute('INSERT INTO claim_object VALUES (?,?,?,?,?)', (c['id'], o.get('entity'), value, o.get('unit'), json.dumps(o, sort_keys=True)))
            years = c.get('valid_years', o.get('years'))
            if years:
                db.execute('INSERT INTO claim_years VALUES (?,?,?,?,?,?,?)', (c['id'], *parse_years(years), years['from_evidence'], years['to_evidence']))
            if c.get('review'):
                db.execute('INSERT INTO claim_review VALUES (?,?,?)', (c['id'], c['review']['by'], c['review']['at']))
            for e in c['evidence']:
                db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?)', (e['id'], c['id'], e['source'], e['quote'], e['locator'], e['match_mode']))
        db.executescript(files('timecheck').joinpath('sql/views.sql').read_text())
        # Query each view before publishing: invalid SQL must fail during build.
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall():
            db.execute('SELECT * FROM "' + row[0] + '" LIMIT 1').fetchall()


def _coverage(data_dir, claims, errors):
    lines, used = defaultdict(set), set()
    for c in claims:
        if c['status'] == 'verified':
            if c['predicate'] == 'in_line':
                lines[c['object']['entity']].add(c['subject'])
            elif c['predicate'] == 'uses_caliber':
                used.add(c['subject'])
    coverage = {}
    for target in sorted(Path(data_dir, 'targets').glob('*.json')):
        try:
            doc = json.loads(target.read_text())
            line = doc.get('line', 'line:' + target.stem) if isinstance(doc, dict) else 'line:' + target.stem
            refs = doc['references'] if isinstance(doc, dict) else doc
            if not isinstance(refs, list) or not all(isinstance(r, str) and r.startswith('reference:') for r in refs):
                raise ValueError('Target references must be a list of reference ids')
            wanted = set(refs)
            covered = wanted & used & lines[line]
            coverage[line] = {'target': len(wanted), 'covered': len(covered), 'missing': sorted(wanted - covered)}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(issue('invalid_targets', str(exc), target))
    return coverage


def _review_summary(entities, claims):
    proposed = defaultdict(list)
    memberships, used, family = defaultdict(set), defaultdict(set), defaultdict(set)
    for c in claims:
        if c['status'] == 'proposed':
            proposed[c['path']].append(c['id'])
        if c['predicate'] == 'in_line':
            memberships[c['object']['entity']].add(c['subject'])
        elif c['predicate'] == 'uses_caliber':
            used[c['subject']].add(c['object']['entity'])
        elif c['predicate'] in {'derived_from', 'clone_of', 'grade_of'}:
            a, b = c['subject'], c['object']['entity']
            family[a].add(b)
            family[b].add(a)
    counts = {}
    for line, entity in entities.items():
        if entity['kind'] != 'line':
            continue
        subjects = {line} | memberships[line]
        queue = deque(caliber for ref in memberships[line] for caliber in used[ref])
        while queue:
            caliber = queue.popleft()
            if caliber not in subjects:
                subjects.add(caliber)
                queue.extend(family[caliber] - subjects)
        counts[line] = {'verified': 0, 'proposed': 0}
        for c in claims:
            if c['subject'] in subjects:
                counts[line][c['status']] += 1
    return dict(proposed), counts


def _truncations(claims):
    edges = defaultdict(set)
    for c in claims:
        if c['status'] == 'verified' and c['predicate'] in {'derived_from', 'clone_of', 'grade_of'}:
            a, b = c['subject'], c['object']['entity']
            edges[a].add(b)
            edges[b].add(a)
    truncated = []
    for start in edges:
        queue, seen = deque([(start, 0)]), {start}
        while queue:
            node, depth = queue.popleft()
            for neighbor in edges[node] - seen:
                if depth == 6:
                    truncated.append(start)
                    queue.clear()
                    break
                seen.add(neighbor)
                queue.append((neighbor, depth + 1))
    return sorted(set(truncated))


def build(*, data_dir='data', out='timecheck.sqlite', report='report.json', snapshot_dir=None,
          strict=False, offline=False, only_changed=None, cache_dir=None, no_evidence=False):
    entities, sources, claims, errors, warnings, shares = load_data(data_dir)
    integrity_ok = not errors
    if integrity_ok and not no_evidence:
        ev_errors, ev_warnings = verify_evidence(claims, sources, snapshot_dir=snapshot_dir,
                                                offline=offline, strict=strict,
                                                only_changed=only_changed, cache_dir=cache_dir)
        errors.extend(ev_errors)
        warnings.extend(ev_warnings)
    selected = None if only_changed is None else {Path(p).resolve() for p in only_changed}
    evidence_verification = {}
    for c in claims:
        for e in c['evidence']:
            state = 'unchecked'
            if integrity_ok and not no_evidence and (selected is None or Path(c['path']).resolve() in selected):
                state = 'manual' if e['match_mode'] == 'manual' else 'verified'
            evidence_verification[e['id']] = state
    for problem in errors:
        if not no_evidence and problem.get('evidence_id') in evidence_verification:
            evidence_verification[problem['evidence_id']] = 'error'
    for problem in warnings:
        if not no_evidence and problem.get('evidence_id') in evidence_verification:
            evidence_verification[problem['evidence_id']] = 'warning'
    disputed = compute_disputed(claims)
    branches = defaultdict(set)
    for c in claims:
        if c['status'] == 'verified' and c['predicate'] == 'succeeds':
            branches[c['subject']].add(c['object']['entity'])
    branches = {k: sorted(v) for k, v in branches.items() if len(v) > 1}
    proposed_by_file, line_counts = _review_summary(entities, claims)
    result = {
        'data_dir': str(Path(data_dir).resolve()),
        'proposed_claims_by_file': proposed_by_file, 'line_claim_counts': line_counts,
        'review_inputs': {c['id']: review_fingerprint(c, sources) for c in claims},
        'schema_version': 1, 'norm_version': NORM_VERSION, 'extractor_version': EXTRACTOR_VERSION,
        'entity_counts': dict(Counter(d['kind'] for d in [*entities.values(), *sources.values()])),
        'claim_counts': {'status': dict(Counter(c['status'] for c in claims)),
                         'has_primary': dict(Counter('primary' if any(sources.get(e['source'], {}).get('trust_tier') == 'primary' for e in c['evidence']) else 'secondary_only' for c in claims)),
                         'predicate': dict(Counter(c['predicate'] for c in claims))},
        'evidence_count': sum(len(c['evidence']) for c in claims),
        'evidence_verification': evidence_verification,
        'disputed': len(disputed), 'disputed_claims': sorted(disputed),
        'contested': sum(c['contested'] for c in claims), 'branches': branches,
        'years_unknown': sorted(c['id'] for c in claims if c['predicate'] == 'uses_caliber' and (c['valid_years']['from'] is None or c['valid_years']['to'] is None)),
        'pending_manual_attestations': sorted(e['id'] for c in claims if c['status'] == 'proposed' for e in c['evidence'] if e['match_mode'] == 'manual'),
        'coverage': _coverage(data_dir, claims, errors), 'evidence_share': shares,
        'family_truncated': _truncations(claims), 'errors': errors, 'warnings': warnings}
    output = Path(out)
    if output.exists():
        try:
            with sqlite3.connect(f'{output.resolve().as_uri()}?mode=ro', uri=True) as old:
                previous = {r[0] for table in ('brand','line','reference','caliber') for r in old.execute(f'SELECT id FROM {table}')}
            aliases = {a for d in entities.values() for a in d.get('aliases', [])}
            for missing in sorted(previous - entities.keys() - aliases):
                warnings.append(issue('slug_disappeared', f'{missing} disappeared without an alias'))
        except sqlite3.Error:
            pass  # Existing output need not be a previous timecheck database.
    if not errors:
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.timecheck-', suffix='.sqlite', dir=output.parent)
        os.close(fd)
        try:
            _compile(temporary, entities, sources, claims, disputed)
            os.replace(temporary, output)
        except (sqlite3.Error, OSError) as exc:
            errors.append(issue('compile_error', str(exc)))
        finally:
            Path(temporary).unlink(missing_ok=True)
    result['errors_by_class'] = dict(Counter(e['class'] for e in errors))
    result['warnings_by_class'] = dict(Counter(e['class'] for e in warnings))
    report_path = Path(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return (2 if errors else 1 if warnings else 0), result
