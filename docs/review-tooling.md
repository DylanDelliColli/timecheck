# Evidence and review tools

`timecheck snapshot pin URL` requests a Wayback capture and prints a JSON object
with `archive_url` in raw `id_` form, `snapshot_sha256`, a `content_type` guess and
UTC `retrieved_at` date. When saving returns a queue/status page, it resolves the
closest available capture to the request time. An existing nearest capture may be
returned while a new capture is queued. Each request has a 30-second timeout and
three retries after the initial attempt, with 1/2/4-second delays. Unavailable
captures and exhausted retries return exit 2 with a diagnostic. Bodies are hashed
before gzip decompression; source bodies are never written to the repository.
The PDF content-type guess requires inspection: image-only PDFs need manual
attestation and cannot be treated as digital text.

After an independent review and a strict evidence build, maintainers can apply
that review to proposed claims whose every evidence item is an exact match on an
HTML or text source:

```sh
timecheck build --strict --data-dir data --report report.json
timecheck status verify --by 'review-run / chief' --report report.json \
  --files data/references/example.json --except clm-aaaaaaaaaa
```

`--data-dir` defaults to `data`, `--report` to `report.json`. Omit `--files` to
select all claim files. `--except` accepts one or more claim ids; excluded claims
remain proposed. `--at` accepts an ISO datetime with timezone and defaults to now
in UTC. Output is JSON: `{"count": 1, "claim_ids": ["clm-..."]}`. Existing verified
claims and their reviews are preserved. All evidence on a candidate must have
state `verified` in the report, mode `exact`, and source type `html` or `text`;
unchecked, warning and error HTML/text candidates are skipped. Any candidate
with `pdf_text` or manual evidence refuses the operation unless explicitly
excluded, regardless of its report state or whether its quote matches exactly.
PDF matching is an advisory pre-check in v1. PDF and scan claims stay proposed
until a human attests them; this command cannot provide that attestation.
`--include-fuzzy` has been withdrawn. Exclude the claim ids listed under pending
attestation to apply a review to the eligible HTML/text claims.

The report records SHA256 fingerprints of claim, subject, source metadata and
verification algorithm versions. Reports from earlier extraction/matching code
require rebuilding before promotion.
Quote, object, evidence or source edits require rebuilding before review; reports
from another data directory are refused. Status and review changes do not
invalidate the fingerprint, allowing repeat application. Candidates are validated
before any file is changed, and each changed JSON file is replaced atomically.
Replacement across multiple files is not a filesystem-wide transaction; inspect
git diff after an I/O failure. A report is a local trusted artifact, not a signed
attestation. Matching establishes that text is present; independent review must
still establish whether the claim interprets it faithfully.

The additive report fields are:

- `proposed_claims_by_file`: file paths as supplied to build, each with its proposed
  claim ids in file order. Available even with `--no-evidence`.
- `line_claim_counts`: verified/proposed counts for each line's own claims,
  member references and their used calibers plus connected base/clone/grade
  families. Membership and family traversal consider every status. Each subject
  counts once per line; shared calibers can count under multiple lines. Brand
  claims are excluded. These are claim counts, distinct from reference coverage.
- `data_dir`: resolved data root, used by the status command.
- `review_inputs`: claim ids mapped to fingerprints of the checked inputs.
- `pending_attestations`: proposed PDF/manual evidence rows, each containing
  `claim_id`, `evidence_id`, `source_id`, `content_type` and the claim file
  `location`. Rows are sorted by source, claim and evidence id to review one
  document at a time. They include matched, failed and unchecked evidence,
  including `--no-evidence` builds. Only evidence needing attestation is listed
  for a mixed-evidence claim; the entire claim remains proposed. The existing
  `pending_manual_attestations` evidence-id list still lists manual evidence only.

Digital PDFs use pinned `pypdf==6.19.0` and `fonttools==4.66.1` (embedded CFF
font encodings), normalize extracted page text, and allow
`exact` or `fuzzy` evidence. Fuzzy matching uses case-sensitive normalized Levenshtein
ratio (`1 - distance / max(lengths)`) at least 0.90 on contiguous normalized windows whose length is 80–120%
of the normalized quote length. Numeric tokens, including years, decimals and
numbers embedded in caliber designations, must match exactly and in order;
window boundaries cannot truncate a number. Fuzzy mode is rejected for other
content types. Empty, encrypted, unreadable or conflicting digit-encoding PDFs return the
existing `unsupported_content_type` error. The digit guard checks page and nested
form fonts before extraction, names an unsafe font, and refuses the PDF rather
than silently excluding a page; see `docs/normalization.md`. These guards do not
establish that extracted digits match the rendered glyphs in every PDF. Even a
successful PDF match never authorizes automatic promotion. There is no OCR;
scans remain manual.
