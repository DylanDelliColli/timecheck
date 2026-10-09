"""Seiko seed journeys through the real build, SQLite views and CLI."""
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys

import pytest

from timecheck.build import build


@pytest.fixture(scope="module")
def seiko_seed(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path_factory.mktemp("seiko-seed")
    database = output / "seed.sqlite"
    code, report = build(data_dir=root / "data", out=database,
                         report=output / "report.json", strict=True,
                         no_evidence=True)
    assert code == 0, (report["errors"], report["warnings"])
    return database, report


def test_presage_shares_documented_calibers_across_lines(seiko_seed):
    database, _ = seiko_seed
    with sqlite3.connect(database) as db:
        for caliber in ("seiko-6r35", "seiko-6l35"):
            lines = {row[0] for row in db.execute(
                "SELECT DISTINCT l.line_id FROM v_reference_calibers_all u "
                "JOIN v_lineage_all l ON l.reference_id=u.reference_id "
                "WHERE u.caliber_id = ?", ("caliber:" + caliber,))}
            assert "line:seiko-presage" in lines
            assert len(lines) >= 2
        assert db.execute("SELECT COUNT(*) FROM v_reference_calibers_all "
                          "WHERE caliber_id = 'caliber:seiko-4r36'").fetchone()[0] > 0


def test_seiko_target_and_unknowns_are_visible(seiko_seed):
    database, report = seiko_seed
    assert report["coverage"]["line:seiko-presage"]["target"] > 2
    root = Path(__file__).resolve().parents[1]
    targets = json.loads((root / "data/targets/seiko-presage.json").read_text())["references"]
    assert {"reference:seiko-srpb41j1", "reference:seiko-srpe43j1",
            "reference:seiko-srpb43", "reference:seiko-spb165j1"} <= set(targets)
    with sqlite3.connect(database) as db:
        rows = db.execute("SELECT u.grade, u.year_from, u.year_to, e.evidence_id "
                          "FROM v_reference_calibers_all u JOIN v_evidence_all e "
                          "ON e.claim_id = u.claim_id "
                          "WHERE u.caliber_id = 'caliber:seiko-6l35'").fetchall()
        assert rows
        assert all(grade == "unknown" and first is None and last is None and evidence
                   for grade, first, last, evidence in rows)


def test_seiko_cli_primary_filter_keeps_cross_line_hosts(seiko_seed):
    database, _ = seiko_seed
    command = [sys.executable, "-m", "timecheck", "query", "v_reference_calibers",
               "--db", str(database), "--where", "caliber_id = 'caliber:seiko-6r35'",
               "--include-proposed", "--primary-only", "--json"]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    rows = json.loads(result.stdout)
    assert len(rows) >= 2
    assert all(row["has_primary"] == 1 for row in rows)


def test_pilot_watch_finds_new_cocktail_time_hosts(seiko_seed):
    database, _ = seiko_seed
    with sqlite3.connect(database) as db:
        hosts = {row[0] for row in db.execute(
            "SELECT other_reference_id FROM v_shared_dna_all "
            "WHERE reference_id = 'reference:seiko-srpb41j1' "
            "AND via_caliber_id = 'caliber:seiko-4r35'")}
    assert {"reference:seiko-srpb43", "reference:seiko-srpb46",
            "reference:seiko-srpe45j1"} <= hosts


def test_seiko_installation_does_not_establish_a_maker(seiko_seed):
    database, _ = seiko_seed
    with sqlite3.connect(database) as db:
        rows = db.execute(
            "SELECT DISTINCT u.caliber_id, m.entity_id "
            "FROM v_reference_calibers_all u "
            "LEFT JOIN selected_claim_all m "
            "ON m.subject_id=u.caliber_id AND m.predicate='made_by' "
            "WHERE u.caliber_id IN ('caliber:seiko-4r36', 'caliber:seiko-6l35', "
            "'caliber:seiko-6r21', 'caliber:seiko-6r35', 'caliber:seiko-6r38')"
        ).fetchall()
    assert len(rows) == 5
    assert all(maker is None for _, maker in rows)


def test_presage_coverage_counts_delivered_regional_references(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "data"
    shutil.copytree(root / "data", data)
    # Simulate review only in the temporary accounting fixture. Repository
    # claims stay proposed; this does not attest the source or promote data.
    for path in (data / "references").glob("seiko-*.json"):
        doc = json.loads(path.read_text())
        if not any(c["predicate"] == "in_line" and
                   c["object"]["entity"] == "line:seiko-presage"
                   for c in doc["claims"]):
            continue
        for claim in doc["claims"]:
            if claim["predicate"] in ("in_line", "uses_caliber"):
                claim["status"] = "verified"
                claim["review"] = {"by": "synthetic-accounting-fixture",
                                   "at": "2026-10-09T00:00:00Z"}
        path.write_text(json.dumps(doc))
    code, report = build(data_dir=data, out=tmp_path / "graph.sqlite",
                         report=tmp_path / "report.json", strict=True,
                         no_evidence=True)
    assert code == 0, (report["errors"], report["warnings"])
    coverage = report["coverage"]["line:seiko-presage"]
    assert coverage["target"] == 108
    assert coverage["covered"] == 6
    assert not {"reference:seiko-srpb43", "reference:seiko-srpb46"} & set(coverage["missing"])
    with sqlite3.connect(tmp_path / "graph.sqlite") as db:
        for model in ("srpb43", "srpb46"):
            aliases = json.loads(db.execute(
                "SELECT aliases FROM reference WHERE id=?",
                ("reference:seiko-" + model,)).fetchone()[0])
            assert "reference:seiko-" + model + "j1" in aliases
