# Normalization and extraction

`norm_version: 1` applies identically to quotes and extracted snapshots. Exact matching
is a case-sensitive substring comparison after normalization. PDF-only fuzzy
matching is described below.

| Order | Operation |
|---|---|
| 1 | Unicode NFKC |
| 2 | Collapse whitespace runs to one ASCII space |
| 3 | Strip soft hyphen U+00AD |
| 4 | Fold U+2018/U+2019 to ASCII apostrophe; U+201C/U+201D to ASCII quotation mark |
| 5 | Fold U+2010–U+2015 and U+2212 to ASCII hyphen |
| 6 | Trim both ends |

Examples: `ＡＢＣ “Top”—it’s` becomes `ABC "Top"-it's`; `a` + NBSP + `b`
becomes `a b`; `Case` stays distinct from `case`. Stripping a soft hyphen joins
its neighboring letters. Operation order matters: `a` + space + soft hyphen +
space + `b` becomes `a  b` (two spaces after the soft hyphen is stripped). A quote needs at least 20 characters after these operations.
Wikipedia quotes are additionally limited to 200 normalized characters.

| Extractor version 3 | Operation |
|---|---|
| Byte decoding | Archived response charset header, else HTML `<meta charset>` (including charset in content attribute), else UTF-8 with replacement |
| HTML | stdlib `html.parser`, entity decoding enabled |
| Dropped subtrees | `script`, `style`, `noscript`, `template` |
| Block boundaries | Newline at start/end of address, article, aside, blockquote, br, dd, div, dl, dt, fieldset, figcaption, figure, footer, form, h1–h6, header, hr, li, main, nav, ol, p, pre, section, table, tbody, td, th, thead, tr, ul |
| HTML output | Normalize extracted text with norm_version 1 |
| Text output | Decode bytes as above and normalize |
| PDF text | pypdf 6.19.0 with fonttools 4.66.1 for embedded CFF encodings extracts text per page; join with newline and normalize; unreadable/encrypted/textless PDFs fail |
| Image / scan | No OCR; scans require manual evidence |

Snapshots are hashed as raw bytes. Gzip magic causes decompression **after** hash
verification and **before** decoding; local `.bin` fixtures use the same rule.
Unknown charset names fall back to UTF-8 with replacement. Local snapshots have
no response header, so use their meta charset or UTF-8. The fetched archive cache
preserves a response charset in an optional `<sha256>.charset` sidecar. Manual evidence is not
matched by the build. Golden tests live in `tests/test_core.py`; gzip verification
runs through the real build in `tests/test_integrity.py`.


PDF evidence may use `fuzzy`: case-sensitive normalized Levenshtein ratio (`1 - distance / max(lengths)`) >= 0.90
across contiguous normalized windows of quote length ±20% (ceil lower bound,
floor upper bound). Numeric tokens (`\d+(?:[.,]\d+)*`), including years and
caliber-number digits, must match exactly and in order. Windows cannot clip a
numeric token to hide a differing digit. HTML/text retain exact matching only.
Synthetic PDF extraction and matching golden tests are generated in
`tests/test_pdf_evidence.py`; no real source PDF bytes are committed.

Before extracting PDF page text, inspect its font resources and nested Form
XObject font resources. Reject an `/Encoding /Differences` entry assigning a
glyph that resolves to a digit to any code other than that digit's ASCII code.
Glyph resolution includes Adobe names, `uni`/`u` Unicode names and name suffixes.
Also reject an embedded CFF Type1 font when its explicit encoding and CFF-derived
mapping disagree at an ASCII digit code (48–57). These checks run independently
of pypdf's optional fonttools detection flag. Errors use
`unsupported_content_type` and name the font resource and font name. A refused
page makes the whole PDF unavailable for automatic matching; unreliable pages
are never silently omitted. Correct digit encodings and ordinary embedded CFF
fonts remain supported; there is no OCR fallback.

Existing supported extraction outputs are unchanged (`extractor_version: 3`).
The new validation guard has `pdf_digit_guard_version: 1`, bound into review
fingerprints so reports produced before this guard require a fresh build.
