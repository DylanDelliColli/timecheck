# Querying timecheck

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/timecheck build --strict
.venv/bin/timecheck query v_reference_calibers --json
```

The build reads `data/`, writes `timecheck.sqlite` and `report.json`, and verifies
pinned archive evidence. Exit 0 means success, 1 warnings, 2 errors. Offline mode
never fetches; `--snapshot-dir DIR` reads only `DIR/<sha256>.bin`. Add `--data-dir`
to choose another data tree, `--out` / `--report` for isolated outputs, or
`--cache-dir` for a persistent hash-verified archive byte cache. `--only-changed`
restricts evidence checks to claims in those files; schemas and integrity always
check the whole graph. Supplying zero changed paths skips all evidence checks.
`--no-evidence` validates schemas and integrity, compiles SQLite and writes a report
with every evidence item marked `unchecked`; it never fetches or verifies quotes.
This mode supports the offline structural check of real seed files. Use live strict
builds to verify their evidence.

| View | Question |
|---|---|
| `v_reference_calibers` | What calibers and grades did a reference use, and when? Filter `caliber_id` for the inverse. |
| `v_caliber_family` | What bases, derivatives, clones and grades are connected within six edges? |
| `v_shared_dna` | What other references use the same caliber or a related one? |
| `v_lineage` | What references belong to a line, with calibers and sourced predecessors? |
| `v_lineage_diff` | What documented attributes differ across verified succession edges? |
| `v_evidence` | What quoted, pinned evidence supports a claim? |

Use `query VIEW --where "reference_id = 'reference:example'" --db PATH --json`.
`--include-proposed` selects the corresponding `_all` view. `--primary-only`
recomputes the query over primary-supported claims and edges; evidence queries then
show primary evidence only. SQL filters are for trusted local queries. Invalid view
names or SQL return exit 2. Query output is always a JSON array, even when empty.

Views do not impose ordering. Consumers can query SQLite directly for `ORDER BY`.
Years are inclusive: `year_from` and `year_to` can be null, `year_to_kind` distinguishes
`year`, `present` and `unknown`, and `year_from_sort` maps null starts to 9999.
Grades distinguish a documented name, `none` and `unknown`. Disputed and contested
claims remain visible. Missing diff values or unknown years produce `changed: null`.
Check the report for branches, missing coverage, manual attestations and family
truncation. The fixed column definitions are in `docs/releases/v1-design.md`.

For a reproducible synthetic example without external network:

```sh
.venv/bin/timecheck build --strict --data-dir tests/fixtures/data --snapshot-dir tests/snapshots --out build/example.sqlite --report build/example-report.json
.venv/bin/timecheck query v_lineage --db build/example.sqlite --json
.venv/bin/timecheck query v_lineage_diff --db build/example.sqlite --json
.venv/bin/timecheck query v_shared_dna --db build/example.sqlite --json
```

`timecheck id new claim` / `id new evidence` mint IDs; `snapshot hash FILE` hashes
raw bytes. `snapshot pin URL` is reserved for E1 network capture tooling.
Worked seed queries and the agent walkthrough will be expanded by D1.
