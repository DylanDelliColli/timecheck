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
