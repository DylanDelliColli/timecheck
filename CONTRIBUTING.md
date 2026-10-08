# Contributing

Code is MIT; `data/` is ODbL 1.0 with DbCL for contents. Every commit needs a
Developer Certificate of Origin sign-off (`git commit -s`). Submit a pull request;
workers target `release/v1`. Never enter a catalogue fact from memory.

Each entity lives in its type directory with its slug as filename. Files have
`schema_version: 1`; relationships and attributes are claims, not entity fields.
Use `timecheck id new claim` and `timecheck id new evidence` for opaque identifiers.
Keep old slugs in `aliases` when renaming. Relations use the canonical directions
in `schemas/vocabularies.json`; inverse queries come from SQLite views.

Every claim needs a source, a pinned Wayback `id_` archive URL, the SHA-256 of its
raw bytes, an exact short quote and locator. Quotes need at least 20 normalized
characters. Use `timecheck snapshot hash FILE`; hash compressed archive bytes
before extraction. Do not commit full real source pages or scans. Test snapshots
are project-authored synthetic content. Wikipedia sources need a permanent revision
URL, licence `CC BY-SA 4.0`, and quotes at most 200 normalized characters.
Third-party excerpts keep their attribution and rights; they are verification
excerpts, not relicensed contents. The excerpt position needs operator confirmation
before public release, as recorded in the design record.

Primary sources are manufacturer materials, official specifications, brand archives,
and dated catalogues/advertisements. Other references are secondary. Reuse class is
separate: open sources may be extracted, copyrighted sources are cite-only, and
non-commercial sources are banned. Do not systematically extract cite-only sources.
Once the graph has 50 evidence items, each cite-only registrable domain may supply
at most 20% of all evidence. Registrable domains use the offline Public Suffix List
bundled with pinned `publicsuffix2==2.20191221`; update its rules by reviewed dependency
change when new suffixes matter.

Start claims as `proposed`. Verification needs `review.by` and `review.at` and a
faithful transcription of the evidence. Scans use `manual`, remain proposed until
a human attests them, and are skipped by exact matching. An agent must never attest
a scan as a human. Known worker/agent reviewer identities are rejected for verified
manual evidence; the validator cannot authenticate arbitrary reviewer identities.
PDF extraction, OCR and fuzzy matching are outside v1 tooling. A false boolean
needs an explicit absence quote; silence means unknown. Quote matching confirms
presence, not the truth of an interpretation: reviewers must assess the claim.
Unknown year bounds and their evidence IDs are null. Known inclusive bounds (including
`present`) name evidence within that claim. Keep competing claims; disputes are
computed, never stored in JSON. A second verified predecessor is reported as a
branch and excluded from lineage diffs.

Use Python 3.13 and a worktree-local virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
scripts/check.sh
```

Tests run a real build, open real SQLite and invoke the CLI, using synthetic fixtures
without external network. Write failing behavioral tests before changes. PR CI also
checks changed claims against live archives; changing a source rechecks its consumers.
Scheduled checks perform a full live build from `release/v1`. GitHub schedules only
activate once this workflow exists on the default branch. Keep all build and cache
outputs local; never point tests at another worker's runtime files.
