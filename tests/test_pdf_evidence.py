"""Golden digital PDF extraction and real evidence/build composition, no OCR."""
from io import BytesIO
import hashlib
import json
import sqlite3

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from timecheck.build import build
from timecheck.extract import extract
from timecheck.status import verify_status

TEXT = 'Synthetic caliber has 25 jewels and was introduced in 1996. It is automatic.'


def pdf_bytes(text=TEXT):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    if text:
        stream = DecodedStreamObject()
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream.set_data(('BT /F1 12 Tf 36 720 Td (' + escaped + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    out = BytesIO(); writer.write(out)
    return out.getvalue()


def test_pdf_extraction_golden():
    assert extract(pdf_bytes(), 'pdf_text') == TEXT


@pytest.mark.parametrize('quote,content,expected', [
    ('abcdefghijklmnopqrst', 'abcdefghijklmnopqrst', True),
    ('abcdefghijklmnopqrst', 'abXdefghijklmnopqrsY', True),  # ratio exactly 0.90
    ('abcdefghijklmnopqrst', 'abXdefghijYlmnopqrsZ', False),
    (TEXT.replace('automatic', 'automatlc'), TEXT, True),
    (TEXT.replace('25', '26'), TEXT, False),
    (TEXT.replace('1996', '1997'), TEXT, False),
    ('Caliber 25 has synthetic jewels', 'Caliber 125 has synthetic jewels', False),
    ('Synthetic jewels numbered 25', 'Synthetic jewels numbered 250', False),
    ('The caliber 25.5 has 17 jewels', 'The caliber 25.6 has 17 jewels', False),
    ('Synthetic caliber SW200-1 is automatic', 'Synthetic caliber SW300-1 is automatic', False),
    ('The caliber has automatic winding', 'prefix The caliber has automatlc winding suffix', True),
])
def test_pdf_fuzzy_golden(quote, content, expected):
    from timecheck.evidence import fuzzy_match
    assert fuzzy_match(quote, content) is expected


def dataset(tmp_path, mode, quote):
    data, snapshots = tmp_path / 'data', tmp_path / 'snapshots'
    (data / 'calibers').mkdir(parents=True)
    (data / 'sources').mkdir()
    snapshots.mkdir()
    raw = pdf_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    (snapshots / (sha + '.bin')).write_bytes(raw)
    (data / 'sources/synthetic.json').write_text(json.dumps({
        'schema_version': 1, 'id': 'source:synthetic', 'kind': 'source',
        'url': 'https://example.org/synthetic.pdf', 'publisher': 'Project test',
        'trust_tier': 'primary', 'reuse_class': 'open', 'licence': 'CC0-1.0',
        'content_type': 'pdf_text', 'archive_url': 'https://web.archive.org/web/20261008120000id_/https://example.org/synthetic.pdf',
        'snapshot_sha256': sha, 'retrieved_at': '2026-10-08', 'notes': 'Synthetic only'}))
    (data / 'calibers/synthetic.json').write_text(json.dumps({
        'schema_version': 1, 'id': 'caliber:synthetic', 'kind': 'caliber',
        'display_name': 'Synthetic', 'aliases': [], 'claims': [{
            'id': 'clm-aaaaaaaaaa', 'predicate': 'jewels', 'object': {'value': 25, 'unit': 'count'},
            'status': 'proposed', 'contested': False, 'evidence': [{
                'id': 'ev-aaaaaaaaaa', 'source': 'source:synthetic', 'quote': quote,
                'locator': 'Synthetic PDF page 1', 'match_mode': mode}]}]}))
    return data, snapshots


@pytest.mark.parametrize('mode,quote,code', [
    ('exact', TEXT, 0), ('fuzzy', TEXT.replace('automatic', 'automatlc'), 0),
    ('exact', TEXT.replace('automatic', 'automatlc'), 2),
    ('fuzzy', TEXT.replace('1996', '1997'), 2),
])
def test_real_pdf_build_and_review(tmp_path, mode, quote, code):
    data, snaps = dataset(tmp_path, mode, quote)
    result, report = build(data_dir=data, snapshot_dir=snaps, strict=True,
                           out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert result == code, report['errors']
    if code:
        assert report['errors_by_class'] == {'quote_not_found': 1}
        assert report['evidence_verification']['ev-aaaaaaaaaa'] == 'error'
        return
    assert report['evidence_verification']['ev-aaaaaaaaaa'] == 'verified'
    with sqlite3.connect(tmp_path / 'graph.sqlite') as db:
        assert db.execute('SELECT match_mode FROM v_evidence_all').fetchall() == [(mode,)]
    result = verify_status(by='independent-review / chief', data_dir=data, report=tmp_path / 'report.json')
    # The automatic E1 status transition explicitly requires exact verification.
    assert result['count'] == (1 if mode == 'exact' else 0)


@pytest.mark.parametrize('content_type', ['html', 'text', 'image_scan'])
def test_fuzzy_is_reserved_for_pdf(tmp_path, content_type):
    data, snaps = dataset(tmp_path, 'fuzzy', TEXT)
    path = data / 'sources/synthetic.json'
    doc = json.loads(path.read_text()); doc['content_type'] = content_type
    path.write_text(json.dumps(doc))
    code, report = build(data_dir=data, snapshot_dir=snaps, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 2
    assert 'unsupported_content_type' in report['errors_by_class']


@pytest.mark.parametrize('raw', [pdf_bytes(''), b'%PDF-broken'])
def test_pdf_without_text_is_clear_error(tmp_path, raw):
    data, snaps = dataset(tmp_path, 'exact', TEXT)
    sha = hashlib.sha256(raw).hexdigest()
    (snaps / (sha + '.bin')).write_bytes(raw)
    path = data / 'sources/synthetic.json'
    doc = json.loads(path.read_text()); doc['snapshot_sha256'] = sha
    path.write_text(json.dumps(doc))
    code, report = build(data_dir=data, snapshot_dir=snaps, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 2
    assert report['errors_by_class'] == {'unsupported_content_type': 1}
