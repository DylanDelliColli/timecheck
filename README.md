# timecheck

timecheck is a provenance-first graph of wristwatch references and calibers. JSON
files in git compile into SQLite tables, six canonical views and a CLI for
programmers and agents. Every relationship and attribute is a claim with a source,
pinned archived snapshot, raw-byte hash, quote and locator. Competing claims,
unknown years, grades and review status stay visible.

The v1 seed covers Rolex Submariner, Seiko Presage, vintage Omega Seamaster,
ETA/Sellita hosts and the A-11 designation. Coverage varies by family; read the
build report and the [worked examples](docs/querying.md#worked-examples-on-the-merged-seed)
for current gaps. There is no frontend in v1.

## Build and query

Use Python 3.13 or newer. While v1 is being developed, clone `release/v1`
with an authorized GitHub SSH key:

```sh
GIT_SSH_COMMAND='ssh -o BatchMode=yes' git clone --branch release/v1 git@github.com:DylanDelliColli/timecheck.git
cd timecheck
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
scripts/check.sh
.venv/bin/timecheck build --strict --no-evidence --data-dir data
```

The check runs unit and real SQLite/CLI integration tests, verifies synthetic
fixture evidence without network, and validates the real seed structurally. The
last build writes `timecheck.sqlite` and `report.json` without fetching archives.
It preserves authored review statuses but leaves evidence `unchecked`: success
here does not mean archive bytes or quotes have just been verified.

### Worked example

Output reproduces the CLI and data at release commit
`19df33caf0dfca3062ef51997dde926e6a55eaea` (the base of this documentation update):

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

SRPB41J1 uses the documented 4R35; its usage years and grade remain unknown.
The worked examples also show its four other seeded hosts, ten Omega shared-DNA
routes, ETA/Sellita hosts across brands, and the A-11's three makers. Bulova and
Waltham appear in verified-only A-11 lineage; Elgin membership and its caliber's
maker claim remain proposed pending scan attestation. `year_source` distinguishes
usage intervals from production fallback, which cannot order multiple calibers.

Verify real evidence with network access:

```sh
.venv/bin/timecheck build --strict --data-dir data --cache-dir .cache/snapshots
```

Exit codes are 0 for success, 1 for warnings and 2 for errors. Inspect `report.json`
on failure; the previous SQLite output can remain on disk. Real snapshot bytes
belong in local caches and are never committed. Gzip/zstd captures are hashed
before decompression. PDF text matching is advisory; PDF/scan-only claims stay
proposed pending human attestation. `snapshot pin URL` requests an archive capture
and prints its raw-byte pin and hash. CI defines nightly full live verification at
04:17 UTC and manual dispatch on `release/v1`.

Read [Querying timecheck](docs/querying.md) for the ten-line agent quick start,
every table and view column, query/build flags, primary-only queries, evidence joins
and reproducible examples for the five v1 use cases. SQLite is accessible through
Python's standard library; a separate `sqlite3` executable is optional.

## Contribute and reuse

Contributions are pull requests. Start with [CONTRIBUTING.md](CONTRIBUTING.md):
source and reuse policy, schema conventions, proposed claims, evidence verification,
tests and DCO sign-off (`git commit -s`). Never enter a catalogue fact from memory.
For the current worker release, target `release/v1`.

Code is [MIT](LICENSE). Data under `data/` is [ODbL 1.0 with DbCL](data/LICENSE).
Third-party verification excerpts retain their attribution and rights. The
[PRD](docs/PRD.md), [v1 brief](docs/releases/v1.md) and
[design record](docs/releases/v1-design.md) explain the product and contracts.
