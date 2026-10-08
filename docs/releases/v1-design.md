# Design record: timecheck v1 — sourced graph, database first

- Release, release bead and brief revision: `v1` (`v0.1.0`), bead `timecheck-wfn`,
  brief `docs/releases/v1.md` sha256 `41a46903089ac9db915345da2ad3967538d9f5ddbf3fcb66eee31f6d328acb83`,
  PRD `docs/PRD.md` sha256 `b082870653b9851f329ee4375743afab28af85f6f791d62588f474b6bf7d9cdb`.
- Base commit the record describes: `a0953309e527ebac912b0f2e36336f0672320280` (`main`,
  from which `release/v1` is cut). The repository holds no product code at this commit.
- Depth, and why: light. The release creates a fresh system with no authentication, no
  existing data to migrate and no integration with an external service; its one
  external contract is the data schema that future contributors code against. Second
  opinions obtained: a Codex (gpt-6.1-sol, high) cold read of the plan and four
  fresh-context `claude-sonnet-5-5` adversarial reviews of the design draft (scores
  7, 6, 6, 6 of 10; 68 issues raised, 64 decided here, 4 carried as open concerns).
- Status: chosen, 2026-10-08; revised 2026-10-08 (required check and `--data-dir` /
  `--no-evidence`, raised by unit C1; integrity-status rule, raised by C1/C2; status
  transitions, after the pilot). Canary revision pending the C1/C2 merges.

## Product fit

PRD use cases 1–5 (from a watch; vintage buyer's view; lineage; cross-maker
designation; evidence filter), for the operator first and for programmers and agents
reading the database. It displaces manual cross-reading of Ranfft DB, Caliber Corner,
Wikipedia and brand archives. It must not do what makes it wrong per the PRD: a claim
without verifiable evidence, a silent conflict, a conflated grade, a multi-caliber
reference shown with one, or systematic extraction from a copyrighted database.
Doubtful fit: none for v1; the frontend that would make this a consumer product is
deferred by the operator.

## Fit with the existing system

Fresh repository: `docs/` only. Everything below is new. Stack (recorded in
`AGENTS.md`): Python 3.13, a `timecheck` package in src layout with a console script,
JSON Schema (`jsonschema` 4.23.0), SQLite through the standard library, `pytest`
8.3.4. No ORM, no web framework, no Node code. A worker would otherwise re-implement:
slug and id rules, the normalization and extractor tables, the view definitions and the
error classes; all are fixed here.

## Interfaces and contracts

These are fixed before dispatch. A change goes through the chief and is recorded here.

### Repository layout
```
pyproject.toml            package metadata, pinned deps, console script `timecheck`
src/timecheck/            package: validate.py, build.py, evidence.py, normalize.py,
                          extract.py, ids.py, cli.py, sql/ (schema.sql, views.sql)
schemas/                  JSON Schema: entity.schema.json, claim.schema.json,
                          source.schema.json, vocabularies.json
data/brands/<slug>.json   brands, makers and authorities (kind: brand|maker|authority)
data/lines/<slug>.json    model lines
data/references/<slug>.json
data/calibers/<slug>.json
data/sources/<slug>.json
data/LICENSE              ODbL 1.0 + DbCL
LICENSE                   MIT
CONTRIBUTING.md           source policy, cap, DCO
docs/normalization.md     normalization and extractor tables (golden-tested)
docs/querying.md          views, columns, CLI, worked examples (written for agents)
tests/                    pytest; tests/fixtures/data/ (synthetic entities),
                          tests/snapshots/<sha256>.bin (synthetic, project-authored)
scripts/check.sh          required check (fixture strict build + real-data structural build)
.github/workflows/check.yml   PR and push: scripts/check.sh plus live verification of
                          changed claims; schedule: full live verification on release/v1
```

### Identifiers
- Entity ids are slugs with a type prefix: `brand:rolex`, `brand:usaaf` (an authority,
  `kind: authority`), `line:rolex-submariner`, `line:usaaf-a-11`,
  `reference:rolex-16610`, `reference:elgin-a-11`, `caliber:rolex-3135`,
  `caliber:eta-2824-2` (ungraded), `caliber:eta-2824-2-top` (grade entity),
  `source:rolex-com-submariner-date-20261008`. Slug charset `[a-z0-9-]`, maximum 64
  characters after the prefix. Filename = the part after the colon plus `.json`.
- `aliases[]` holds alternate spellings and former slugs; renaming keeps the old slug
  as an alias. Validation fails on an unresolved reference and warns on a slug that
  disappears without an alias.
- Claim ids `clm-<10 base32 chars>`, evidence ids `ev-<10 base32 chars>`, minted by
  `timecheck id new {claim|evidence}`; globally unique, validation fails on duplicates.

### Entity file
```json
{"id":"reference:rolex-16610","kind":"reference","display_name":"Rolex Submariner Date 16610",
 "aliases":["reference:rolex-16610-lv"],"claims":[ … ]}
```
Entity files carry identity and `claims[]` only; no structural foreign keys. Source
files are metadata records, not claims (see below).

### Source file
```json
{"id":"source:…","kind":"source","url":"https://…","publisher":"Rolex SA",
 "trust_tier":"primary","reuse_class":"cite_only","licence":"copyright, cite-only",
 "content_type":"html","archive_url":"https://web.archive.org/web/20261008120000id_/https://…",
 "snapshot_sha256":"…","retrieved_at":"2026-10-08","notes":""}
```
- `trust_tier`: `primary` | `secondary`. `reuse_class`: `open` | `cite_only`.
  `content_type`: `html` | `text` (v1); `pdf_text` and `image_scan` are accepted by the
  schema but `pdf_text` matching was activated by unit E1 on 2026-10-08 after unit S4 recorded that the Sellita and ETA technical sheets are digital PDFs (`pypdf` pinned, `extractor_version` 2) and
  `image_scan` always requires `match_mode: manual`.
- `archive_url` must be a Wayback URL in the `id_` raw-bytes form; `snapshot_sha256`
  is the SHA-256 of the bytes that URL returns. A JS-rendered, redirecting or
  login-walled page is citable only through such a pinned archive of rendered content.
- Wikipedia sources carry `licence: "CC BY-SA 4.0"`, the permanent revision URL as
  `url`, and quotes limited to 200 normalized characters. Quotes from any source are
  short verification excerpts with attribution, not relicensed content (position
  recorded for the operator to confirm before the repository goes public).

### Claim
```json
{"id":"clm-…","predicate":"uses_caliber","object":{"entity":"caliber:rolex-3135"},
 "valid_years":{"from":1988,"to":2010,"from_evidence":"ev-…","to_evidence":"ev-…"},
 "status":"verified","contested":false,"review":{"by":"w-timecheck-abc","at":"2026-10-08T20:00:00Z"},
 "evidence":[{"id":"ev-…","source":"source:…","quote":"…","locator":"specifications panel","match_mode":"exact"}]}
```
- The subject is the enclosing entity. `object` is `{"entity": slug}`, `{"value": …,
  "unit": …}`, `{"value": "<vocabulary term>"}`, `{"value": true|false}` or
  `{"years": {"from": …, "to": …, "from_evidence": …, "to_evidence": …}}` per predicate.
- Years: inclusive; `from` integer or null (unknown); `to` integer, `"present"` or
  null (unknown). Each bound names an evidence id present in the claim's `evidence[]`,
  or is null when the bound is unknown.
- `status`: `proposed` | `verified`. `verified` requires `review.by` and `review.at`.
  `contested` is a reviewer flag. `disputed` is computed at build (below), never stored.
- Boolean-false claims (`offers_grades: false`, `hacking: false`) need a quote that
  states the absence explicitly; otherwise the attribute is unknown (no claim).
- `evidence[]` has at least one item; `quote` is at least 20 normalized characters;
  `match_mode`: `exact` (html, text), `manual` (image_scan; only a human sets
  `verified`). `fuzzy` is allowed only for `pdf_text` sources (activated by E1, 2026-10-08; validation rejects it elsewhere).

### Status transitions (decision 2026-10-08, after the pilot)
Authors always write `status: proposed` and never a `review` block. At merge of a data
PR the chief runs the independent review (an outside model reading the PR's claims
against their quotes) and the strict live build; every claim the build verified and
the review did not flag is set to `verified` with `review.by` naming the reviewer run
and the merger (e.g. `codex:gpt-6.1-sol:pr2 / chief`) and `review.at` the merge time,
in a chief commit on the PR branch before the merge. Flagged claims stay `proposed`
and are listed on the unit's bead for repair. `manual` evidence keeps its claims
`proposed` until the operator attests. After v1, a human maintainer performs the same
step for outside PRs. The build's `--no-evidence` report lists `proposed` claims per
file so the step is auditable.

### Predicates and vocabularies (`schemas/vocabularies.json` is authoritative)
| Subject | Predicate | Object | Cardinality |
|---|---|---|---|
| line | `owned_by` | brand/authority entity | single |
| reference | `in_line` | line entity | single |
| reference | `uses_caliber` | caliber entity + `valid_years` | multi; disputed only on overlapping years |
| reference | `produced` | years | single |
| reference | `succeeds` | reference entity (same line) | single verified; a second verified one is a branch (reported, excluded from diffs); acyclic |
| caliber | `made_by` | brand entity | single |
| caliber | `offers_grades` | boolean | single |
| caliber | `grade_name` | string (grade entities only) | single |
| caliber | `derived_from` | caliber entity (the base) | single |
| caliber | `clone_of` | caliber entity (the original) | single |
| caliber | `grade_of` | caliber entity (the ungraded caliber) | single |
| caliber | `winding` | `manual`\|`automatic` | single |
| caliber | `beat_rate` | value, unit `vph` | single |
| caliber | `jewels` | value, unit `count` | single |
| caliber | `power_reserve` | value, unit `hour` | single |
| caliber | `hacking` | boolean | single |
| caliber | `date_mechanism` | `none`\|`date`\|`day_date`\|`other` | single |
| caliber | `introduced` | value, unit `year` | single |
| caliber | `discontinued` | value, unit `year` | single |
Relations are stored in the canonical direction only; inverses are derived at build.
Status and integrity (decision 2026-10-08, raised by units C1/C2): integrity checks
(slug resolution, same-line rule for `succeeds`, acyclicity, cardinality, id
uniqueness) consider claims of every status, `proposed` included, because authors
never set `verified` and the structure must validate before review. "Single verified
predecessor" refers to the status of the `succeeds` claims themselves: two verified
ones make a branch; `proposed` ones do not count toward it. Status filtering happens
only in the views (`v_*` exclude `proposed`; `v_*_all` include it) and in `disputed`
computation, which considers verified claims only.
A single-valued predicate with two competing verified claims is disputed. Unknown
`uses_caliber` bounds do not create overlap; such claims are reported as `years_unknown`.
Further attributes are added by schema change through the chief, with evidence, never
inferred.

### Grade
A documented grade is its own caliber entity with `grade_of` → the ungraded caliber and
a `grade_name` claim. Grade in every view: `grade_name` when the `uses_caliber` target
is a grade entity; `none` when the target caliber has a verified `offers_grades: false`
claim; `unknown` otherwise.

### Normalization and extraction (`norm_version` 1, `extractor_version` 1)
Normalization: NFKC; collapse runs of whitespace to one space; strip soft hyphens
(U+00AD); fold typographic quotes (U+2018/2019 → `'`, U+201C/201D → `"`) and dashes
(U+2010–2015, U+2212 → `-`); trim; case-sensitive. HTML extraction (stdlib
`html.parser`): decode bytes using the archived response's charset header, else
`<meta charset>`, else UTF-8 with replacement; drop `script`, `style`, `noscript`,
`template` subtrees; decode entities; block-level elements emit a newline; then
normalize. `text` sources: decode as above and normalize. Both tables live in
`docs/normalization.md` with golden tests under `tests/`.

### Build: `timecheck build [--strict] [--offline] [--no-evidence] [--data-dir DIR] [--snapshot-dir DIR] [--only-changed PATHS] [--out timecheck.sqlite] [--report report.json]`
`--data-dir` defaults to `data/`. `--no-evidence` runs steps 1, 2 and 4 only (schema,
integrity, compile, report) and marks every evidence item `unchecked` in the report;
it exists so the required check can validate the real `data/` structurally without
network and without any real snapshot bytes in the repository.
1. Schema validation of every file in `data/`.
2. Integrity: slugs resolve; vocabularies; canonical relation direction; `succeeds`
   acyclic within a line and single verified predecessor; id uniqueness; evidence ids
   referenced by year bounds exist; quote length; cap on evidence share per registrable
   domain (eTLD+1) for `cite_only` sources: 20% of all evidence items once there are
   50 or more.
3. Evidence: for each evidence item, obtain the snapshot bytes (from
   `--snapshot-dir DIR/<snapshot_sha256>.bin` when given, else by fetching
   `archive_url` with 3 retries and exponential backoff), compare the hash, extract
   and normalize text, and find the normalized quote (`exact`). `manual` items are
   not checked. Error classes: `evidence_missing`, `snapshot_unavailable`,
   `snapshot_hash_mismatch`, `quote_not_found`, `unsupported_content_type`,
   `quote_too_short`. `--strict`: every class is an error (exit 2). Without
   `--strict`: `snapshot_unavailable` is a warning. `--offline`: no fetching; every
   item without a local snapshot is `snapshot_unavailable`. `--only-changed PATHS`
   (used by CI) restricts evidence checks to the claims in the given files.
4. Compute `disputed` per the cardinality rules; compile the SQLite file (tables
   `brand, line, reference, caliber, source, claim, claim_object, claim_years,
   claim_review, evidence`; views below); write `report.json`.
Exit codes: 0 ok, 1 warnings only, 2 errors.

### Report (`report.json`)
Counts per entity kind; claims by status, tier (`has_primary`) and predicate;
disputed, contested, branches, `years_unknown`, pending manual attestations; coverage
per seed line (references with at least one verified `uses_caliber` claim, excluding
`proposed`, against the line's target list in `data/targets/<line>.json`); evidence
share per registrable domain; verification errors and warnings by class.

### SQLite views (six). Every `v_*` view excludes `proposed` claims; `v_*_all` includes them.
Common columns: `status` (`verified`|`proposed`), `disputed` (0/1), `contested` (0/1),
`has_primary` (0/1). Year columns: `year_from INTEGER NULL`, `year_to INTEGER NULL`,
`year_to_kind TEXT` (`year`|`present`|`unknown`), `year_from_sort INTEGER`
(= COALESCE(year_from, 9999)). No ORDER BY inside views.
- `v_reference_calibers`(reference_id, caliber_id, grade, year_from, year_to,
  year_to_kind, year_from_sort, claim_id, status, disputed, contested, has_primary).
  Filter by `caliber_id` for the inverse question.
- `v_caliber_family`(caliber_id, related_id, relation_path, depth): bounded connected
  component over the undirected union of `derived_from`, `clone_of`, `grade_of`;
  recursive CTE carrying the visited path (cycle guard), depth cap 6 (truncation
  reported), one row per pair keeping the shortest path; `relation_path` is the
  comma-joined edge types.
- `v_shared_dna`(reference_id, other_reference_id, via_caliber_id, relation_path,
  disputed, has_primary): other references whose `uses_caliber` target is the same
  caliber or in its family; `relation_path` empty for the same caliber.
- `v_lineage`(line_id, reference_id, year_from, year_to, year_to_kind,
  year_from_sort, caliber_id, grade, succeeds_reference_id, claim_id, status,
  disputed, contested, has_primary): one row per selected `uses_caliber` claim; a
  reference without one gets one fallback row per selected `produced` claim (competing
  intervals therefore appear as separate rows, flagged disputed), or a single row with
  null years and `year_from_sort` 9999 when it has neither. Duplicate identical claims
  (same object or value, different ids, e.g. the same fact backed by two sources) are
  legitimate data and yield one row per claim; consumers wanting distinct facts use
  DISTINCT on the value columns. Metadata joins (membership, grade, succession,
  `offers_grades`) are aggregated per subject and never multiply rows (decision
  2026-10-08, after review rounds 3 and 4 of unit C1).
- `v_lineage_diff`(line_id, reference_id, predecessor_id, attribute, before_value,
  after_value, changed, before_status, after_status, before_evidence_id,
  after_evidence_id): along verified `succeeds` edges only; `attribute` is `caliber`,
  each v1 caliber attribute, and `years` (`"from-to"` strings); predecessor side =
  its latest caliber by `year_from`, successor side = its earliest; unknown year on
  either side → one row per attribute with `changed = NULL`; competing values produce the cross product of rows, and rows are DISTINCT over
  (line_id, reference_id, predecessor_id, attribute, before_value, after_value):
  duplicate identical claims never repeat a diff row (evidence ids then cite one
  representative claim each).
- `v_evidence`(claim_id, evidence_id, source_id, tier, match_mode, quote, locator,
  archive_url, retrieved_at).

### CLI
`timecheck build …` as above. `timecheck query VIEW [--where SQL] [--primary-only]
[--include-proposed] [--db PATH] --json` prints a JSON array of rows (exit 0; exit 2 on
SQL error). `timecheck id new {claim|evidence}` prints one id. `timecheck snapshot pin
URL` requests a Wayback capture, prints the pinned `id_` URL and the sha256 (network;
not used by tests). `timecheck snapshot hash FILE` prints the sha256.

### Required check (`scripts/check.sh`, no network)
1. `.venv/bin/python -m pytest -q`
2. `.venv/bin/timecheck build --strict --data-dir tests/fixtures/data --snapshot-dir tests/snapshots --out /tmp/timecheck-fixtures.sqlite`
   (the synthetic fixtures with their synthetic snapshots: evidence fully verified).
3. `.venv/bin/timecheck build --strict --no-evidence --data-dir data --out /tmp/timecheck-data.sqlite`
   (the real seed: schema and integrity, no evidence fetch; real snapshot bytes are
   never committed). Evidence for real claims is verified live only in the PR job
   (`--only-changed`) and the scheduled job on `release/v1`.
Decision 2026-10-08 (raised by unit C1): the earlier form, a strict build of root
`data/` against fixture snapshots, could pass only while `data/` was empty.

### Tests (`pytest`, no network)
Unit: normalization and extractor golden tests; id minting; cardinality and disputed
computation; year parsing. Integration (real composition): run `build --strict
--data-dir tests/fixtures/data --snapshot-dir tests/snapshots` (a synthetic brand, line,
three references with a succession, two calibers with a grade entity, sources with
synthetic snapshot bytes), open the produced SQLite and assert every view's rows; run
the CLI as a subprocess. Negative fixtures, one each: no evidence, quote absent, hash
mismatch, unresolved slug, duplicate id, `succeeds` cycle, overlapping `uses_caliber`
years (→ disputed), boolean-false without explicit absence quote. Fixture snapshots
are synthetic pages written by the project, never copies of real sites.

## Data and migration

No existing data. Schema versioning: `schemas/` carry `"$id"` with a version; data
files carry `"schema_version": 1`; a schema change ships with a migration script under
`scripts/migrations/` and a note here. Rollback is `git revert`. No Supabase, no
external database.

## Risks and unknowns

- Primary sources for the Submariner may be unavailable as pinned archives (Rolex pages
  are JS-rendered). The sourcing pilot's first task is a Wayback availability probe of
  the planned primary sources per family; fallback is secondary-only, visible in the
  report. Finder: pilot worker.
- Sourcing cost per reference is unknown; the pilot measures it (sourcing time only,
  build time excluded). Finder: pilot worker. The chief sets family depth before any
  seed unit is dispatched; floor = the pilot's ten plus about forty references.
- Wayback flakiness in CI: retries and a sha256 snapshot cache; a failure after retries
  is an error and the job is re-runnable. Finder: tooling worker (CI workflow).
- Whether `succeeds` alone orders parallel tracks (date / no-date Submariners) or a
  `track` attribute is needed. Finder: pilot worker on the Submariner.
- Short quoted excerpts under ODbL: position recorded above; operator confirms before
  going public.
- Manual attestation of scans needs operator time; such claims stay `proposed`.

## Test strategy

Unit and integration tests as under Interfaces, run by `scripts/check.sh` locally and
in CI. Real-journey checks per the brief: (1) full seed strict build with live
verification, timed, plus the negative fixtures; (2) the Seamaster question and the
Submariner lineage answered through `timecheck query` and SQL in the chief's lane;
(3) an uncoached walkthrough by a code-blind evaluator from an empty checkout using
`docs/querying.md`, the build and the CLI for PRD use cases 1–5. Provenance audit at
readiness: a random sample of verified claims re-checked against pinned snapshots,
aggregate reported. No disposable stack: each worker's build writes its own SQLite file
in its worktree.

## Decomposition

Units (one to three beads each; a unit ships as one PR into `release/v1`):

- **C1 Tooling (canary, half 1)**: package skeleton, pyproject with pinned deps,
  licences and CONTRIBUTING, schemas and vocabularies, validation and integrity
  checks, normalization/extractor with golden tests and `docs/normalization.md`,
  evidence verification with `--snapshot-dir`, SQLite compile with the six views,
  report, CLI (`build`, `query`, `id`, `snapshot hash`), fixtures and negative
  fixtures, `scripts/check.sh`, CI workflow. No real data.
- **C2 Sourcing pilot (canary, half 2)**: in parallel with C1 against this record's
  contract: Wayback availability probe of planned primary sources per family; ten
  references across the five families (at least two Submariner with a `succeeds`
  edge, one Seamaster, one Presage, one ETA/Sellita host pair, one A-11, one scan-based
  source recorded as `manual`/`proposed`) with their calibers, sources and claims as
  JSON files; time per reference recorded on the bead; validated with C1's build once
  it lands (or the pilot's own `jsonschema` check before). Produces `data/targets/`
  lists for Submariner.
- **Gate**: chief folds C1/C2 findings into this record, sets depth per family from
  the measured cost, revises undispatched beads.
- **Wave** (≤3 concurrent): **S1** Submariner to the floor; **S2** Seiko Presage +
  4R/6R/6L lines; **S3** Omega Seamaster 1960s–70s; **S4** ETA/Sellita cross-brand
  hosts; **S5** A-11 trio; **E1** evidence tooling: `snapshot pin`, scheduled full
  verification, and `pdf_text`/`fuzzy` (activated: S4 recorded the PDF need on 2026-10-08);
  **D1** `docs/querying.md` for agents with worked examples and the CLI polish needed
  by the walkthrough.
- Dependencies (`br dep add`): every wave unit depends on C1; S1–S5 and D1 depend on
  the gate (recorded as a dependency on C2); E1 depends on C1 only.
- Wave order by independence: S1 and D1 first (lineage is canonical and the docs are
  on the walkthrough path), then S2–S5 as slots free, E1 whenever a slot is free.

## Alternatives considered

Light record. Second opinions: Codex's cold read proposed the claim-centric file layout
and the evidence drawer and challenged the seed scope (adopted as the pilot gate); four
fresh-context Sonnet reviews drove the rules for absence claims, cardinality and
overlap, status columns on views, slug-to-file mapping, six views, PR-scoped live
verification instead of a ledger, the canary split and the 50-reference floor.
Rejected: YAML + static site (no downloadable graph), an evidence-first document
archive (2–3 weeks, copyright at scale), a graph database (queries are shallow).

## Rulings needed

None blocking. For the operator's return, with defaults in force meanwhile: (1) confirm
the position on short quoted excerpts before the repository goes public (default: as
recorded); (2) plan time to attest scan-based evidence at readiness (default: those
claims stay `proposed`).
