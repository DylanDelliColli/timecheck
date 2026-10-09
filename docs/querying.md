# Querying timecheck

Start here to build a local database, answer the five v1 questions and follow a
result back to its evidence. Run commands from the repository root. You need
Python 3.13 or newer, git and permission to clone the currently private GitHub
repository via an authorized GitHub SSH key. No standalone SQLite client is required.

## Agent quick start

These ten shell lines clone the current release, install the CLI, check it, build
the real seed without network and find the evidence for a Presage movement claim:

```sh
GIT_SSH_COMMAND='ssh -o BatchMode=yes' git clone --branch release/v1 git@github.com:DylanDelliColli/timecheck.git
cd timecheck
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
scripts/check.sh
.venv/bin/timecheck build --strict --no-evidence --data-dir data
.venv/bin/timecheck query v_reference_calibers --where "reference_id = 'reference:seiko-srpb41j1'" --json
.venv/bin/timecheck query v_shared_dna --where "reference_id = 'reference:seiko-srpb41j1'" --json
.venv/bin/timecheck query v_evidence --where "claim_id = 'clm-6gnbc5jd5g'" --json
.venv/bin/python -c 'import json,pathlib; print(json.dumps(json.loads(pathlib.Path("data/references/seiko-srpb41j1.json").read_text()), indent=2))'
```

Evidence items live inside each entity's `claims[].evidence[]`; their `source`
points to metadata in `data/sources/`. The database joins these in `v_evidence`.
The structural build in this quick start leaves evidence `unchecked`. Use the
live build below before treating a report as evidence verification.

## Build and verify

For an existing checkout, create `.venv` and install as above. Dependencies and
Python requirements are in `pyproject.toml`. `scripts/check.sh` runs pytest (unit
and real integration tests), a strict fixture build using project-authored
snapshots, and a strict structural build of the real seed. It needs no archive
network access and writes local files under `build/` plus `report.json`.
Installation itself needs package access unless dependencies are already cached.

Reproduce an evidence-verified synthetic build independently:

```sh
.venv/bin/timecheck build --strict --data-dir tests/fixtures/data --snapshot-dir tests/snapshots --out build/example.sqlite --report build/example-report.json
.venv/bin/timecheck query v_lineage --db build/example.sqlite --json
```

Compile the real seed offline for querying its authored claims:

```sh
.venv/bin/timecheck build --strict --no-evidence --data-dir data
```

Verify every machine-matchable item against its pinned archive with network:

```sh
.venv/bin/timecheck build --strict --data-dir data --cache-dir .cache/snapshots
```

The cache stores hash-checked raw bytes locally. A later offline replay can use it:

```sh
.venv/bin/timecheck build --strict --offline --data-dir data --cache-dir .cache/snapshots --out build/reverified.sqlite --report build/reverified-report.json
```

A missing cached snapshot fails the strict replay. Manual scan evidence is skipped
by machine matching even in a successful strict live build; inspect
`pending_manual_attestations`. Never commit real source bodies or scans.

### Build flags and failures

| Flag | Meaning |
|---|---|
| `--data-dir DIR` | JSON tree to compile; default `data`. |
| `--out PATH` | SQLite output; default `timecheck.sqlite`. Parent directories are created. |
| `--report PATH` | JSON report; default `report.json`. |
| `--strict` | Treat snapshot unavailability as errors; other validation and evidence failures are already errors. |
| `--no-evidence` | Validate schemas/integrity and compile, with all evidence `unchecked`; no fetching or matching. |
| `--offline` | Never fetch; check local snapshots/cache only. |
| `--snapshot-dir DIR` | Read `DIR/<snapshot_sha256>.bin`; supplying this also prevents network fallback for missing files. |
| `--cache-dir DIR` | Read/write persistent hash-checked snapshots, with optional `.charset` sidecars. |
| `--only-changed PATHS` | Limit evidence verification to claims in these entity files; schemas/integrity still check the whole tree. Zero paths skips all evidence checks. |

When using `--only-changed`, pass entity paths, not just source paths: source
metadata changes need all entity consumers rechecked. For full verification omit
this option. A partial report leaves other evidence `unchecked`.

Build exit codes: **0** success, **1** warnings only, **2** errors. Look at `errors`,
`warnings`, `errors_by_class` and `warnings_by_class` in the report. Archive
unavailability may reflect remote availability; a hash mismatch means the returned
raw bytes differ from the pin; `quote_not_found` means the normalized quote was
absent. Do not treat these as successful verification. An unsuccessful build may
leave an older SQLite file in place; check the exit code and report before querying
an output as if it were fresh.

The report also records `entity_counts`, `claim_counts` (status, primary support,
predicate), `evidence_count`, per-item `evidence_verification`, `disputed_claims`,
`contested`, `branches`, `years_unknown`, `pending_manual_attestations`, `coverage`,
`evidence_share` and `family_truncated`. Coverage uses target files under
`data/targets/`, verified membership and verified caliber usage; it is not a count
of every JSON file or proposed claim. Disputed/contested counts count claims.
`evidence_verification` distinguishes `verified`, `manual`, `unchecked`, `error`
and `warning`; it is separate from a claim's authored review status.

## SQLite layout

Entity/source JSON is the editable source of truth; SQLite is rebuilt output.
Entity IDs are typed slugs such as `reference:seiko-srpb41j1` and
`caliber:seiko-4r35`. Claim IDs start `clm-`; evidence IDs start `ev-`. Slugs and
aliases are exact strings, not a fuzzy search system. List names without assuming
a reference exists:

```sh
.venv/bin/python - <<'PY'
import sqlite3
with sqlite3.connect('timecheck.sqlite') as db:
    for row in db.execute('SELECT id, display_name FROM reference ORDER BY id'):
        print(*row, sep=' | ')
PY
```

The ten tables retain both proposed and verified claims. Use canonical views for
status-aware composition. The `brand` table contains brands, makers and authorities;
`line`, `reference` and `caliber` contain their respective entity types. These four
entity tables share all four columns:

| Column | Meaning |
|---|---|
| `id` | Canonical typed entity slug; primary key. |
| `kind` | Entity type; `brand` may be `brand`, `maker` or `authority`. |
| `display_name` | Human-readable name. |
| `aliases` | JSON-encoded array of alternate names/former slugs. |

`source` contains source records:

| Column | Meaning |
|---|---|
| `id` | `source:` slug; primary key. |
| `kind` | `source`. |
| `url` | Original source URL; Wikipedia uses a permanent revision URL. |
| `publisher` | Publisher attribution. |
| `trust_tier` | `primary` or `secondary`. |
| `reuse_class` | `open` or `cite_only`; independent of tier. |
| `licence` | Source's licence/rights statement. |
| `content_type` | Declared format: `html`, `text`, `pdf_text` or `image_scan`; matching support depends on the tooling revision. |
| `archive_url` | Pinned Wayback raw-byte `id_` URL. |
| `snapshot_sha256` | SHA-256 of the raw archived response bytes, before decompression/extraction. |
| `retrieved_at` | Source retrieval date. |
| `notes` | Source context; empty string when omitted. |

`claim` describes each assertion:

| Column | Meaning |
|---|---|
| `id` | Claim ID; primary key. |
| `subject_id` | ID of the enclosing entity. |
| `predicate` | Assertion type, e.g. `uses_caliber`, `in_line`, `succeeds`, `power_reserve`; vocabulary in `schemas/vocabularies.json`. |
| `status` | Authored `proposed` or reviewed `verified`. |
| `disputed` | Computed 0/1 conflict flag. |
| `contested` | Authored reviewer 0/1 flag. |
| `has_primary` | 1 if any evidence on this claim comes from a primary source, else 0. |

`claim_object` holds the target/value:

| Column | Meaning |
|---|---|
| `claim_id` | Claim foreign key and primary key. |
| `entity_id` | Target entity for a relationship, otherwise null. |
| `value` | Scalar serialized as text: strings as-is, numbers/booleans as JSON text (`false`, not SQL NULL). Null for relationships/year objects. |
| `unit` | Numeric unit such as `vph`, `count`, `hour`, `year`; otherwise null. |
| `object_json` | Full original object as JSON text, including year objects. |

`claim_years` holds usage `valid_years` or a `produced` year object:

| Column | Meaning |
|---|---|
| `claim_id` | Claim foreign key and primary key. |
| `year_from` | Inclusive start integer, or null for unknown. |
| `year_to` | Inclusive end integer; null for present or unknown. |
| `year_to_kind` | `year`, `present` or `unknown`; distinguishes those nulls. |
| `year_from_sort` | Start year, or 9999 for unknown; convenience sort key. |
| `from_evidence` | Evidence ID supporting the start bound, or null for unknown. |
| `to_evidence` | Evidence ID supporting the end bound, or null for unknown. |

`claim_review` exists only for claims with a review block:

| Column | Meaning |
|---|---|
| `claim_id` | Claim foreign key and primary key. |
| `reviewer` | Recorded reviewer identity (`review.by`); not proof of authenticated human identity. |
| `reviewed_at` | Recorded review timestamp (`review.at`). |

`evidence` retains individual excerpts:

| Column | Meaning |
|---|---|
| `id` | Evidence ID; primary key. |
| `claim_id` | Supported claim's foreign key. |
| `source_id` | Source foreign key. |
| `quote` | Short verification excerpt. |
| `locator` | Page/section/panel describing its location. |
| `match_mode` | `exact`, `manual` or schema-permitted `fuzzy`; format and tooling determine what can be checked. |

### Status, conflicts, years and grades

Default `v_*` views compose **verified** claims; each `v_*_all` counterpart includes
proposed claims too. The latter does not promote or review them. `v_lineage` also
retains reference identities as fallback rows, even if no selected claim exists;
null `line_id`/`claim_id` means no selected supporting fact. Composed rows may
combine several claims: their `status` is not a certification of every joined
fact. In particular an `_all` lineage row may say `verified` for its usage while
its membership is proposed. Read the relevant claim evidence.

Verification of a quote's presence is distinct from review of its interpretation.
The build never promotes claims. Proposed scan claims need human attestation.
Both disputed and contested claims stay visible in default views.

`disputed = 1` marks different verified values for a single-valued predicate.
For `uses_caliber`, different targets conflict only when both intervals have known
bounds and overlap (inclusive, with `present` unbounded). Unknown usage bounds do
not prove overlap: two calibers with unknown years remain visible with
`disputed = 0`; see `years_unknown`. `contested = 1` is a reviewer flag, independent
of computed disputes. Duplicate identical claims are legitimate and may yield
multiple rows; use `DISTINCT` on value columns if counting distinct facts.

On composed views, dispute/contest flags aggregate contributing facts.
`has_primary` is conservative across required facts (including grade metadata,
line membership, succession or family edges as applicable); a view row can be
secondary-supported even when its usage claim alone has primary evidence.

Year columns use the meanings in `claim_years`. A null year is unknown, never
zero. An absent claim differs from an explicitly stated negative. A `produced`
interval describes reference production; usage years describe a caliber's use in
that reference. `v_lineage` uses usage years when it has a usage row and falls back
to production only when it has no selected usage; query `produced` claims directly
for separate production dates. Views contain no `ORDER BY`; sort explicitly with
`year_from_sort, reference_id`, keeping unknown starts last.

Every usage/lineage `grade` is a documented grade name (for a caliber entity with
`grade_of` and `grade_name`), **`none`** only with a verified `offers_grades: false`
claim, or **`unknown`** otherwise. `unknown` must not be interpreted as Standard
or no grades. Proposed false claims do not turn grade into `none`, even in `_all`.

## Six canonical views and every column

Suffix `_all` has the same columns as its base view. Internal helper views such as
`selected_claim`, `membership`, `grade_metadata` and `family_paths` implement the
composition and are not CLI query targets.

### `v_reference_calibers`

One row per selected `uses_caliber` claim, with aggregated grade metadata. Query
`caliber_id` to answer the inverse “which references use this caliber?”; there is
no separate `v_caliber_references` view in the implemented six-view interface.

| Column | Meaning |
|---|---|
| `reference_id` | Usage subject reference. |
| `caliber_id` | Usage target, including a grade entity when documented. |
| `grade` | Documented name, `none` or `unknown`. |
| `year_from`, `year_to`, `year_to_kind`, `year_from_sort` | Usage interval and sort key as above. |
| `claim_id` | Supporting usage claim; join to evidence. |
| `status` | Usage claim's status. |
| `disputed`, `contested`, `has_primary` | Usage plus grade metadata flags. |

### `v_caliber_family`

Connected calibers through the undirected union of `derived_from`, `clone_of` and
`grade_of`, with a visited-path cycle guard and depth cap six. No self rows. One
shortest path per ordered caliber pair; this is a bounded neighborhood, not proof
of mechanical interchangeability. Check `family_truncated` in the report.

| Column | Meaning |
|---|---|
| `caliber_id` | Starting caliber. |
| `related_id` | Connected caliber. |
| `relation_path` | Comma-joined edge predicates on the chosen path; traversal can run either direction. |
| `depth` | Number of edges (1–6). |

### `v_shared_dna`

Other references using the same caliber or a connected family caliber. One
reference can have multiple routes/results; there is no ranking or price meaning.

| Column | Meaning |
|---|---|
| `reference_id` | Starting reference. |
| `other_reference_id` | Other reference, never the starting reference itself. |
| `via_caliber_id` | Starting reference's caliber connecting this pair. |
| `relation_path` | Empty string for identical caliber; otherwise family edge predicates. |
| `disputed` | Conflict on usage/grade facts or connecting family edges. |
| `has_primary` | Primary support across usages/grade metadata and the connecting path. |

### `v_lineage`

One row per selected usage; if none, one per selected production claim; if neither,
a reference fallback with null years. Membership/succession metadata is aggregated
and does not multiply rows. Filter `line_id` explicitly to exclude unassigned
fallbacks. Two distinct verified predecessors are a branch: reported in `branches`,
with null predecessor here and excluded from diffs.

| Column | Meaning |
|---|---|
| `line_id` | Selected model line; null for no selected or conflicting membership. |
| `reference_id` | Reference identity. |
| `year_from`, `year_to`, `year_to_kind`, `year_from_sort` | Usage interval, or production fallback, or unknown. |
| `caliber_id` | Selected caliber; null in a non-usage fallback. |
| `grade` | Usage grade; null in a non-usage fallback. |
| `succeeds_reference_id` | Selected single predecessor, or null for missing/ambiguous/branched succession. |
| `claim_id` | Usage claim, else production claim, else membership claim, else null. |
| `status` | That claim's status; fallback literal `verified` when none exists, so check `claim_id`. |
| `disputed`, `contested`, `has_primary` | Aggregated usage/production/membership/succession flags. |

### `v_lineage_diff`

Along **verified** `succeeds` edges only, including in `_all`. Compare the
predecessor's latest usage start with the successor's earliest. Missing usage or
an unknown usage start/end on either reference produces null comparisons for all
attributes. Known usages can still have unknown attributes. Competing values
produce cross-product comparisons; identical value pairs are deduplicated with
one representative evidence ID per side.

| Column | Meaning |
|---|---|
| `line_id` | Successor's selected line. |
| `reference_id` | Successor. |
| `predecessor_id` | Reference it succeeds. |
| `attribute` | `caliber`, `years`, `offers_grades`, `grade_name`, `winding`, `beat_rate`, `jewels`, `power_reserve`, `hacking`, `date_mechanism`, `introduced`, `discontinued`. |
| `before_value`, `after_value` | Text values; caliber IDs, scalar strings or `from-to` years strings; null for unknown. |
| `changed` | 1 different, 0 equal, null when comparison is unknown. |
| `before_status`, `after_status` | Status of each compared value's claim, null when absent/unknown interval. |
| `before_evidence_id`, `after_evidence_id` | Representative excerpt for each value; null when absent/unknown interval. Join to `v_evidence.evidence_id`. |

### `v_evidence`

One row per excerpt attached to a selected claim. This view does not include
hashes or machine-verification results: join `source` for hashes, and use the
current report for matching results.

| Column | Meaning |
|---|---|
| `claim_id` | Supported selected claim. |
| `evidence_id` | Excerpt ID. |
| `source_id` | Source metadata ID. |
| `tier` | `primary` or `secondary`. |
| `match_mode` | Matching/attestation mode. |
| `quote` | Attributed short excerpt. |
| `locator` | Where to inspect the quote. |
| `archive_url` | Pinned raw-byte Wayback URL. |
| `retrieved_at` | Source retrieval date. |

## CLI queries and tools

```sh
.venv/bin/timecheck query v_reference_calibers --where "caliber_id = 'caliber:seiko-4r35'" --db timecheck.sqlite --json
.venv/bin/timecheck query v_reference_calibers --include-proposed --json
.venv/bin/timecheck query v_reference_calibers_all --json
.venv/bin/timecheck query v_caliber_family --where "caliber_id = 'caliber:eta-2824-2'" --primary-only --json
.venv/bin/timecheck id new claim
.venv/bin/timecheck id new evidence
```

Hash an existing synthetic snapshot automatically:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
import subprocess
subprocess.run(['.venv/bin/timecheck', 'snapshot', 'hash', str(next(Path('tests/snapshots').glob('*.bin')))], check=True)
PY
```

`query VIEW` accepts only the six canonical names and their `_all` counterparts.
`--db` defaults to `timecheck.sqlite` and opens it read-only. `--where` is a trusted
local SQL expression, not a full SELECT or a bind parameter API. `--json` documents
the requested format; current query output is always a JSON array, including `[]`.
Successful queries exit 0; invalid views, SQL or missing databases exit 2.
`--include-proposed` selects the `_all` counterpart.

`--primary-only` rebuilds the views over primary-supported claims in that query's
connection, including family/succession edges. It is more than filtering the final
rows: secondary-only connecting facts are removed. Evidence results then contain
primary excerpts only. It does not mean all excerpts on a mixed-source claim are
primary. Direct SQLite queries do not activate this CLI transformation.

`id new` only mints an ID; it does not add a claim/evidence file. `snapshot hash`
hashes raw bytes without altering them. At the example revision below,
`snapshot pin URL` is reserved and returns 2 with an E1 message; capture tooling
is being delivered separately. Check `.venv/bin/timecheck --help` and subcommand
help for your installed revision. Schemas accept PDF/manual formats, but this
example revision's machine extractor supports HTML/text only; normalization and
format details are in [normalization.md](normalization.md).

## Worked examples on the merged seed

These are real outputs captured at release commit
`e09169c2282a6a8663757ec08c4256f178980677` (C1/C2/S1 merged: 116 entity/source
records, 225 claims). They use the root `timecheck.sqlite` from the real-seed build
above, not synthetic fixtures. Later seed/tooling merges may add rows or features;
the revision anchors the pasted outputs. The structural build and live build
compile the same authored claims; consult the report separately for archive
verification. JSON formatting is expanded for readability; row order is incidental.

### 1. From a watch: Seiko Presage

```sh
.venv/bin/timecheck query v_reference_calibers --where "reference_id = 'reference:seiko-srpb41j1'" --json
```

```json
[
  {
    "reference_id": "reference:seiko-srpb41j1",
    "caliber_id": "caliber:seiko-4r35",
    "grade": "unknown",
    "year_from": null,
    "year_to": null,
    "year_to_kind": "unknown",
    "year_from_sort": 9999,
    "claim_id": "clm-6gnbc5jd5g",
    "status": "verified",
    "disputed": 0,
    "contested": 0,
    "has_primary": 1
  }
]
```

The merged seed links SRPB41J1 to 4R35 with primary evidence. Its usage years and grade are unknown; no dates or grade should be inferred from those nulls.

Its shared DNA

```sh
.venv/bin/timecheck query v_shared_dna --where "reference_id = 'reference:seiko-srpb41j1'" --json
```

```json
[
  {
    "reference_id": "reference:seiko-srpb41j1",
    "other_reference_id": "reference:seiko-srpe43j1",
    "via_caliber_id": "caliber:seiko-4r35",
    "relation_path": "",
    "disputed": 0,
    "has_primary": 1
  }
]
```

The other seeded reference uses the identical caliber, so `relation_path` is empty. This revision contains two Presage hosts, not the full set of Seiko lines or every watch using 4R35. The query will find additional hosts as evidenced claims are merged.

### 2. Vintage buyer: Omega Seamaster

```sh
.venv/bin/timecheck query v_reference_calibers --where "reference_id = 'reference:omega-st-166-0002'" --json
```

```json
[
  {
    "reference_id": "reference:omega-st-166-0002",
    "caliber_id": "caliber:omega-562",
    "grade": "unknown",
    "year_from": null,
    "year_to": null,
    "year_to_kind": "unknown",
    "year_from_sort": 9999,
    "claim_id": "clm-gi5xon4oe5",
    "status": "verified",
    "disputed": 0,
    "contested": 0,
    "has_primary": 1
  },
  {
    "reference_id": "reference:omega-st-166-0002",
    "caliber_id": "caliber:omega-565",
    "grade": "unknown",
    "year_from": null,
    "year_to": null,
    "year_to_kind": "unknown",
    "year_from_sort": 9999,
    "claim_id": "clm-bwrqjhmp6j",
    "status": "verified",
    "disputed": 0,
    "contested": 0,
    "has_primary": 1
  }
]
```

ST 166.0002 has two primary-supported caliber claims. Unknown usage bounds mean these do not establish a changeover year or which movement a particular specimen contains; they also do not establish an overlapping conflict. Preserve both rows. This query answers documented caliber usage, not parts interchange or servicing availability.

The documented Omega calibers' families

```sh
.venv/bin/timecheck query v_caliber_family --where "caliber_id IN ('caliber:omega-562','caliber:omega-565')" --json
```

```json
[]
```

Neither caliber currently has a selected `derived_from`, `clone_of` or `grade_of`
path in the merged seed. This empty family result describes the graph's sourced
relations; it does not establish that the movements have no relatives. Family
queries return connected calibers, while shared-DNA queries below return other
watch references.

What else shares those Omega calibers?

```sh
.venv/bin/timecheck query v_shared_dna --where "reference_id = 'reference:omega-st-166-0002'" --json
```

```json
[]
```

No other host is currently connected in this merged seed. An empty result means missing graph coverage, not proof that the calibers were exclusive to this reference.

### 3. Submariner lineage and changes

```sh
.venv/bin/timecheck query v_lineage --where "line_id = 'line:rolex-submariner' AND reference_id = 'reference:rolex-16610'" --json
```

```json
[
  {
    "line_id": "line:rolex-submariner",
    "reference_id": "reference:rolex-16610",
    "year_from": null,
    "year_to": null,
    "year_to_kind": "unknown",
    "year_from_sort": 9999,
    "caliber_id": "caliber:rolex-3135",
    "grade": "unknown",
    "succeeds_reference_id": "reference:rolex-168000",
    "claim_id": "clm-axqg2rbafk",
    "status": "verified",
    "disputed": 0,
    "contested": 0,
    "has_primary": 0
  }
]
```

16610 has a selected predecessor and caliber, but unknown usage years. Query the whole line by removing the reference condition. The guide below gives a sorted SQL form and keeps production dates separate from usage dates.

Compare the sourced succession

```sh
.venv/bin/timecheck query v_lineage_diff --where "reference_id = 'reference:rolex-16610' AND attribute IN ('caliber','power_reserve','years')" --json
```

```json
[
  {
    "line_id": "line:rolex-submariner",
    "reference_id": "reference:rolex-16610",
    "predecessor_id": "reference:rolex-168000",
    "attribute": "caliber",
    "before_value": null,
    "after_value": null,
    "changed": null,
    "before_status": null,
    "after_status": null,
    "before_evidence_id": null,
    "after_evidence_id": null
  },
  {
    "line_id": "line:rolex-submariner",
    "reference_id": "reference:rolex-16610",
    "predecessor_id": "reference:rolex-168000",
    "attribute": "power_reserve",
    "before_value": null,
    "after_value": null,
    "changed": null,
    "before_status": null,
    "after_status": null,
    "before_evidence_id": null,
    "after_evidence_id": null
  },
  {
    "line_id": "line:rolex-submariner",
    "reference_id": "reference:rolex-16610",
    "predecessor_id": "reference:rolex-168000",
    "attribute": "years",
    "before_value": null,
    "after_value": null,
    "changed": null,
    "before_status": null,
    "after_status": null,
    "before_evidence_id": null,
    "after_evidence_id": null
  }
]
```

The verified succession is present, but its usage intervals are unknown, so the diff deliberately returns `changed: null` and unknown values/evidence IDs. This is not a claim that nothing changed. Run without the attribute filter to see all twelve attributes. A known change comparison is exercised by the synthetic fixture build in `scripts/check.sh`; these real-seed rows remain honest about their gaps.

### 4. A-11 designation across makers

```sh
.venv/bin/timecheck query v_lineage --where "line_id = 'line:usaaf-a-11'" --json
```

```json
[]
```

Verified-only lineage is empty at this revision: the Elgin membership excerpt is a scan and remains proposed pending human attestation. Do not replace this with an unsupported maker relationship.

Include the pending membership

```sh
.venv/bin/timecheck query v_lineage --where "line_id = 'line:usaaf-a-11'" --include-proposed --json
```

```json
[
  {
    "line_id": "line:usaaf-a-11",
    "reference_id": "reference:elgin-a-11",
    "year_from": null,
    "year_to": null,
    "year_to_kind": "unknown",
    "year_from_sort": 9999,
    "caliber_id": "caliber:elgin-539",
    "grade": "unknown",
    "succeeds_reference_id": null,
    "claim_id": "clm-6rsds5usl7",
    "status": "verified",
    "disputed": 0,
    "contested": 0,
    "has_primary": 0
  }
]
```

Only Elgin is seeded here; Waltham/Bulova coverage is still pending. The row's `status: verified` describes its usage claim, while its included membership is proposed/manual. The side-by-side maker SQL below currently returns no rows: it requires a verified `made_by` claim, while Elgin 539's maker claim is proposed/manual. It will include makers when their supporting claims are verified. No multi-maker completion is implied.

### 5. Apply the evidence filter to the same query

```sh
.venv/bin/timecheck query v_lineage --where "line_id = 'line:usaaf-a-11'" --include-proposed --primary-only --json
```

```json
[
  {
    "line_id": "line:usaaf-a-11",
    "reference_id": "reference:elgin-a-11",
    "year_from": null,
    "year_to": null,
    "year_to_kind": "unknown",
    "year_from_sort": 9999,
    "caliber_id": null,
    "grade": null,
    "succeeds_reference_id": null,
    "claim_id": "clm-bpgsi66cc5",
    "status": "proposed",
    "disputed": 0,
    "contested": 0,
    "has_primary": 1
  }
]
```

The secondary-only caliber usage is removed. A primary-supported membership fallback remains, with null caliber and grade, its membership `claim_id`, and `status: proposed`. Primary support for membership cannot replace missing primary support for usage. The scan membership still needs human attestation; this fallback is not a verified movement assignment. This is the same designation query, with only `--primary-only` added.

A primary-supported result that survives

```sh
.venv/bin/timecheck query v_reference_calibers --where "reference_id = 'reference:omega-st-166-0002'" --primary-only --json
```

```json
[
  {
    "reference_id": "reference:omega-st-166-0002",
    "caliber_id": "caliber:omega-562",
    "grade": "unknown",
    "year_from": null,
    "year_to": null,
    "year_to_kind": "unknown",
    "year_from_sort": 9999,
    "claim_id": "clm-gi5xon4oe5",
    "status": "verified",
    "disputed": 0,
    "contested": 0,
    "has_primary": 1
  },
  {
    "reference_id": "reference:omega-st-166-0002",
    "caliber_id": "caliber:omega-565",
    "grade": "unknown",
    "year_from": null,
    "year_to": null,
    "year_to_kind": "unknown",
    "year_from_sort": 9999,
    "claim_id": "clm-bwrqjhmp6j",
    "status": "verified",
    "disputed": 0,
    "contested": 0,
    "has_primary": 1
  }
]
```

Both Omega usages survive. This repeats the vintage query with `--primary-only`; the added filter supplies no missing usage years or grade.

### How to read evidence

```sh
.venv/bin/timecheck query v_evidence --where "claim_id = 'clm-6gnbc5jd5g'" --json
```

```json
[
  {
    "claim_id": "clm-6gnbc5jd5g",
    "evidence_id": "ev-roiik57744",
    "source_id": "source:seiko-presage-srpb41j1-20260518",
    "tier": "primary",
    "match_mode": "exact",
    "quote": "Caliber Number 4R35 Movement Type Automatic with manual winding",
    "locator": "Specifications; Movement",
    "archive_url": "https://web.archive.org/web/20260518210242id_/https://www.seikowatches.com/us-en/products/presage/srpb41j1",
    "retrieved_at": "2026-10-08"
  }
]
```

Read the quote at its locator in the archived snapshot and check the original source/publisher/licence. The excerpt identifies the caliber in a specifications context; the build checks normalized presence, while review determines whether it supports this reference's claim. `retrieved_at` is not a production date. Raw `id_` snapshots may require decoding/decompression; preserve their raw bytes for the SHA-256. Never hash copied browser text as if it were the pinned response.

### SQL: sorted lineage, maker comparison and evidence joins

Use Python's SQLite client for ordering, projections and joins. This command
prints the full Submariner line, compares seeded A-11 makers, and follows the
Presage usage into its source and hash. It works without network; archive
verification is recorded separately in `report.json`.

```sh
.venv/bin/python - <<'PY'
import json
import sqlite3
with sqlite3.connect('file:timecheck.sqlite?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    queries = {
        'submariner': """
            SELECT reference_id, caliber_id, grade, year_from, year_to,
                   year_to_kind, succeeds_reference_id, disputed, has_primary
            FROM v_lineage WHERE line_id = 'line:rolex-submariner'
            ORDER BY year_from_sort, reference_id, caliber_id
        """,
        'a11_makers': """
            SELECT b.display_name AS maker, l.reference_id, l.caliber_id,
                   l.grade, l.status AS usage_status, l.has_primary
            FROM v_lineage_all l
            JOIN claim c ON c.subject_id = l.caliber_id AND c.predicate = 'made_by'
                         AND c.status = 'verified'
            JOIN claim_object o ON o.claim_id = c.id
            JOIN brand b ON b.id = o.entity_id
            WHERE l.line_id = 'line:usaaf-a-11'
            ORDER BY b.display_name, l.reference_id, l.caliber_id
        """,
        'presage_evidence': """
            SELECT r.reference_id, r.caliber_id, r.grade, r.claim_id,
                   e.evidence_id, e.tier, e.match_mode, e.quote, e.locator,
                   e.archive_url, e.retrieved_at, s.url, s.publisher,
                   s.licence, s.snapshot_sha256
            FROM v_reference_calibers r
            JOIN v_evidence e ON e.claim_id = r.claim_id
            JOIN source s ON s.id = e.source_id
            WHERE r.reference_id = 'reference:seiko-srpb41j1'
            ORDER BY e.evidence_id
        """,
        'rolex_production': """
            SELECT c.subject_id, y.year_from, y.year_to, y.year_to_kind,
                   c.status, c.disputed, e.quote, e.archive_url
            FROM claim c JOIN claim_years y ON y.claim_id = c.id
            JOIN v_evidence e ON e.claim_id = c.id
            WHERE c.predicate = 'produced' AND c.subject_id = 'reference:rolex-16610'
            ORDER BY y.year_from_sort, c.id, e.evidence_id
        """
    }
    for name, sql in queries.items():
        print(name)
        print(json.dumps([dict(row) for row in db.execute(sql)], indent=2))
PY
```

At the example revision, `a11_makers` returns `[]`: the SQL requires a verified
`made_by`, while the Elgin 539 maker claim (`clm-ha7amhj52a`) is proposed with
manual evidence awaiting human attestation. `v_lineage_all` includes proposed
membership, but does not change that SQL join's verified-maker requirement.
Inspect the pending maker evidence and membership separately:

```sh
.venv/bin/timecheck query v_evidence --where "claim_id = 'clm-ha7amhj52a'" --include-proposed --json
.venv/bin/timecheck query v_evidence --where "claim_id = 'clm-bpgsi66cc5'" --include-proposed --json
```

Both excerpts have `match_mode: manual` and government-document archive locators.
They are primary by source tier but not machine-matched or human-attested yet.

`v_reference_calibers.claim_id` joins evidence for usage, not every contributing
grade fact. For the latter, read `grade_of`, `grade_name` and `offers_grades` claims
on the target caliber. `v_lineage.claim_id` likewise does not represent all
membership/succession facts. For family/shared-DNA paths, inspect the intermediate
caliber relationship claims: `relation_path` lists predicates, not claim IDs.
Query their evidence by joining `claim` → `claim_object` → `v_evidence`, selecting
subjects/targets along the path. `v_lineage_diff` evidence IDs refer to each value,
not the succession edge; inspect the successor's `succeeds` evidence separately.
Use `_all` evidence when inspecting proposed contributing claims.

A source's primary tier is provenance, not a guarantee of interpretation or
completeness. Cite the source URL/publisher and retain the archived pin, quote,
locator and hash. Source reuse rights and third-party excerpt attribution still
apply; see [CONTRIBUTING.md](../CONTRIBUTING.md). Data is ODbL 1.0 + DbCL and code
MIT. No query fills a gap from agent memory.
