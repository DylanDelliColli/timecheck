# Normalization and extraction

`norm_version: 1` applies identically to quotes and extracted snapshots. Matching
is a case-sensitive substring comparison after normalization.

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

| Extractor version 1 | Operation |
|---|---|
| Byte decoding | Archived response charset header, else HTML `<meta charset>` (including charset in content attribute), else UTF-8 with replacement |
| HTML | stdlib `html.parser`, entity decoding enabled |
| Dropped subtrees | `script`, `style`, `noscript`, `template` |
| Block boundaries | Newline at start/end of address, article, aside, blockquote, br, dd, div, dl, dt, fieldset, figcaption, figure, footer, form, h1–h6, header, hr, li, main, nav, ol, p, pre, section, table, tbody, td, th, thead, tr, ul |
| HTML output | Normalize extracted text with norm_version 1 |
| Text output | Decode bytes as above and normalize |
| PDF / image | No automated extraction; scans require manual evidence |

Snapshots are hashed as raw bytes. Gzip magic causes decompression **after** hash
verification and **before** decoding; local `.bin` fixtures use the same rule.
Unknown charset names fall back to UTF-8 with replacement. Local snapshots have
no response header, so use their meta charset or UTF-8. The fetched archive cache
preserves a response charset in an optional `<sha256>.charset` sidecar. Manual evidence is not
matched by the build. Golden tests live in `tests/test_core.py`; gzip verification
runs through the real build in `tests/test_integrity.py`.
