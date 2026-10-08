"""Verify pinned raw archive bytes before extracting their text."""
import math
import re
import gzip
import hashlib
from pathlib import Path
import time
import zlib
from urllib.request import Request, urlopen
from .extract import extract
from .normalize import normalize
from .validate import issue


NUMBER = re.compile(r'\d+(?:[.,]\d+)*')


def _levenshtein_at_most(a, b, limit):
    """Unit-cost edit distance, bounded to the threshold diagonal band.

    Values above limit return limit+1. This keeps sliding PDF windows from
    allocating a full matrix or computing rows which cannot qualify.
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = {j: j for j in range(min(len(b), limit) + 1)}
    for i, char in enumerate(a, 1):
        current = {0: i} if i <= limit else {}
        for j in range(max(1, i - limit), min(len(b), i + limit) + 1):
            current[j] = min(previous.get(j, limit + 1) + 1,
                             current.get(j - 1, limit + 1) + 1,
                             previous.get(j - 1, limit + 1) + (char != b[j - 1]))
        if min(current.values(), default=limit + 1) > limit:
            return limit + 1
        previous = current
    return previous.get(len(b), limit + 1)


def fuzzy_match(quote, content):
    """PDF-only normalized Levenshtein ratio >=0.90 over every contiguous ±20% quote window.

    Both inputs have already been normalized. Numeric tokens must match in
    order and in full, including digits embedded in caliber names. Window
    boundaries cannot hide a changed digit by clipping a larger number.
    """
    size = len(quote)
    if not size:
        return False
    numbers = NUMBER.findall(quote)
    spans = [(m.start(), m.end()) for m in NUMBER.finditer(content)]
    numeric_interior = {i for start, end in spans for i in range(start + 1, end)}
    minimum, maximum = math.ceil(size * .8), math.floor(size * 1.2)
    for start in range(len(content) - minimum + 1):
        if start in numeric_interior:
            continue
        for end in range(start + minimum, min(len(content), start + maximum) + 1):
            if end in numeric_interior:
                continue
            window = content[start:end]
            longest = max(size, len(window))
            limit = longest // 10
            if abs(size - len(window)) > limit:
                continue
            if NUMBER.findall(window) != numbers:
                continue
            if _levenshtein_at_most(quote, window, limit) <= limit:
                return True
    return False


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
                        except Exception as exc:
                            # The transport boundary includes opening, body reads
                            # and response teardown. IncompleteRead/HTTPException
                            # are not OSError subclasses; every failed attempt
                            # must leave no bytes from a partial response behind.
                            raw, charset = None, None
                            failure = ('snapshot_unavailable', f'Archive fetch/read failed ({type(exc).__name__}): {exc}')
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
                        except (OSError, EOFError, zlib.error) as exc:
                            failure = ('snapshot_unavailable', f'Snapshot gzip decode failed: {exc}')
                cache[key] = (failure, content if not failure else None)
            failure, content = cache[key]
            if failure:
                kind, message = failure
            elif len(normalize(e['quote'])) < 20:
                kind, message = 'quote_too_short', 'Quote needs 20 normalized characters'
            elif not (fuzzy_match(normalize(e['quote']), content) if e['match_mode'] == 'fuzzy' else normalize(e['quote']) in content):
                kind, message = 'quote_not_found', 'Normalized quote absent from pinned snapshot'
            else:
                continue
            destination = warnings if kind == 'snapshot_unavailable' and not strict else errors
            destination.append(issue(kind, message, c['path'], claim_id=c['id'], evidence_id=e['id']))
    return errors, warnings
