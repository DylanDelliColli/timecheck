"""Recorded protocol fixtures; these tests never open a socket."""
import hashlib
import json
from email.message import Message
from io import BytesIO

import pytest

from timecheck.cli import main

TARGET = 'https://example.org/specification?lang=en&edition=2'
CAPTURE = 'https://web.archive.org/web/20261008120000/' + TARGET
PINNED = CAPTURE.replace('20261008120000/', '20261008120000id_/')


class Response(BytesIO):
    def __init__(self, raw, *, headers=None, url=CAPTURE):
        super().__init__(raw)
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value
        self.url = url

    def geturl(self):
        return self.url


@pytest.mark.parametrize('capture_response', ['location', 'content-location', 'available'])
def test_pin_recorded_responses(monkeypatch, capsys, capture_response):
    from timecheck import snapshot
    raw = b'<html>Project-authored synthetic archive.</html>'
    calls = []
    def open_recorded(request, timeout):
        calls.append(request.full_url)
        assert timeout == 30
        if len(calls) == 1:
            headers = {'Location': CAPTURE} if capture_response == 'location' else {'Content-Location': CAPTURE.removeprefix('https://web.archive.org')} if capture_response == 'content-location' else {}
            return Response(b'Capture queued', headers=headers, url='https://web.archive.org/save/' + TARGET)
        if '/wayback/available?' in request.full_url:
            return Response(json.dumps({'archived_snapshots': {'closest': {'available': True, 'status': '200', 'url': CAPTURE, 'timestamp': '20261008120000'}}}).encode())
        assert request.full_url == PINNED
        return Response(raw, headers={'Content-Type': 'text/html'}, url=PINNED)
    monkeypatch.setattr(snapshot, 'urlopen', open_recorded)
    assert main(['snapshot', 'pin', TARGET]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['archive_url'] == PINNED
    assert result['snapshot_sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['content_type'] == 'html'
    assert len(result['retrieved_at']) == 10
    assert calls[0] == 'https://web.archive.org/save/' + TARGET


def test_timeout_retries_and_clear_error(monkeypatch, capsys):
    from timecheck import snapshot
    calls, delays = [], []
    def fail(request, timeout):
        calls.append(request.full_url)
        raise TimeoutError('recorded timeout')
    monkeypatch.setattr(snapshot, 'urlopen', fail)
    monkeypatch.setattr(snapshot.time, 'sleep', delays.append)
    assert main(['snapshot', 'pin', TARGET]) == 2
    err = capsys.readouterr().err
    assert 'recorded timeout' in err and '4 attempts' in err and 'Traceback' not in err
    assert len(calls) == 4 and delays == [1, 2, 4]


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://example.org/space here', 'http://', 'ftp://example.org/a'])
def test_reject_invalid_target(url, monkeypatch, capsys):
    from timecheck import snapshot
    monkeypatch.setattr(snapshot, 'urlopen', lambda *a, **k: pytest.fail('invalid URL fetched'))
    assert main(['snapshot', 'pin', url]) == 2


def test_wrong_target_capture_is_refused(monkeypatch, capsys):
    from timecheck import snapshot
    def response(request, timeout):
        if '/save/' in request.full_url:
            return Response(b'', headers={'Content-Location': '/web/20261008120000/https://other.org/'})
        return Response(b'{"archived_snapshots": {}}')
    monkeypatch.setattr(snapshot, 'urlopen', response)
    assert main(['snapshot', 'pin', TARGET]) == 2
    assert 'capture' in capsys.readouterr().err.lower()


@pytest.mark.parametrize('payload,headers,expected', [
    (b'%PDF-1.4 synthetic test bytes', {}, 'pdf_text'),
    (b'Synthetic text only', {'Content-Type': 'text/plain'}, 'text'),
    (b'fake image', {'Content-Type': 'image/png'}, 'image_scan'),
])
def test_content_type_guess(payload, headers, expected):
    from timecheck.snapshot import _guess
    assert _guess(payload, headers, TARGET) == expected


def test_gzip_raw_hash_and_retry_recovery(monkeypatch, capsys):
    import gzip
    from timecheck import snapshot
    raw = gzip.compress(b'<html>Project-authored synthetic archive.</html>', mtime=0)
    calls, delays = [], []
    def recorded(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise TimeoutError('first recorded save attempt')
        if '/save/' in request.full_url:
            return Response(b'', headers={'Location': CAPTURE})
        return Response(raw, headers={'Content-Type': 'application/octet-stream'}, url=PINNED)
    monkeypatch.setattr(snapshot, 'urlopen', recorded)
    monkeypatch.setattr(snapshot.time, 'sleep', delays.append)
    assert main(['snapshot', 'pin', TARGET]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['snapshot_sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['content_type'] == 'html'
    assert len(calls) == 3 and delays == [1]


def test_nonraw_download_redirect_rejected(monkeypatch, capsys):
    from timecheck import snapshot
    monkeypatch.setattr(snapshot, 'urlopen', lambda *a, **k: Response(b'<html>Replay toolbar</html>', headers={'Location': CAPTURE}))
    assert main(['snapshot', 'pin', TARGET]) == 2
    assert 'id_ capture' in capsys.readouterr().err


@pytest.mark.parametrize('candidate', [
    'https://evil.example/web/20261008120000/https://example.org/specification?lang=en&edition=2',
    '/web/20269908120000/https://example.org/specification?lang=en&edition=2',
    '/web/20261008120000/https://other.org/',
])
def test_invalid_archive_resolution(candidate):
    from timecheck.snapshot import _pinned
    assert _pinned(candidate, TARGET) is None


@pytest.mark.parametrize('resolved', [
    'https://web.archive.org/web/20261008120000/https://example.org/id_/specification',
    'http://web.archive.org/web/20261008120000id_/https://example.org/id_/specification',
])
def test_target_id_substring_cannot_disguise_replay(monkeypatch, capsys, resolved):
    from timecheck import snapshot
    target = 'https://example.org/id_/specification'
    capture = 'https://web.archive.org/web/20261008120000/' + target
    def response(request, timeout):
        if '/save/' in request.full_url:
            return Response(b'', headers={'Location': capture})
        return Response(b'<html>Replay toolbar</html>', url=resolved)
    monkeypatch.setattr(snapshot, 'urlopen', response)
    assert main(['snapshot', 'pin', target]) == 2
    assert 'id_ capture' in capsys.readouterr().err
