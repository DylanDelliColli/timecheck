"""Recorded transport responses and real build/SQLite regressions, no external network."""
import gzip
import hashlib
import json
import sqlite3
from urllib.error import HTTPError, URLError

import pytest
import zstandard

from timecheck.build import build
from timecheck.evidence import verify_evidence
from test_evidence_transport import Response, inputs
from test_integration import dataset, SNAPSHOTS


@pytest.mark.parametrize('failure', [429, 503, 'refused'])
def test_throttle_backoff_is_jittered_bounded_and_recovers(monkeypatch, failure):
    raw = b'The synthetic specification gives cafe automatic winding.'
    claims, sources = inputs(raw); claims[0]['evidence'][0]['quote'] = raw.decode()
    attempts, delays = [], []
    def fetch(request, timeout):
        attempts.append(request)
        if len(attempts) < 3:
            if failure == 'refused':
                raise URLError(ConnectionRefusedError('Connection refused'))
            raise HTTPError(request.full_url, failure, 'rate limited', {'Retry-After': '120'}, None)
        return Response(raw)
    monkeypatch.setattr('timecheck.evidence.urlopen', fetch)
    monkeypatch.setattr('timecheck.evidence.time.sleep', delays.append)
    assert verify_evidence(claims, sources, strict=True) == ([], [])
    assert len(attempts) == 3
    assert len(delays) == 2 and all(5 <= d <= 60 for d in delays)
    assert attempts[0].get_header('Accept-encoding') == 'identity'


@pytest.mark.parametrize('encoding', ['identity', 'gzip', 'zstd'])
def test_wayback_200_error_body_is_unavailable_not_hash_mismatch(monkeypatch, encoding, capsys):
    raw = b'<html><title>Wayback Machine</title><h2>The Wayback Machine has not archived that URL.</h2></html>'
    if encoding == 'gzip': raw = gzip.compress(raw)
    if encoding == 'zstd': raw = zstandard.ZstdCompressor().compress(raw)
    claims, sources = inputs(b'expected pinned bytes')
    def fetch(*a, **k):
        response = Response(raw); response.status = 200
        response.headers['Content-Encoding'] = encoding
        return response
    monkeypatch.setattr('timecheck.evidence.urlopen', fetch)
    monkeypatch.setattr('timecheck.evidence.time.sleep', lambda _: None)
    errors, warnings = verify_evidence(claims, sources, strict=True)
    assert not warnings and errors[0]['class'] == 'snapshot_unavailable'
    diagnostics = errors[0]['transport']
    assert diagnostics['http_status'] == 200 and diagnostics['content_encoding'] == encoding
    assert diagnostics['archive_url'] == sources['source:example']['archive_url']
    assert diagnostics['first_bytes_hex'] == raw[:32].hex()
    assert 'ev-aaaaaaaaaa' in capsys.readouterr().err


@pytest.mark.parametrize('encoding', ['gzip', 'zstd'])
def test_hash_mismatch_reports_encoding_variant_without_accepting(monkeypatch, encoding):
    raw = b'The synthetic specification gives cafe automatic winding.'
    packed = gzip.compress(raw) if encoding == 'gzip' else zstandard.ZstdCompressor().compress(raw)
    claims, sources = inputs(raw)
    monkeypatch.setattr('timecheck.evidence.urlopen', lambda *a, **k: Response(packed))
    errors, _ = verify_evidence(claims, sources, strict=True)
    assert errors[0]['class'] == 'snapshot_hash_mismatch'
    assert errors[0]['transport']['decoded_sha256'] == hashlib.sha256(raw).hexdigest()
    assert errors[0]['transport']['encoding_variant_of_pin'] is True
    assert errors[0]['transport']['representation_encoding'] == encoding


@pytest.mark.parametrize('streaming', [False, True])
def test_zstd_raw_hash_real_build_and_sqlite(dataset, tmp_path, streaming):
    raw = next(SNAPSHOTS.iterdir()).read_bytes()
    packed = zstandard.ZstdCompressor(write_content_size=not streaming).compress(raw)
    sha = hashlib.sha256(packed).hexdigest(); snaps = tmp_path / 'encoded'; snaps.mkdir()
    (snaps / (sha + '.bin')).write_bytes(packed)
    path = dataset / 'sources/example.json'; doc = json.loads(path.read_text())
    doc['snapshot_sha256'] = sha; path.write_text(json.dumps(doc))
    code, report = build(data_dir=dataset, snapshot_dir=snaps, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 0, report['errors']
    assert set(report['evidence_verification'].values()) == {'verified'}
    with sqlite3.connect(tmp_path / 'graph.sqlite') as db:
        assert db.execute('SELECT COUNT(*) FROM v_evidence').fetchone()[0] == 23
        assert db.execute('SELECT DISTINCT snapshot_sha256 FROM source').fetchall() == [(sha,)]


def test_evidence_id_selection_marks_other_items_unchecked(dataset, tmp_path):
    claim = json.loads((dataset / 'references/alpha.json').read_text())['claims'][1]
    ident = claim['evidence'][0]['id']
    code, report = build(data_dir=dataset, snapshot_dir=SNAPSHOTS, strict=True,
                         evidence_ids={ident}, out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 0, report['errors']
    assert report['evidence_verification'][ident] == 'verified'
    assert list(report['evidence_verification'].values()).count('verified') == 1
    with sqlite3.connect(tmp_path / 'graph.sqlite') as db:
        assert db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0] == 23


def test_distinct_requests_are_serial_and_spaced(monkeypatch):
    raw = b'The synthetic specification gives cafe automatic winding.'
    claims, sources = inputs(raw); claims[0]['evidence'][0]['quote'] = raw.decode()
    from copy import deepcopy
    claims.append(deepcopy(claims[0])); claims[1]['evidence'][0].update(id='ev-bbbbbbbbbb', source='source:other')
    sources['source:other'] = dict(sources['source:example'], archive_url=sources['source:example']['archive_url'] + '/other')
    now, starts = [0.0], []
    def sleep(delay): now[0] += delay
    def fetch(*a, **k): starts.append(now[0]); return Response(raw)
    monkeypatch.setattr('timecheck.evidence.time.monotonic', lambda: now[0])
    monkeypatch.setattr('timecheck.evidence.time.sleep', sleep)
    monkeypatch.setattr('timecheck.evidence.urlopen', fetch)
    assert verify_evidence(claims, sources, strict=True) == ([], [])
    assert starts == [0, 1]


@pytest.mark.parametrize('variant', ['truncated', 'invalid'])
def test_corrupt_zstd_reports_decode_failure_not_quote_success(tmp_path, variant):
    raw = b'The synthetic specification gives cafe automatic winding.'
    packed = zstandard.ZstdCompressor().compress(raw)
    packed = packed[:-1] if variant == 'truncated' else b'\x28\xb5\x2f\xfdinvalid'
    claims, sources = inputs(packed); claims[0]['evidence'][0]['quote'] = raw.decode()
    (tmp_path / (sources['source:example']['snapshot_sha256'] + '.bin')).write_bytes(packed)
    errors, warnings = verify_evidence(claims, sources, snapshot_dir=tmp_path, strict=True)
    assert not warnings and errors[0]['class'] == 'snapshot_unavailable'
    assert 'zstd decode failed' in errors[0]['message']


@pytest.mark.parametrize('body,media,content_type', [
    (b"<html><title>Wayback Machine</title><p>Hrm. Wayback Machine doesn't have that page archived.</p></html>", 'text/html', 'html'),
    (b'<html><title>  Wayback&nbsp;Machine </title><p>An unfamiliar archive status.</p></html>', 'text/html', 'html'),
    (b'<html><title>Archive error</title><p>This page is not available</p></html>', 'text/html', 'html'),
    (b'<html><title>Archive error</title><p>Hrm.</p></html>', 'text/html', 'html'),
    (b'<html><title>Archive error</title><p>A generic archive error body.</p></html>', 'text/html; charset=utf-8', 'pdf_text'),
])
@pytest.mark.parametrize('strict', [False, True])
def test_recorded_placeholder_variants_retry_and_remain_unavailable(monkeypatch, body, media, content_type, strict):
    claims, sources = inputs(b'expected original capture bytes'); sources['source:example']['content_type'] = content_type
    attempts, delays = [], []
    def fetch(*a, **k):
        attempts.append(1); response = Response(body); response.status = 200
        response.headers['Content-Type'] = media
        return response
    monkeypatch.setattr('timecheck.evidence.urlopen', fetch)
    monkeypatch.setattr('timecheck.evidence.time.sleep', delays.append)
    errors, warnings = verify_evidence(claims, sources, strict=strict)
    problems = errors if strict else warnings
    assert len(attempts) == 4 and len(delays) == 3
    assert all(5 <= d <= 60 for d in delays)
    assert len(problems) == 1 and problems[0]['class'] == 'snapshot_unavailable'
    assert problems[0]['transport']['http_status'] == 200
    assert not (warnings if strict else errors)


def test_real_html_with_wayback_title_literal_in_script_is_not_placeholder(monkeypatch):
    raw = (b'<html><title>Synthetic archived article</title><script>const example = "<title>Wayback Machine</title>";</script>'
           b'<p>The synthetic specification gives cafe automatic winding.</p></html>')
    claims, sources = inputs(raw); sources['source:example']['content_type'] = 'html'
    claims[0]['evidence'][0]['quote'] = 'The synthetic specification gives cafe automatic winding.'
    attempts = []
    def fetch(*a, **k):
        attempts.append(1); response = Response(raw); response.headers['Content-Type'] = 'text/html'; return response
    monkeypatch.setattr('timecheck.evidence.urlopen', fetch)
    monkeypatch.setattr('timecheck.evidence.time.sleep', lambda _: None)
    assert verify_evidence(claims, sources, strict=True) == ([], [])
    assert len(attempts) == 1


def test_placeholder_title_attribute_can_contain_greater_than(monkeypatch):
    raw = b'<html><title data-example="a>b">Wayback Machine</title><p>Unfamiliar status text.</p></html>'
    claims, sources = inputs(b'expected original capture'); sources['source:example']['content_type'] = 'html'
    attempts = []
    def fetch(*a, **k):
        attempts.append(1); response = Response(raw); response.headers['Content-Type'] = 'text/html'; return response
    monkeypatch.setattr('timecheck.evidence.urlopen', fetch)
    monkeypatch.setattr('timecheck.evidence.time.sleep', lambda _: None)
    errors, warnings = verify_evidence(claims, sources, strict=True)
    assert len(attempts) == 4 and not warnings and errors[0]['class'] == 'snapshot_unavailable'


@pytest.mark.parametrize('media', ['application/pdf', None])
def test_valid_pdf_with_html_comment_is_not_a_placeholder(monkeypatch, media):
    from test_pdf_evidence import pdf_bytes, TEXT
    from timecheck.extract import extract
    raw = pdf_bytes().replace(b'startxref', b'% <title>Wayback Machine</title> Hrm.\nstartxref')
    assert extract(raw, 'pdf_text') == TEXT
    claims, sources = inputs(raw); sources['source:example']['content_type'] = 'pdf_text'
    claims[0]['evidence'][0]['quote'] = TEXT; attempts = []
    def fetch(*a, **k):
        attempts.append(1); response = Response(raw)
        if media: response.headers['Content-Type'] = media
        return response
    monkeypatch.setattr('timecheck.evidence.urlopen', fetch)
    monkeypatch.setattr('timecheck.evidence.time.sleep', lambda _: None)
    assert verify_evidence(claims, sources, strict=True) == ([], [])
    assert len(attempts) == 1
