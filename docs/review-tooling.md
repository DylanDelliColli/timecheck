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
that review to exact-verified proposed claims:

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
state `verified` in the report and mode `exact` by default; unchecked, warning
and error candidates are skipped. Add `--include-fuzzy` to also accept matched
`fuzzy` evidence from `pdf_text` sources. Manual candidates refuse the operation unless
explicitly excluded; this command never provides a human scan attestation.
The flag records the maintainer's explicit choice to promote reviewed fuzzy PDF
claims; independent review of their interpretation is still required.

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

Digital PDFs use pinned `pypdf==6.19.0` and `fonttools==4.66.1` (embedded CFF
font encodings), normalize extracted page text, and allow
`exact` or `fuzzy` evidence. Fuzzy matching uses case-sensitive normalized Levenshtein
ratio (`1 - distance / max(lengths)`) at least 0.90 on contiguous normalized windows whose length is 80–120%
of the normalized quote length. Numeric tokens, including years, decimals and
numbers embedded in caliber designations, must match exactly and in order;
window boundaries cannot truncate a number. Fuzzy mode is rejected for other
content types. Empty, encrypted or unreadable PDFs return the existing
`unsupported_content_type` error. There is no OCR; scans remain manual.
