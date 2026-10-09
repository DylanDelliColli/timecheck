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

Use Python 3.13 or newer. While v1 is being developed, clone `release/v1` (the
repository is public; clone over HTTPS or with an authorized GitHub SSH key):

```sh
GIT_SSH_COMMAND='ssh -o BatchMode=yes' git clone --branch release/v1 git@github.com:DylanDelliColli/timecheck.git
cd timecheck
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
scripts/check.sh
.venv/bin/timecheck build --strict --no-evidence --data-dir data
.venv/bin/timecheck query v_reference_calibers --where "reference_id = 'reference:seiko-srpb41j1'" --json
```

The check runs unit and real SQLite/CLI integration tests, verifies synthetic
fixture evidence without network, and validates the real seed structurally. The
last build writes `timecheck.sqlite` and `report.json` without fetching archives.
It preserves authored review statuses but leaves evidence `unchecked`: success
here does not mean archive bytes or quotes have just been verified.

Verify real evidence with network access:

```sh
.venv/bin/timecheck build --strict --data-dir data --cache-dir .cache/snapshots
```

Exit codes are 0 for success, 1 for warnings and 2 for errors. Inspect `report.json`
on failure; the previous SQLite output can remain on disk. Real snapshot bytes
belong in local caches and are never committed.

Read [Querying timecheck](docs/querying.md) for the ten-line agent quick start,
every table and view column, all CLI flags, primary-only queries, evidence joins
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
