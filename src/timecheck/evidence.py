"""Verify pinned raw archive bytes before extracting their text."""
import gzip
import hashlib
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from .extract import extract
from .normalize import normalize
from .validate import issue


def verify_evidence(claims, sources, *, snapshot_dir=None, offline=False,
                    strict=False, only_changed=None, cache_dir=None):
    errors, warnings = [], []
    selected = None if only_changed is None else {Path(p).resolve() for p in only_changed}
    cache = {}
    for c in claims:
        if selected is not None and Path(c['path']).resolve() not in selected:
            continue
        for e in c['evidence']:
            if e['match_mode'] == 'manual':
                continue
            source = sources.get(e['source'])
            if source is None:
                continue  # Integrity validation already reports this.
            sha = source['snapshot_sha256']
            key = (sha, source['content_type'], source['archive_url'])
            if key not in cache:
                raw, charset, failure = None, None, None
                local = Path(snapshot_dir, sha + '.bin') if snapshot_dir else None
                stored = Path(cache_dir, sha + '.bin') if cache_dir else None
                for candidate in (local, stored):
                    if candidate and candidate.is_file():
                        try:
                            raw = candidate.read_bytes()
                            charset_file = candidate.with_suffix('.charset')
                            if candidate == stored and charset_file.is_file():
                                charset = charset_file.read_text().strip() or None
                        except OSError as exc:
                            failure = ('snapshot_unavailable', str(exc))
                        break
                if raw is None and (offline or snapshot_dir):
                    failure = ('snapshot_unavailable', f'No local snapshot {sha}')
                elif raw is None:
                    for attempt in range(4):  # initial request + three retries
                        try:
                            request = Request(source['archive_url'], headers={'User-Agent': 'timecheck/0.1 provenance-verifier'})
                            with urlopen(request, timeout=30) as response:
                                raw = response.read()
                                charset = response.headers.get_content_charset()
                            failure = None
                            break
                        except (OSError, URLError) as exc:
                            failure = ('snapshot_unavailable', str(exc))
                            if attempt < 3:
                                time.sleep(2 ** attempt)
                if raw is not None:
                    if hashlib.sha256(raw).hexdigest() != sha:
                        failure = ('snapshot_hash_mismatch', f'Raw snapshot hash does not match {sha}')
                    else:
                        if stored and not stored.exists():
                            stored.parent.mkdir(parents=True, exist_ok=True)
                            stored.write_bytes(raw)
                            if charset:
                                stored.with_suffix('.charset').write_text(charset)
                        try:
                            decoded = gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw
                            content = extract(decoded, source['content_type'], charset)
                        except ValueError as exc:
                            failure = ('unsupported_content_type', str(exc))
                        except (OSError, EOFError) as exc:
                            failure = ('unsupported_content_type', f'Invalid compressed snapshot: {exc}')
                cache[key] = (failure, content if not failure else None)
            failure, content = cache[key]
            if failure:
                kind, message = failure
            elif len(normalize(e['quote'])) < 20:
                kind, message = 'quote_too_short', 'Quote needs 20 normalized characters'
            elif normalize(e['quote']) not in content:
                kind, message = 'quote_not_found', 'Normalized quote absent from pinned snapshot'
            else:
                continue
            destination = warnings if kind == 'snapshot_unavailable' and not strict else errors
            destination.append(issue(kind, message, c['path'], claim_id=c['id'], evidence_id=e['id']))
    return errors, warnings
