"""A-11 cross-maker journeys through the real seed build and CLI."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from timecheck.build import build


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = {"reference:" + maker + "-a-11"
              for maker in ("elgin", "waltham", "bulova")}


@pytest.fixture(scope="module")
def a11_seed(tmp_path_factory):
    output = tmp_path_factory.mktemp("a11-seed")
    database = output / "seed.sqlite"
    code, report = build(data_dir=ROOT / "data", out=database,
                         report=output / "report.json", strict=True,
                         no_evidence=True)
    assert code == 0, (report["errors"], report["warnings"])
    return database, report


def test_a11_designation_finds_three_distinct_maker_movements(a11_seed):
    database, _ = a11_seed
    with sqlite3.connect(database) as db:
        rows = db.execute(
            "SELECT l.reference_id, u.caliber_id, m.entity_id, u.grade "
            "FROM v_lineage_all l "
            "JOIN v_reference_calibers_all u ON u.reference_id=l.reference_id "
            "JOIN selected_claim_all m ON m.subject_id=u.caliber_id "
            "AND m.predicate='made_by' WHERE l.line_id='line:usaaf-a-11'"
        ).fetchall()
    assert {r[0] for r in rows} == REFERENCES
    assert len({r[1] for r in rows}) == 3
    assert {r[2] for r in rows} == {"brand:elgin", "brand:waltham", "brand:bulova"}
    assert all(r[3] == "unknown" for r in rows)


def test_a11_cli_exposes_evidence_and_unknown_usage_years(a11_seed):
    database, _ = a11_seed
    result = subprocess.run(
        [sys.executable, "-m", "timecheck", "query", "v_lineage", "--db",
         str(database), "--where", "line_id='line:usaaf-a-11'",
         "--include-proposed", "--json"],
        capture_output=True, text=True, check=True)
    rows = json.loads(result.stdout)
    assert {r["reference_id"] for r in rows} == REFERENCES
    with sqlite3.connect(database) as db:
        for reference in REFERENCES:
            uses = db.execute(
                "SELECT u.year_from, u.year_to, e.quote, e.archive_url "
                "FROM v_reference_calibers_all u JOIN v_evidence_all e "
                "ON e.claim_id=u.claim_id WHERE u.reference_id=?", (reference,)
            ).fetchall()
            assert uses
            assert all(first is None and last is None and len(quote) >= 20
                       and "id_/" in archive for first, last, quote, archive in uses)


def test_a11_target_keeps_unattested_coverage_visible(a11_seed):
    database, report = a11_seed
    target = json.loads((ROOT / "data/targets/usaaf-a-11.json").read_text())
    assert set(target["references"]) == REFERENCES
    assert target["source"]
    coverage = report["coverage"]["line:usaaf-a-11"]
    assert coverage["target"] == 3
    with sqlite3.connect(database) as db:
        visible = {r[0] for r in db.execute(
            "SELECT reference_id FROM v_lineage "
            "WHERE line_id='line:usaaf-a-11' AND caliber_id IS NOT NULL")}
    assert coverage["covered"] == len(visible)
    assert set(coverage["missing"]) == REFERENCES - visible
    # Elgin membership still needs human attestation of the government scan.
    assert "reference:elgin-a-11" in coverage["missing"]
    assert report["pending_attestations"]


def test_a11_claims_do_not_invent_grade_absence():
    paths = [ROOT / "data/references" / (maker + "-a-11.json")
             for maker in ("waltham", "bulova")]
    paths += [ROOT / "data/calibers" / name for name in
              ("waltham-a-11-6-0.json", "bulova-10ak-csh.json")]
    for path in paths:
        doc = json.loads(path.read_text())
        assert doc["claims"]
        for claim in doc["claims"]:
            assert claim["predicate"] != "offers_grades"
            for evidence in claim["evidence"]:
                source = json.loads((ROOT / "data/sources" /
                                     (evidence["source"].split(":")[1] + ".json")).read_text())
                if source["content_type"] == "image_scan":
                    assert evidence["match_mode"] == "manual"
