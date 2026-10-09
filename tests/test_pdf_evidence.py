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
    ('aababaabbabaabbabaab', 'aabababbbaaaabbabaab', True),
    ('aababaabbabaabbabaab', 'prefix aabababbbaaaabbabaab suffix', True),
    ('abcdefghijklmnopqrst', 'abcdghijefklmnopqrst', False),  # moved ef: SM 0.90, Levenshtein 0.80
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
    path = data / 'calibers/synthetic.json'
    before = path.read_bytes()
    with pytest.raises(ValueError, match='PDF evidence requires human attestation'):
        verify_status(by='independent-review / chief', data_dir=data, report=tmp_path / 'report.json')
    assert path.read_bytes() == before
    assert json.loads(before)['claims'][0]['status'] == 'proposed'
    assert report['pending_attestations'] == [{
        'claim_id': 'clm-aaaaaaaaaa', 'evidence_id': 'ev-aaaaaaaaaa',
        'source_id': 'source:synthetic', 'content_type': 'pdf_text',
        'location': str(path)}]


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


def embedded_cff_pdf():
    """Project-authored minimal CFF: byte A maps to two, B maps to five.

    FontBuilder generated this tiny font program (glyphs .notdef/two/five,
    600-unit empty outlines, explicit CFF encoding). The PDF is generated here;
    no real font or source snapshot bytes are included.
    """
    from base64 import b64decode
    from pypdf.generic import ArrayObject, NumberObject
    cff = b64decode('AQAEAQABAQENU3ludGhldGljQ0ZGAAEBARP4GwL4HAP4GATVD9oQi+4S3hEAAgEBDhdTeW50aGV0aWMgQ0ZGU3ludGhldGljAAAAABMAFgEBQQEAAwEBBAcK+OwO+OwO+OwO')
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    program = DecodedStreamObject(); program.set_data(cff)
    program[NameObject('/Subtype')] = NameObject('/Type1C')
    descriptor = DictionaryObject({NameObject('/Type'): NameObject('/FontDescriptor'),
                                   NameObject('/FontName'): NameObject('/SyntheticCFF'),
                                   NameObject('/Flags'): NumberObject(4),
                                   NameObject('/FontFile3'): writer._add_object(program)})
    cff_font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                NameObject('/Subtype'): NameObject('/Type1'),
                                NameObject('/BaseFont'): NameObject('/SyntheticCFF'),
                                NameObject('/Encoding'): NameObject('/StandardEncoding'),
                                NameObject('/FirstChar'): NumberObject(65),
                                NameObject('/LastChar'): NumberObject(66),
                                NameObject('/Widths'): ArrayObject([NumberObject(600), NumberObject(600)]),
                                NameObject('/FontDescriptor'): writer._add_object(descriptor)})
    plain_font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                  NameObject('/Subtype'): NameObject('/Type1'),
                                  NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/F1'): writer._add_object(plain_font), NameObject('/F2'): writer._add_object(cff_font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 36 720 Td (Synthetic CFF caliber has ) Tj /F2 12 Tf (AB) Tj /F1 12 Tf ( jewels documented.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output)
    return output.getvalue()


def test_embedded_cff_numeric_text_and_real_build(tmp_path, caplog):
    expected = 'Synthetic CFF caliber has 25 jewels documented.'
    raw = embedded_cff_pdf()
    assert extract(raw, 'pdf_text') == expected
    data, snaps = dataset(tmp_path, 'exact', expected)
    sha = hashlib.sha256(raw).hexdigest()
    (snaps / (sha + '.bin')).write_bytes(raw)
    path = data / 'sources/synthetic.json'
    doc = json.loads(path.read_text()); doc['snapshot_sha256'] = sha
    path.write_text(json.dumps(doc))
    code, report = build(data_dir=data, snapshot_dir=snaps, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 0, report['errors']
    assert report['evidence_verification']['ev-aaaaaaaaaa'] == 'verified'
    assert 'fontTools is required' not in caplog.text
    with sqlite3.connect(tmp_path / 'graph.sqlite') as db:
        assert db.execute('SELECT quote FROM v_evidence_all').fetchone()[0] == expected


def remapped_cff_pdf(differences=None, *, cff_digit_conflict=False, form=False):
    """Reserialize the review's AB->52 explicit-encoding reproduction."""
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject, NumberObject
    reader = PdfReader(BytesIO(embedded_cff_pdf()))
    font = reader.pages[0]['/Resources']['/Font']['/F2'].get_object()
    if differences is not None:
        font[NameObject('/Encoding')] = DictionaryObject({
            NameObject('/BaseEncoding'): NameObject('/StandardEncoding'),
            NameObject('/Differences'): ArrayObject([
                NumberObject(x) if isinstance(x, int) else NameObject(x) for x in differences])})
    if cff_digit_conflict:
        from fontTools.cffLib import CFFFontSet
        stream = font['/FontDescriptor']['/FontFile3']
        cff = CFFFontSet(); cff.decompile(BytesIO(stream.get_data()), None)
        cff.topDictIndex[0].Encoding[66] = '.notdef'
        cff.topDictIndex[0].Encoding[50] = 'five'
        from types import SimpleNamespace
        raw = BytesIO(); cff.compile(raw, SimpleNamespace(recalcBBoxes=False))
        stream.set_data(raw.getvalue())
    if form:
        page = reader.pages[0]
        fonts = page['/Resources']['/Font']
        nested = DecodedStreamObject()
        nested.set_data(b'BT /F2 12 Tf 36 720 Td (AB) Tj ET')
        nested[NameObject('/Subtype')] = NameObject('/Form')
        nested[NameObject('/BBox')] = ArrayObject([NumberObject(x) for x in (0, 0, 612, 792)])
        nested[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F2'): fonts.raw_get('/F2')})})
        page['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/Nested'): nested})
        del fonts['/F2']
        page['/Contents'].set_data(b'/Nested Do')
    writer = PdfWriter(); writer.append(reader)
    raw = BytesIO(); writer.write(raw)
    return raw.getvalue()


@pytest.mark.parametrize('has_fonttools', [True, False])
@pytest.mark.parametrize('differences', [
    [65, '/five', '/two'], [65, '/uni0035', '/uni0032'],
    [65, '/u0035', '/u0032'], [65, '/five.alt', '/two.alt'],
])
def test_pdf_digit_remap_is_unreliable_independent_of_pypdf_fonttools_flag(monkeypatch, has_fonttools, differences):
    from pypdf import _font
    monkeypatch.setattr(_font, 'HAS_FONTTOOLS', has_fonttools)
    with pytest.raises(ValueError, match='SyntheticCFF'):
        extract(remapped_cff_pdf(differences), 'pdf_text')


@pytest.mark.parametrize('quote', [
    'Synthetic CFF caliber has 25 jewels documented.',
    'Synthetic CFF caliber has 52 jewels documented.',
])
@pytest.mark.parametrize('mode', ['exact', 'fuzzy'])
def test_real_build_never_verifies_ambiguous_cff_digits(tmp_path, quote, mode):
    raw = remapped_cff_pdf([65, '/five', '/two'])
    data, snaps = dataset(tmp_path, mode, quote)
    sha = hashlib.sha256(raw).hexdigest()
    (snaps / (sha + '.bin')).write_bytes(raw)
    path = data / 'sources/synthetic.json'
    doc = json.loads(path.read_text()); doc['snapshot_sha256'] = sha
    path.write_text(json.dumps(doc))
    code, report = build(data_dir=data, snapshot_dir=snaps, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 2
    assert report['errors_by_class'] == {'unsupported_content_type': 1}
    assert 'SyntheticCFF' in report['errors'][0]['message']
    assert report['evidence_verification']['ev-aaaaaaaaaa'] == 'error'
    assert not (tmp_path / 'graph.sqlite').exists()


def test_explicit_encoding_conflict_at_digit_code_is_unreliable():
    with pytest.raises(ValueError, match='SyntheticCFF'):
        extract(remapped_cff_pdf(cff_digit_conflict=True), 'pdf_text')


def test_nested_form_digit_remap_is_unreliable():
    with pytest.raises(ValueError, match='SyntheticCFF'):
        extract(remapped_cff_pdf([65, '/five', '/two'], form=True), 'pdf_text')


def test_correct_explicit_digit_encoding_remains_supported():
    assert extract(remapped_cff_pdf([50, '/two', 53, '/five']), 'pdf_text') == 'Synthetic CFF caliber has 25 jewels documented.'


def to_unicode_swapped_pdf(mode='bfchar', cmap_override=None):
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(pdf_bytes()))
    font = reader.pages[0]['/Resources']['/Font']['/F1']
    font[NameObject('/Encoding')] = NameObject('/WinAnsiEncoding')
    stream = DecodedStreamObject()
    if mode == 'bfchar':
        cmap = b'2 beginbfchar\n<32> <0035>\n<35> <0032>\nendbfchar'
    elif mode == 'bfrange':
        cmap = b'2 beginbfrange\n<32> <32> <0035>\n<35> <35> <0032>\nendbfrange'
    else:
        cmap = b'2 beginbfrange\n<32> <32> [<0035>]\n<35> <35> [<0032>]\nendbfrange'
    stream.set_data(cmap_override if cmap_override is not None else cmap)
    font[NameObject('/ToUnicode')] = stream
    writer = PdfWriter(); writer.append(reader)
    out = BytesIO(); writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize('cmap_mode', ['bfchar', 'bfrange', 'array'])
@pytest.mark.parametrize('mode', ['exact', 'fuzzy'])
def test_real_build_refuses_tounicode_digit_swap(tmp_path, cmap_mode, mode):
    raw = to_unicode_swapped_pdf(cmap_mode)
    data, snaps = dataset(tmp_path, mode, TEXT.replace('25', '52'))
    sha = hashlib.sha256(raw).hexdigest()
    (snaps / (sha + '.bin')).write_bytes(raw)
    path = data / 'sources/synthetic.json'
    doc = json.loads(path.read_text()); doc['snapshot_sha256'] = sha
    path.write_text(json.dumps(doc))
    code, report = build(data_dir=data, snapshot_dir=snaps, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 2
    assert report['errors_by_class'] == {'unsupported_content_type': 1}
    assert 'Helvetica' in report['errors'][0]['message']
    assert report['evidence_verification']['ev-aaaaaaaaaa'] == 'error'
    assert not (tmp_path / 'graph.sqlite').exists()


@pytest.mark.parametrize('mapping', [b'<32> <0041>', b'<41> <0032>', b'<32> <00320035>'])
def test_simple_font_tounicode_cannot_add_or_remove_digits(mapping):
    with pytest.raises(ValueError, match='Helvetica'):
        extract(to_unicode_swapped_pdf(cmap_override=b'1 beginbfchar\n' + mapping + b'\nendbfchar'), 'pdf_text')


def test_simple_font_identity_tounicode_digits_remain_supported():
    raw = to_unicode_swapped_pdf(cmap_override=b'2 beginbfchar\n<32> <0032>\n<35> <0035>\nendbfchar')
    assert extract(raw, 'pdf_text') == TEXT


def type0_pdf(*, identity=True, digit_text=True, to_unicode=True, form=False):
    """Generate Type0 and actual embedded TrueType, with/without identity tables."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont
    from pypdf.generic import ArrayObject, NumberObject, TextStringObject
    names = ['.notdef', 'two', 'five', 'a', 'b', 'c']
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({50: 'two', 53: 'five', 97: 'a', 98: 'b', 99: 'c'})
    fb.setupGlyf({name: TTGlyphPen(None).glyph() for name in names})
    fb.setupHorizontalMetrics({name: (600, 0) for name in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({'familyName': 'Synthetic CID', 'styleName': 'Regular',
                       'fullName': 'Synthetic CID', 'psName': 'SyntheticCID'})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    fb.setupPost(keepGlyphNames=identity)
    fb.setupMaxp()
    if not identity:
        del fb.font['cmap']
    program_raw = BytesIO(); fb.font.save(program_raw)
    # Assert the fixture's distinction, not merely a renamed generic font.
    check = TTFont(BytesIO(program_raw.getvalue()))
    assert (check['post'].formatType == 2.0 and 'cmap' in check) if identity else (check['post'].formatType == 3.0 and 'cmap' not in check)
    writer = PdfWriter(); page = writer.add_blank_page(width=612, height=792)
    program = DecodedStreamObject(); program.set_data(program_raw.getvalue())
    descriptor = DictionaryObject({NameObject('/Type'): NameObject('/FontDescriptor'),
                                   NameObject('/FontName'): NameObject('/SyntheticCID'),
                                   NameObject('/Flags'): NumberObject(32),
                                   NameObject('/FontFile2'): writer._add_object(program)})
    descendant = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                  NameObject('/Subtype'): NameObject('/CIDFontType2'),
                                  NameObject('/BaseFont'): NameObject('/SyntheticCID'),
                                  NameObject('/FontDescriptor'): writer._add_object(descriptor),
                                  NameObject('/CIDToGIDMap'): NameObject('/Identity'),
                                  NameObject('/CIDSystemInfo'): DictionaryObject({
                                      NameObject('/Registry'): TextStringObject('Adobe'),
                                      NameObject('/Ordering'): TextStringObject('Identity'),
                                      NameObject('/Supplement'): NumberObject(0)})})
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type0'),
                             NameObject('/BaseFont'): NameObject('/SyntheticCID'),
                             NameObject('/Encoding'): NameObject('/Identity-H'),
                             NameObject('/DescendantFonts'): ArrayObject([writer._add_object(descendant)])})
    if to_unicode:
        cmap = DecodedStreamObject()
        # Includes unused digit entries when showing abc: rejection must depend
        # on emitted Type0 text, rather than the existence of an unused mapping.
        cmap.set_data(b'5 beginbfchar\n<0001> <0032>\n<0002> <0035>\n<0003> <0061>\n<0004> <0062>\n<0005> <0063>\nendbfchar')
        font[NameObject('/ToUnicode')] = writer._add_object(cmap)
    fonts = DictionaryObject({NameObject('/F2'): writer._add_object(font)})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): fonts})
    codes = b'00010002' if digit_text and to_unicode else b'00320035' if digit_text else b'000300040005'
    content = DecodedStreamObject(); content.set_data(b'BT /F2 12 Tf 36 720 Td <' + codes + b'> Tj ET')
    if form:
        content[NameObject('/Subtype')] = NameObject('/Form')
        content[NameObject('/BBox')] = ArrayObject([NumberObject(x) for x in (0, 0, 612, 792)])
        content[NameObject('/Resources')] = page['/Resources']
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({
            NameObject('/Nested'): writer._add_object(content)})})
        wrapper = DecodedStreamObject(); wrapper.set_data(b'/Nested Do')
        content = wrapper
    page[NameObject('/Contents')] = writer._add_object(content)
    out = BytesIO(); writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize('identity', [True, False])
@pytest.mark.parametrize('to_unicode,form', [(True, False), (False, False), (False, True)])
def test_v1_fallback_refuses_type0_digit_text(identity, to_unicode, form):
    with pytest.raises(ValueError, match='SyntheticCID'):
        extract(type0_pdf(identity=identity, to_unicode=to_unicode, form=form), 'pdf_text')


def test_type0_nondigit_text_is_supported_even_with_unused_digit_maps():
    assert extract(type0_pdf(digit_text=False), 'pdf_text') == 'abc'


@pytest.mark.parametrize('mode', ['exact', 'fuzzy'])
def test_real_build_reports_type0_digit_refusal(tmp_path, mode):
    raw = type0_pdf(identity=False)
    data, snaps = dataset(tmp_path, mode, TEXT)
    sha = hashlib.sha256(raw).hexdigest()
    (snaps / (sha + '.bin')).write_bytes(raw)
    path = data / 'sources/synthetic.json'
    doc = json.loads(path.read_text()); doc['snapshot_sha256'] = sha
    path.write_text(json.dumps(doc))
    code, report = build(data_dir=data, snapshot_dir=snaps, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 2
    assert report['errors_by_class'] == {'unsupported_content_type': 1}
    assert 'SyntheticCID' in report['errors'][0]['message']
    assert report['evidence_verification']['ev-aaaaaaaaaa'] == 'error'
    assert not (tmp_path / 'graph.sqlite').exists()


def review_bypass_pdf(route):
    """Review reproductions remain advisory even when the guards miss them."""
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject, NumberObject
    if route == 'differences_nondigit':
        reader = PdfReader(BytesIO(to_unicode_swapped_pdf(
            cmap_override=b'2 beginbfchar\n<32> <0032>\n<35> <0035>\nendbfchar')))
        font = reader.pages[0]['/Resources']['/Font']['/F1']
        font[NameObject('/Encoding')] = DictionaryObject({
            NameObject('/BaseEncoding'): NameObject('/WinAnsiEncoding'),
            NameObject('/Differences'): ArrayObject([NumberObject(50), NameObject('/A')])})
        # The font displays A5, but identity ToUnicode extracts 25.
    else:
        reader = PdfReader(BytesIO(type0_pdf(identity=True)))
        page = reader.pages[0]
        font = page['/Resources']['/Font']['/F2']
        font['/ToUnicode'].set_data(b'2 beginbfchar\n<0001> <0035>\n<0002> <0032>\nendbfchar')
        simple = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                   NameObject('/Subtype'): NameObject('/Type1'),
                                   NameObject('/BaseFont'): NameObject('/Helvetica')})
        page['/Resources']['/Font'][NameObject('/F1')] = simple
        stream = DecodedStreamObject()
        # Restoring graphics state before ET makes pypdf flush Type0 text under
        # the previously selected Helvetica. Glyph ids 1/2 are two/five, yet
        # ToUnicode emits five/two and the visitor sees a simple font.
        stream.set_data(b'BT /F1 12 Tf 36 720 Td (Synthetic caliber has ) Tj ET '
                        b'q BT /F2 12 Tf 36 700 Td <00010002> Tj Q ET '
                        b'BT /F1 12 Tf 36 680 Td ( jewels documented.) Tj ET')
        page[NameObject('/Contents')] = stream
    writer = PdfWriter(); writer.append(reader)
    out = BytesIO(); writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize('route', ['graphics_state_flush', 'differences_nondigit'])
@pytest.mark.parametrize('mode', ['exact', 'fuzzy'])
def test_pdf_digit_bypass_match_never_authorizes_promotion(tmp_path, route, mode):
    raw = review_bypass_pdf(route)
    quote = extract(raw, 'pdf_text')
    assert ('52' if route == 'graphics_state_flush' else '25') in quote
    data, snaps = dataset(tmp_path, mode, quote)
    sha = hashlib.sha256(raw).hexdigest()
    (snaps / (sha + '.bin')).write_bytes(raw)
    source_path = data / 'sources/synthetic.json'
    source = json.loads(source_path.read_text()); source['snapshot_sha256'] = sha
    source_path.write_text(json.dumps(source))
    code, report = build(data_dir=data, snapshot_dir=snaps, strict=True,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 0, report['errors']
    assert report['evidence_verification']['ev-aaaaaaaaaa'] == 'verified'
    path = data / 'calibers/synthetic.json'
    before = path.read_bytes()
    with pytest.raises(ValueError, match='PDF evidence requires human attestation'):
        verify_status(by='independent-review / chief', data_dir=data, report=tmp_path / 'report.json')
    assert path.read_bytes() == before
    assert 'review' not in json.loads(before)['claims'][0]
    assert report['pending_attestations'][0]['evidence_id'] == 'ev-aaaaaaaaaa'
    assert report['pending_attestations'][0]['source_id'] == 'source:synthetic'


@pytest.mark.parametrize('no_evidence', [False, True])
def test_pdf_mixed_evidence_refuses_atomically_and_can_be_excluded(tmp_path, no_evidence):
    from copy import deepcopy
    data, snaps = dataset(tmp_path, 'exact', TEXT)
    text = TEXT.encode(); sha = hashlib.sha256(text).hexdigest()
    (snaps / (sha + '.bin')).write_bytes(text)
    source = json.loads((data / 'sources/synthetic.json').read_text())
    source.update(id='source:text', content_type='text', snapshot_sha256=sha)
    (data / 'sources/text.json').write_text(json.dumps(source))
    path = data / 'calibers/synthetic.json'
    doc = json.loads(path.read_text())
    pdf_claim = doc['claims'][0]
    text_evidence = dict(pdf_claim['evidence'][0], id='ev-bbbbbbbbbb', source='source:text')
    html_claim = deepcopy(pdf_claim)
    html_claim.update(id='clm-bbbbbbbbbb', evidence=[text_evidence])
    pdf_claim['evidence'].append(dict(text_evidence, id='ev-cccccccccc'))
    doc['claims'].insert(0, html_claim)
    path.write_text(json.dumps(doc)); before = path.read_bytes()
    code, report = build(data_dir=data, snapshot_dir=snaps, strict=True, no_evidence=no_evidence,
                         out=tmp_path / 'graph.sqlite', report=tmp_path / 'report.json')
    assert code == 0, report['errors']
    with pytest.raises(ValueError, match='PDF evidence requires human attestation'):
        verify_status(by='review / chief', data_dir=data, report=tmp_path / 'report.json')
    assert path.read_bytes() == before
    assert report['pending_attestations'] == [{
        'claim_id': 'clm-aaaaaaaaaa', 'evidence_id': 'ev-aaaaaaaaaa',
        'source_id': 'source:synthetic', 'content_type': 'pdf_text', 'location': str(path)}]
    result = verify_status(by='review / chief', data_dir=data, report=tmp_path / 'report.json',
                           exclude=['clm-aaaaaaaaaa'])
    assert result['claim_ids'] == ([] if no_evidence else ['clm-bbbbbbbbbb'])
    updated = json.loads(path.read_text())['claims']
    assert updated[1]['status'] == 'proposed' and 'review' not in updated[1]
