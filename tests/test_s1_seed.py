"""Exercise the declared Submariner seed through its real SQLite and CLI interfaces."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from timecheck.build import build


@pytest.fixture(scope="module")
def submariner_seed(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path_factory.mktemp("submariner-seed")
    database = output / "seed.sqlite"
    code, report = build(data_dir=root / "data", out=database,
                         report=output / "report.json", strict=True,
                         no_evidence=True)
    assert code == 0, (report["errors"], report["warnings"])
    targets = json.loads((root / "data/targets/rolex-submariner.json").read_text())
    return database, set(targets["references"]), report


def test_submariner_targets_have_queryable_movements_and_evidence(submariner_seed):
    database, targets, report = submariner_seed
    with sqlite3.connect(database) as db:
        members = {row[0] for row in db.execute(
            "SELECT reference_id FROM v_lineage_all "
            "WHERE line_id = 'line:rolex-submariner'")}
        movements = {row[0] for row in db.execute(
            "SELECT reference_id FROM v_reference_calibers_all")}
        assert targets <= members & movements
        assert {row[0] for row in db.execute(
            "SELECT caliber_id FROM v_reference_calibers_all "
            "WHERE reference_id = 'reference:rolex-5512'")} >= {
                "caliber:rolex-1530", "caliber:rolex-1560", "caliber:rolex-1570"}
        assert {row[0] for row in db.execute(
            "SELECT caliber_id FROM v_reference_calibers_all "
            "WHERE reference_id = 'reference:rolex-5513'")} >= {
                "caliber:rolex-1530", "caliber:rolex-1520"}
        assert {row[0] for row in db.execute(
            "SELECT y.year_from FROM claim c "
            "JOIN claim_years y ON y.claim_id = c.id "
            "WHERE c.subject_id = 'reference:rolex-14060m' "
            "AND c.predicate = 'produced'")} >= {1999, 2002}
        assert db.execute("SELECT COUNT(*) FROM v_evidence_all").fetchone()[0] == report["evidence_count"]


def test_6200_production_occurrence_does_not_define_bounds(submariner_seed):
    database, _, _ = submariner_seed
    with sqlite3.connect(database) as db:
        intervals = db.execute(
            "SELECT y.year_from, y.year_to FROM claim c "
            "JOIN claim_years y ON y.claim_id = c.id "
            "WHERE c.subject_id = 'reference:rolex-6200' "
            "AND c.predicate = 'produced'").fetchall()
    # The table explicitly gives a production interval in 1955. The prose
    # reports production during 1954, without identifying either boundary.
    assert intervals == [(1955, 1955)]


def test_submariner_cli_can_show_proposed_history(submariner_seed):
    database, _, _ = submariner_seed
    command = [sys.executable, "-m", "timecheck", "query",
               "v_reference_calibers", "--db", str(database), "--where",
               "reference_id = 'reference:rolex-5512'", "--json"]
    default = subprocess.run(command, capture_output=True, text=True, check=True)
    assert all(row["status"] == "verified" for row in json.loads(default.stdout))
    inclusive = subprocess.run(command + ["--include-proposed"],
                               capture_output=True, text=True, check=True)
    assert {row["caliber_id"] for row in json.loads(inclusive.stdout)} >= {
        "caliber:rolex-1530", "caliber:rolex-1560", "caliber:rolex-1570"}


@pytest.mark.parametrize('view', ['v_lineage_diff', 'v_lineage_diff_all'])
def test_submariner_diff_requires_sourced_caliber_order(submariner_seed, view):
    database, _, _ = submariner_seed
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        ambiguous = db.execute(
            f"SELECT * FROM {view} WHERE predecessor_id = 'reference:rolex-5513' "
            "AND reference_id = 'reference:rolex-5514'").fetchall()
        assert len(ambiguous) == 12
        assert all(row['changed'] is None for row in ambiguous)
        caliber, = [row for row in ambiguous if row['attribute'] == 'caliber']
        assert caliber['before_value'] is None and caliber['after_value'] is None
        modern, = db.execute(
            f"SELECT * FROM {view} WHERE predecessor_id = 'reference:rolex-114060' "
            "AND reference_id = 'reference:rolex-124060' AND attribute = 'caliber'").fetchall()
        assert (modern['before_value'], modern['after_value'], modern['changed']) == (
            'caliber:rolex-3130', 'caliber:rolex-3230', 1)
