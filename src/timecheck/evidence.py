"""Verify pinned raw archive bytes before extracting their text."""
import math
import re
import gzip
import hashlib
import json
import random
import sys
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import zstandard
from urllib.error import HTTPError
from pathlib import Path
from html.parser import HTMLParser
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



ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'


def representation_encoding(raw):
    if raw.startswith(b'\x1f\x8b'):
        return 'gzip'
    if raw.startswith(ZSTD_MAGIC):
        return 'zstd'
    return 'identity'


def decode_representation(raw):
    """Decode only after the caller validates the hash of the original bytes."""
    encoding = representation_encoding(raw)
    if encoding == 'gzip':
        return gzip.decompress(raw)
    if encoding == 'zstd':
        # Streaming captures need not include a decompressed size in the frame.
        chunks, remaining = [], raw
        while remaining:
            frame = zstandard.ZstdDecompressor().decompressobj()
            chunks.append(frame.decompress(remaining))
            if not frame.eof:
                raise zstandard.ZstdError('Incomplete zstd frame')
            remaining = frame.unused_data
        return b''.join(chunks)
    return raw


class _ArchiveTitles(HTMLParser):
    """Read real title elements; markup inside script text is not an element."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.titles, self.parts, self.active = [], [], False

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.parts, self.active = [], True

    def handle_endtag(self, tag):
        if tag == 'title' and self.active:
            self.titles.append(normalize(''.join(self.parts)).lower())
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def _wayback_error(raw, source_type, content_type=None, charset=None):
    """Recognize archive placeholders independently of their particular wording."""
    media = (content_type or '').split(';', 1)[0].strip().lower()
    if media == 'text/html' and source_type != 'html':
        return True
    try:
        decoded = decode_representation(raw)
        # Confirmed PDF bytes are a PDF, including comments that resemble HTML.
        if decoded.startswith(b'%PDF-'):
            return False
        body = extract(decoded, 'html', charset).lower()
    except (OSError, EOFError, zlib.error, zstandard.ZstdError):
        return False
    parser = _ArchiveTitles()
    try:
        text = decoded.decode(charset or 'utf-8', errors='replace')
    except LookupError:
        text = decoded.decode('utf-8', errors='replace')
    parser.feed(text)
    titles = parser.titles
    if 'wayback machine' in titles:
        return True
    if any(message in body for message in (
            "doesn't have that page archived", 'this page is not available', 'hrm.')):
        return True
    # Retain earlier archive-owned error templates with more specific titles.
    archive_template = (any(title.startswith(('wayback machine', 'internet archive', 'rate limit reached'))
                            for title in titles) or b'id="wb-error' in decoded.lower())
    return archive_template and any(message in body for message in (
        'has not archived that url', 'no archived versions', 'cannot be crawled or displayed',
        'url has been excluded', 'rate limit', 'temporarily unavailable',
        'failed to load', 'cannot be displayed due to robots.txt'))


def _retry_delay(attempt, exc=None):
    status = getattr(exc, 'code', None)
    throttled = status in {429, 503} or 'connection refused' in str(exc).lower() or exc == 'placeholder'
    delay = (5 * 2 ** attempt + random.uniform(0, 1)) if throttled else 2 ** attempt
    headers = getattr(exc, 'headers', None)
    retry_after = headers.get('Retry-After') if headers else None
    if retry_after and throttled:
        try:
            seconds = float(retry_after)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                seconds = 0
        delay = max(delay, seconds)
    return min(60, delay)


def verify_evidence(claims, sources, *, snapshot_dir=None, offline=False,
                    strict=False, only_changed=None, cache_dir=None, evidence_ids=None):
    errors, warnings = [], []
    selected = None if only_changed is None else {Path(p).resolve() for p in only_changed}
    cache, last_request = {}, None
    for c in claims:
        if selected is not None and Path(c['path']).resolve() not in selected:
            continue
        for e in c['evidence']:
            if evidence_ids is not None and e['id'] not in evidence_ids:
                continue
            if e['match_mode'] == 'manual':
                continue
            source = sources.get(e['source'])
            if source is None:
                continue
            sha = source['snapshot_sha256']
            key = (sha, source['content_type'], source['archive_url'])
            if key not in cache:
                raw, charset, failure, content = None, None, None, None
                transport = {'archive_url': source['archive_url'], 'http_status': None,
                             'content_encoding': None, 'first_bytes_hex': '',
                             'expected_sha256': sha}
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
                    for attempt in range(4):
                        try:
                            # Serial transport (concurrency one), with spacing even
                            # across different captures in a bulk verification.
                            if last_request is not None:
                                remaining = 1 - (time.monotonic() - last_request)
                                if remaining > 0:
                                    time.sleep(remaining)
                            last_request = time.monotonic()
                            transport.update(http_status=None, content_encoding=None, first_bytes_hex='', attempts=attempt + 1)
                            request = Request(source['archive_url'], headers={
                                'User-Agent': 'timecheck/0.1 provenance-verifier',
                                'Accept-Encoding': 'identity'})
                            with urlopen(request, timeout=30) as response:
                                transport.update(http_status=getattr(response, 'status', 200),
                                                 content_encoding=response.headers.get('Content-Encoding', 'identity'))
                                raw = response.read()
                                charset = response.headers.get_content_charset()
                            transport.update(first_bytes_hex=raw[:32].hex(), actual_sha256=hashlib.sha256(raw).hexdigest())
                            if _wayback_error(raw, source['content_type'], response.headers.get('Content-Type'), charset):
                                failure = ('snapshot_unavailable', 'Wayback returned an error/placeholder page')
                                raw, charset = None, None
                                if attempt < 3:
                                    delay = _retry_delay(attempt, 'placeholder')
                                    time.sleep(delay)
                                    # sleep doubles as pacing; no second delay if a
                                    # test replaces sleep without advancing its clock.
                                    last_request = None
                                continue
                            failure = None
                            break
                        except Exception as exc:
                            raw, charset = None, None
                            if isinstance(exc, HTTPError):
                                transport.update(http_status=exc.code,
                                                 content_encoding=exc.headers.get('Content-Encoding', 'identity') if exc.headers else None)
                                try:
                                    transport['first_bytes_hex'] = exc.read(32).hex()
                                except Exception:
                                    pass
                                finally:
                                    exc.close()
                            failure = ('snapshot_unavailable', f'Archive fetch/read failed ({type(exc).__name__}): {exc}')
                            if attempt < 3:
                                time.sleep(_retry_delay(attempt, exc))
                                last_request = None
                if raw is not None:
                    transport.update(first_bytes_hex=raw[:32].hex(), actual_sha256=hashlib.sha256(raw).hexdigest(),
                                     representation_encoding=representation_encoding(raw))
                    if transport['actual_sha256'] != sha:
                        failure = ('snapshot_hash_mismatch', f'Raw snapshot hash does not match {sha}')
                        # Diagnostic comparison only: never trust alternate bytes.
                        if representation_encoding(raw) != 'identity':
                            try:
                                decoded_sha = hashlib.sha256(decode_representation(raw)).hexdigest()
                                transport.update(decoded_sha256=decoded_sha, encoding_variant_of_pin=decoded_sha == sha)
                            except (OSError, EOFError, zlib.error, zstandard.ZstdError):
                                transport['encoding_variant_of_pin'] = False
                    else:
                        if stored and not stored.exists():
                            stored.parent.mkdir(parents=True, exist_ok=True)
                            stored.write_bytes(raw)
                            if charset:
                                stored.with_suffix('.charset').write_text(charset)
                        try:
                            content = extract(decode_representation(raw), source['content_type'], charset)
                        except ValueError as exc:
                            failure = ('unsupported_content_type', str(exc))
                        except (OSError, EOFError, zlib.error, zstandard.ZstdError) as exc:
                            failure = ('snapshot_unavailable', f"Snapshot {representation_encoding(raw)} decode failed: {exc}")
                cache[key] = (failure, content, transport)
            failure, content, transport = cache[key]
            if failure:
                kind, message = failure
            elif len(normalize(e['quote'])) < 20:
                kind, message = 'quote_too_short', 'Quote needs 20 normalized characters'
            elif not (fuzzy_match(normalize(e['quote']), content) if e['match_mode'] == 'fuzzy' else normalize(e['quote']) in content):
                kind, message = 'quote_not_found', 'Normalized quote absent from pinned snapshot'
            else:
                continue
            destination = warnings if kind == 'snapshot_unavailable' and not strict else errors
            problem = issue(kind, message, c['path'], claim_id=c['id'], evidence_id=e['id'], transport=dict(transport))
            destination.append(problem)
            print(json.dumps(problem, sort_keys=True), file=sys.stderr)
    return errors, warnings
