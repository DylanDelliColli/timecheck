"""Schema and graph integrity validation; no archive access."""
from collections import Counter, defaultdict
from importlib.resources import files
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from publicsuffix2 import get_sld
from .normalize import normalize

SCHEMAS = files('timecheck').joinpath('schemas')
VOCABULARIES = json.loads(SCHEMAS.joinpath('vocabularies.json').read_text())['predicates']
FOLDERS = {'brands': {'brand', 'maker', 'authority'}, 'lines': {'line'},
           'references': {'reference'}, 'calibers': {'caliber'}, 'sources': {'source'}}


def issue(kind, message, location=None, **context):
    return {'class': kind, 'message': message, **({'location': str(location)} if location else {}), **context}


def domain(url):
    host = (urlparse(url).hostname or '').lower().rstrip('.')
    return get_sld(host) or host


def validators():
    schemas = [json.loads(SCHEMAS.joinpath(f'{name}.schema.json').read_text())
               for name in ('entity', 'claim', 'source')]
    registry = Registry().with_resources((s['$id'], Resource.from_contents(s)) for s in schemas)
    return {name: Draft202012Validator(s, registry=registry, format_checker=FormatChecker())
            for name, s in zip(('entity', 'claim', 'source'), schemas)}


def _states_absence(quote, predicate):
    """Require a negated attribute, not a compound such as 'hacking problems'."""
    noun = 'hack(?:ing)?' if predicate == 'hacking' else 'grades?'
    article = r'(?:(?:a|an|the|any)\s+)?'
    clause_end = r'(?=\s*(?:[,.;:!?)]|\b(?:and|but|or)\b|$))'
    patterns = [
        rf"\b(?:no|without|not)\s+{article}{noun}\b{clause_end}",
        rf"\bnon[- ]{noun}\b{clause_end}",
        # Have/offer/support are explicit absence verbs, not arbitrary modifiers.
        rf"\b(?:does not|do not|doesn't|don't)(?:\s+(?:have|offer|support))?\s+{article}{noun}\b{clause_end}",
        rf"\b{noun}\s+(?:(?:is|are)\s+)?(?:not\s+(?:available|offered|supported)|absent|unavailable)\b{clause_end}",
    ]
    if predicate == 'offers_grades':
        patterns.append(rf"\b(?:single grade|one grade only|no grades offered)\b{clause_end}")
    text = normalize(quote).lower()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if re.match(r"(?:without|no\b|non[- ])", match.group()):
                # Negation of a negation is affirmative. Limit the lookback to
                # this clause so unrelated earlier negatives do not mask absence.
                prefix = re.split(r"[,.;:!?)]|\b(?:and|but|or)\b", text[:match.start()])[-1]
                if re.search(r"\b(?:not|never)\b|n't\b", prefix):
                    continue
            return True
    return False


def load_data(data_dir):
    entities, sources, claims, errors, warnings = {}, {}, [], [], []
    seen = set()
    checks = validators()
    root = Path(data_dir)
    if not root.is_dir():
        errors.append(issue('data_unavailable', 'Data directory does not exist', root))
    for folder, kinds in FOLDERS.items():
        for path in sorted((root / folder).glob('*.json')):
            try:
                doc = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                errors.append(issue('invalid_json', str(exc), path))
                continue
            if not isinstance(doc, dict):
                errors.append(issue('schema_error', 'Entity must be an object', path))
                continue
            schema = checks['source' if folder == 'sources' else 'entity']
            schema_errors = list(schema.iter_errors(doc))
            # Use domain-specific errors even when the schema fails first.
            for c in doc.get('claims', []) if isinstance(doc.get('claims', []), list) else []:
                if isinstance(c, dict) and not c.get('evidence'):
                    errors.append(issue('evidence_missing', 'Claim needs evidence', path, claim_id=c.get('id')))
            for c in doc.get('claims', []) if isinstance(doc.get('claims', []), list) else []:
                if not isinstance(c, dict):
                    continue
                for e in c.get('evidence', []) if isinstance(c.get('evidence', []), list) else []:
                    if isinstance(e, dict) and isinstance(e.get('quote'), str) and len(normalize(e['quote'])) < 20:
                        errors.append(issue('quote_too_short', 'Quote needs 20 normalized characters', path, evidence_id=e.get('id')))
            for error in schema_errors:
                errors.append(issue('schema_error', error.message, path,
                                    json_path='/'.join(map(str, error.absolute_path))))
            if schema_errors:
                continue
            ident = doc['id']
            if ident in seen:
                errors.append(issue('duplicate_id', ident, path))
            seen.add(ident)
            prefix = 'brand' if doc['kind'] in {'maker', 'authority'} else doc['kind']
            if doc['kind'] not in kinds or not ident.startswith(prefix + ':') or path.stem != ident.split(':')[1]:
                errors.append(issue('entity_identity', 'Kind, prefix, directory and filename must agree', path))
            (sources if folder == 'sources' else entities)[ident] = doc
            for c in doc.get('claims', []):
                claims.append({**c, 'subject': ident, 'path': str(path)})
                for cid in [c['id'], *(e['id'] for e in c['evidence'])]:
                    if cid in seen:
                        errors.append(issue('duplicate_id', cid, path))
                    seen.add(cid)
    aliases = {}
    for ident, doc in entities.items():
        for alias in doc.get('aliases', []):
            if alias in entities or (alias in aliases and aliases[alias] != ident):
                errors.append(issue('alias_collision', alias))
            aliases[alias] = ident
    def resolve(ident):
        return ident if ident in entities else aliases.get(ident)
    for c in claims:
        rule = VOCABULARIES[c['predicate']]
        subject_kind = entities[c['subject']]['kind']
        if subject_kind != rule['subject']:
            errors.append(issue('predicate_subject', c['predicate'], c['path'], claim_id=c['id']))
        if 'entity' in c['object']:
            target = c['object']['entity']
            resolved = resolve(target)
            if not resolved:
                errors.append(issue('unresolved_slug', target, c['path'], claim_id=c['id']))
            else:
                kind = entities[resolved]['kind']
                if kind not in rule['terms']:
                    errors.append(issue('predicate_object', target, c['path'], claim_id=c['id']))
                if resolved != target:
                    warnings.append(issue('alias_used', f'{target} resolves to {resolved}', c['path']))
                    c['object'] = {'entity': resolved}
                if resolved == c['subject']:
                    errors.append(issue('self_relation', target, c['path']))
        evidence_ids = {e['id'] for e in c['evidence']}
        years = c.get('valid_years', c['object'].get('years'))
        if years:
            f, t = years['from'], years['to']
            if isinstance(f, int) and isinstance(t, int) and f > t:
                errors.append(issue('invalid_years', 'from must not exceed to', c['path']))
            for bound in ('from', 'to'):
                val, eid = years[bound], years[bound + '_evidence']
                if (val is None and eid is not None) or (val is not None and eid not in evidence_ids):
                    errors.append(issue('year_evidence', f'Invalid {bound} evidence id', c['path'], claim_id=c['id']))
        if c['predicate'] in {'hacking', 'offers_grades'} and c['object']['value'] is False:
            if not any(_states_absence(e['quote'], c['predicate']) for e in c['evidence']):
                errors.append(issue('explicit_absence_required', c['predicate'], c['path'], claim_id=c['id']))
        for e in c['evidence']:
            source = sources.get(e['source'])
            if not source:
                errors.append(issue('unresolved_slug', e['source'], c['path'], evidence_id=e['id']))
                continue
            if e['match_mode'] == 'manual' and c['status'] == 'verified' and re.match(r'(?:w-|ao-|worker|chief|agent|codex|claude)', c['review']['by'], re.I):
                errors.append(issue('manual_attestation_required', 'Known agent identity cannot verify a scan', c['path'], evidence_id=e['id']))
            if source['content_type'] == 'image_scan' and e['match_mode'] != 'manual':
                errors.append(issue('unsupported_content_type', 'image_scan requires manual matching', c['path']))
            if source['content_type'] != 'image_scan' and e['match_mode'] == 'manual':
                errors.append(issue('unsupported_content_type', 'manual is reserved for image_scan', c['path']))
            if domain(source['url']) == 'wikipedia.org' and (source['licence'] != 'CC BY-SA 4.0' or len(normalize(e['quote'])) > 200 or not re.search(r'(?:[?&]oldid=\d+|/Special:PermanentLink/\d+)', source['url'])):
                errors.append(issue('wikipedia_policy', 'Wikipedia needs a permanent revision, CC BY-SA 4.0 and quotes <=200 characters', c['path']))
    for s in sources.values():
        if re.search(r'(?:\bNC\b|non[ -]?commercial)', s['licence'], re.I):
            errors.append(issue('banned_source', s['id']))
    grades = {c['subject'] for c in claims if c['predicate'] == 'grade_of'}
    for c in claims:
        if c['predicate'] == 'grade_name' and c['subject'] not in grades:
            errors.append(issue('grade_without_base', c['subject']))
    in_lines = defaultdict(set)
    for c in claims:
        if c['predicate'] == 'in_line':
            in_lines[c['subject']].add(c['object']['entity'])
    edges = defaultdict(set)
    for c in claims:
        if c['predicate'] != 'succeeds':
            continue
        a, b = c['subject'], c['object']['entity']
        if in_lines[a] != in_lines[b] or len(in_lines[a]) != 1:
            errors.append(issue('succeeds_line', 'Succession must be within one documented line', c['path']))
        edges[a].add(b)
    # Iterative color traversal avoids recursion limits on large contributor datasets.
    colors = {}
    for start in list(edges):
        stack = [(start, False)]
        while stack:
            node, done = stack.pop()
            if done:
                colors[node] = 2
                continue
            if colors.get(node) == 1:
                errors.append(issue('succeeds_cycle', node))
                break
            if colors.get(node) == 2:
                continue
            colors[node] = 1
            stack.append((node, True))
            stack.extend((target, False) for target in edges.get(node, ()))
    total = sum(len(c['evidence']) for c in claims)
    shares = Counter()
    capped = Counter()
    for c in claims:
        for e in c['evidence']:
            if e['source'] in sources:
                s = sources[e['source']]
                d = domain(s['url'])
                shares[d] += 1
                if s['reuse_class'] == 'cite_only':
                    capped[d] += 1
    if total >= 50:
        for d, count in capped.items():
            if count / total > .20:
                errors.append(issue('domain_cap', f'{d}: {count}/{total} exceeds 20%'))
    return entities, sources, claims, errors, warnings, {d: {'count': n, 'share': n / total if total else 0} for d, n in sorted(shares.items())}
