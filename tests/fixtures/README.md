# Synthetic graph fixtures

All names, claims and snapshot pages here were authored by this project; they contain
no real watch facts. The fixture has one brand, one line, three references (Beta
succeeds Alpha), two ungraded calibers and one grade entity, with a synthetic primary
source. SHA-named snapshot bytes live in `tests/snapshots/`.

Negative fixtures are independent temporary copies of `data/`, changed by the
parameterized tests in `test_integration.py` and `test_integrity.py`. They exercise:

| Fixture | Expected class or result |
|---|---|
| no_evidence | evidence_missing |
| quote_absent | quote_not_found |
| hash_mismatch | snapshot_hash_mismatch |
| unresolved | unresolved_slug |
| duplicate | duplicate_id |
| cycle | succeeds_cycle |
| overlapping uses_caliber | build succeeds; both claims disputed |
| absence | explicit_absence_required |

Other cases cover unknown years, competing attributes/grade names, branches, manual
proposals, evidence IDs, vocabularies, source policy, domain cap and primary graph
filtering. The tests invoke the real CLI/build, then query the resulting SQLite.
