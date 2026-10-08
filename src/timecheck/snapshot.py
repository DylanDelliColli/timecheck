"""Request a capture and hash its pinned raw Wayback response bytes."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import re
import time
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


CAPTURE = re.compile(r'^https?://web\.archive\.org/web/(\d{14})(?:[a-z]+_)?/(https?://.+)$')


def _request(url):
    for attempt in range(4):
        try:
            request = Request(url, headers={'User-Agent': 'timecheck/0.1 provenance-verifier',
                                            'Accept-Encoding': 'identity'})
            with urlopen(request, timeout=30) as response:
                return response.read(), response.headers, response.geturl()
        except Exception as exc:
            if attempt == 3:
                raise ValueError(f'Wayback request failed after 4 attempts for {url} ({type(exc).__name__}): {exc}') from exc
            time.sleep(2 ** attempt)


def _pinned(candidate, target):
    if not candidate:
        return None
    match = CAPTURE.fullmatch(urljoin('https://web.archive.org', candidate))
    if not match or match[2] != target:
        return None
    try:
        datetime.strptime(match[1], '%Y%m%d%H%M%S')
    except ValueError:
        return None
    return f'https://web.archive.org/web/{match[1]}id_/{target}'


def _guess(raw, headers, target):
    sample = gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw
    media = headers.get('Content-Type', '').split(';')[0].lower()
    if sample.startswith(b'%PDF-') or media == 'application/pdf' or urlsplit(target).path.lower().endswith('.pdf'):
        return 'pdf_text'  # A guess only: a scan may have no extractable text.
    if media.startswith('image/'):
        return 'image_scan'
    if media == 'text/html' or re.search(br'<(?:!doctype\s+html|html|head|body)\b', sample[:1024], re.I):
        return 'html'
    return 'text'


def pin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('snapshot pin needs an absolute HTTP(S) URL without credentials, whitespace or a fragment')
    requested_at = datetime.now(timezone.utc)
    _, headers, resolved = _request('https://web.archive.org/save/' + url)
    pinned = next((p for candidate in (headers.get('Content-Location'), headers.get('Location'), resolved)
                   if (p := _pinned(candidate, url))), None)
    if pinned is None:
        # A save may be queued or return its status page. Resolve the nearest
        # available capture to the request time using the availability endpoint.
        query = urlencode({'url': url, 'timestamp': requested_at.strftime('%Y%m%d%H%M%S')})
        raw, _, _ = _request('https://archive.org/wayback/available?' + query)
        try:
            closest = json.loads(raw)['archived_snapshots']['closest']
            if closest.get('available') is True and str(closest.get('status')) == '200':
                pinned = _pinned(closest.get('url'), url)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError('Wayback did not return an available capture for ' + url) from exc
    if pinned is None:
        raise ValueError('Wayback did not return an available capture for ' + url + '; capture may still be queued, retry later')
    raw, headers, resolved = _request(pinned)
    final = _pinned(resolved, url)
    if final is None or 'id_/' not in resolved:
        raise ValueError('Wayback raw download redirected outside a pinned id_ capture: ' + resolved)
    return {'archive_url': final, 'snapshot_sha256': hashlib.sha256(raw).hexdigest(),
            'content_type': _guess(raw, headers, url),
            'retrieved_at': datetime.now(timezone.utc).date().isoformat()}
