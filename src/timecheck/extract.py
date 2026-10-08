"""Versioned HTML, plain text and digital PDF extraction. No OCR."""
from html.parser import HTMLParser
from io import BytesIO
from pypdf import PdfReader
import re
from .normalize import normalize

EXTRACTOR_VERSION = 2
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


def extract(raw: bytes, content_type: str, charset: str | None = None) -> str:
    if content_type == 'pdf_text':
        try:
            reader = PdfReader(BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise ValueError('encrypted PDF')
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
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
