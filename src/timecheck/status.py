"""Apply a maintainer's review using a build's verified, unchanged inputs."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .validate import load_data


def review_fingerprint(claim, sources):
    """Bind quote checks to the claim, subject and source metadata they checked.

    Status/review are omitted so applying the report is idempotent. Paths are
    checked separately, allowing relative/absolute spellings of the same root.
    """
    payload = {k: v for k, v in claim.items() if k not in {'path', 'status', 'review'}}
    payload['sources'] = {e['source']: sources.get(e['source']) for e in claim['evidence']}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def verify_status(*, by, at=None, data_dir='data', report='report.json', files=None, exclude=()):
    if not by.strip():
        raise ValueError('Reviewer --by must not be blank')
    at = at or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    try:
        stamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('timezone required')
    except ValueError as exc:
        raise ValueError('--at needs an ISO datetime with a timezone') from exc
    latest = json.loads(Path(report).read_text())
    if not isinstance(latest, dict) or latest.get('data_dir') != str(Path(data_dir).resolve()):
        raise ValueError('Build report belongs to another data directory; rebuild first')
    fingerprints = latest.get('review_inputs', {})
    states = latest.get('evidence_verification', {})
    if not isinstance(fingerprints, dict) or not isinstance(states, dict):
        raise ValueError('Build report lacks review input metadata; rebuild first')
    _, sources, claims, errors, _, _ = load_data(data_dir)
    if errors:
        raise ValueError('Data validation failed; rebuild and repair before review: ' + errors[0]['message'])
    paths = {Path(c['path']).resolve() for c in claims}
    selected = paths if files is None else {Path(p).resolve() for p in files}
    if selected - paths:
        raise ValueError('Unknown claim file: ' + str(sorted(selected - paths)[0]))
    excluded = set(exclude)
    if excluded - {c['id'] for c in claims}:
        raise ValueError('Unknown excluded claim: ' + sorted(excluded - {c['id'] for c in claims})[0])
    changed, documents, originals = [], {}, {}
    # Validate every candidate before touching any file, including manual claims.
    for c in claims:
        path = Path(c['path']).resolve()
        if path not in selected or c['status'] != 'proposed' or c['id'] in excluded:
            continue
        if any(e['match_mode'] == 'manual' for e in c['evidence']):
            raise ValueError('Manual evidence requires human attestation; exclude claim ' + c['id'])
        if fingerprints.get(c['id']) != review_fingerprint(c, sources):
            raise ValueError('Stale or missing report input for ' + c['id'] + '; rebuild first')
        if not all(e['match_mode'] == 'exact' and states.get(e['id']) == 'verified' for e in c['evidence']):
            continue
        if path not in documents:
            originals[path] = path.read_bytes()
            documents[path] = json.loads(originals[path])
        entry = next(item for item in documents[path]['claims'] if item['id'] == c['id'])
        entry.update(status='verified', review={'by': by, 'at': at})
        changed.append(c['id'])
    staged = {}
    try:
        for path, doc in documents.items():
            fd, name = tempfile.mkstemp(prefix='.timecheck-review-', dir=path.parent)
            staged[path] = Path(name)
            with os.fdopen(fd, 'w') as output:
                output.write(json.dumps(doc, indent=2, ensure_ascii=False) + '\n')
            os.chmod(name, path.stat().st_mode & 0o777)
        if any(path.read_bytes() != raw for path, raw in originals.items()):
            raise ValueError('Claim files changed during review; retry with a fresh report')
        for path, temporary in staged.items():
            os.replace(temporary, path)
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
    return {'count': len(changed), 'claim_ids': changed}
