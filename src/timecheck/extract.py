"""Versioned HTML, plain text and digital PDF extraction. No OCR."""
from html.parser import HTMLParser
from io import BytesIO
from pypdf import PdfReader
from pypdf._codecs import adobe_glyphs, charset_encoding
import re
from .normalize import normalize

EXTRACTOR_VERSION = 3
PDF_DIGIT_GUARD_VERSION = 1
BLOCKS = set('address article aside blockquote br dd div dl dt fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section table tbody td th thead tr ul'.split())
DROP = {'script', 'style', 'noscript', 'template'}


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in DROP:
            self.hidden.append(tag)
        if not self.hidden and tag in BLOCKS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _resolved(obj):
    return obj.get_object() if hasattr(obj, 'get_object') else obj


def _glyph_text(name):
    """Adobe/Unicode glyph names, including suffixes and compound names."""
    name = str(name).removeprefix('/').split('.', 1)[0]
    if '_' in name:
        parts = [_glyph_text(part) for part in name.split('_')]
        return ''.join(parts) if all(part is not None for part in parts) else None
    if '/' + name in adobe_glyphs:
        return adobe_glyphs['/' + name]
    if re.fullmatch(r'uni(?:[0-9A-Fa-f]{4})+', name):
        return ''.join(chr(int(name[i:i + 4], 16)) for i in range(3, len(name), 4))
    if re.fullmatch(r'u[0-9A-Fa-f]{4,6}', name):
        try:
            return chr(int(name[1:], 16))
        except ValueError:
            return None
    return None


def _check_font_digits(font, name):
    label = f'{name} ({font.get("/BaseFont", "unnamed font")})'
    explicit = _resolved(font.get('/Encoding'))
    encoding = None
    if explicit is not None:
        base = explicit.get('/BaseEncoding', '/StandardEncoding') if isinstance(explicit, dict) else explicit
        if base in charset_encoding:
            encoding = dict(enumerate(charset_encoding[base]))
        if isinstance(explicit, dict) and '/Differences' in explicit:
            differences = _resolved(explicit['/Differences'])
            if not isinstance(differences, list):
                raise ValueError(f'Unreliable PDF font {label}: invalid Encoding Differences')
            code = 0
            for entry in differences:
                if isinstance(entry, int):
                    code = entry
                    continue
                text = _glyph_text(entry)
                normalized = normalize(text) if text is not None else ''
                if any(char.isdigit() for char in normalized):
                    if len(normalized) != 1 or normalized not in '0123456789' or code != ord(normalized):
                        raise ValueError(f'Unreliable PDF font {label}: Differences remaps digit glyph {entry} to code {code}')
                if encoding is not None:
                    encoding[code] = text
                code += 1
    descriptor = _resolved(font.get('/FontDescriptor'))
    program = _resolved(descriptor.get('/FontFile3')) if isinstance(descriptor, dict) else None
    if explicit is None or program is None or program.get('/Subtype') != '/Type1C':
        return
    # Inspect CFF directly, independent of pypdf's optional HAS_FONTTOOLS flag:
    # pypdf may discard explicit encoding entries in favor of its CFF map.
    from fontTools.cffLib import CFFFontSet
    try:
        cff = CFFFontSet()
        cff.decompile(BytesIO(program.get_data()), None)
        mapping = cff.topDictIndex[0].Encoding
        if isinstance(mapping, str):
            return  # pypdf derives no override map for predefined CFF encodings.
        for code in range(48, 58):
            if code >= len(mapping) or not mapping[code] or mapping[code] == '.notdef':
                continue
            text = _glyph_text(mapping[code])
            if encoding is None or text is None or encoding.get(code) != text:
                raise ValueError(f'Unreliable PDF font {label}: explicit encoding and CFF mapping disagree at digit code {code}')
    except Exception as exc:
        raise ValueError(f'Cannot safely decode PDF font {label}: {exc}') from exc


def _check_resource_digits(resources, seen_resources, seen_fonts, path='page'):
    resources = _resolved(resources)
    if not isinstance(resources, dict) or id(resources) in seen_resources:
        return
    seen_resources.add(id(resources))
    fonts = _resolved(resources.get('/Font', {}))
    for name, obj in fonts.items():
        font = _resolved(obj)
        if id(font) in seen_fonts:
            continue
        seen_fonts.add(id(font))
        _check_font_digits(font, path + str(name))
        for descendant in _resolved(font.get('/DescendantFonts', [])):
            child = _resolved(descendant)
            _check_font_digits(child, path + str(name) + '/descendant')
    for name, obj in _resolved(resources.get('/XObject', {})).items():
        form = _resolved(obj)
        if form.get('/Subtype') == '/Form':
            _check_resource_digits(form.get('/Resources', resources), seen_resources,
                                   seen_fonts, path + str(name))


def extract(raw: bytes, content_type: str, charset: str | None = None) -> str:
    if content_type == 'pdf_text':
        try:
            reader = PdfReader(BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise ValueError('encrypted PDF')
            seen_resources, seen_fonts, pages = set(), set(), []
            for number, page in enumerate(reader.pages, 1):
                _check_resource_digits(page.get('/Resources', {}), seen_resources,
                                       seen_fonts, f'page {number}')
                pages.append(page.extract_text() or '')
            text = '\n'.join(pages)
            if not normalize(text):
                raise ValueError('PDF has no text layer; scans require manual evidence')
            return normalize(text)
        except Exception as exc:
            raise ValueError('Unsupported PDF text extraction: ' + str(exc)) from exc
    if content_type not in {'html', 'text'}:
        raise ValueError('unsupported_content_type')
    if not charset:
        match = re.search(rb'<meta\b[^>]*charset\s*=\s*[\'\"]?\s*([a-zA-Z0-9_-]+)', raw, re.I)
        charset = match[1].decode('ascii') if match else 'utf-8'
    try:
        text = raw.decode(charset, errors='replace')
    except LookupError:
        text = raw.decode('utf-8', errors='replace')
    if content_type == 'html':
        parser = TextParser()
        parser.feed(text)
        text = ''.join(parser.parts)
    return normalize(text)
