# tests/test_select_dbs_cli.py
import csv, json, os, subprocess, sys
from tests._sqlite_fixtures import make_db, WWE

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "select_dbs.py")

def test_cli_applies_fk_extra_and_writes_split_path_and_anchor_json(tmp_path):
    db = make_db(tmp_path, "wwe", WWE)
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"spider2:wwe": [
        {"table": "Matches", "cols": ["champion"], "ref_table": "Wrestlers", "ref_cols": ["id"]}]}))
    out, cand, anc = tmp_path / "all.csv", tmp_path / "cand.csv", tmp_path / "anchors.json"
    subprocess.run([sys.executable, SCRIPT, "--source", f"spider2={db}", "--fk-extra", str(extra), "--out", str(out),
                    "--candidates", str(cand), "--anchors-json", str(anc), "--workers", "1"],
                   check=True, capture_output=True)
    r = next(csv.DictReader(open(out)))
    assert r["pass"] == "True" and r["split"] == "test" and r["path"] == db
    assert r["n_fks_inferred"] == "4"   # card_id by name, winner_id/loser_id by value, champion from --fk-extra
    anchors = json.load(open(anc))
    assert list(anchors) == ["spider2:wwe"]
    rec = anchors["spider2:wwe"]
    assert rec["source"] == "spider2" and rec["db"] == "wwe" and rec["path"] == db
    w = next(a for a in rec["anchors"] if a["table"] == "Wrestlers")
    assert w["kind"] == "person_named" and w["down"] == ["Matches"]
    edges = {(f["table"], f["col"], f["ref_table"], f["ref_col"]) for f in rec["fks"]}
    assert ("Matches", "champion", "Wrestlers", "id") in edges     # from --fk-extra
    assert ("Matches", "winner_id", "Wrestlers", "id") in edges    # inferred by value
    assert all(f["hit"] is None or f["hit"] >= 0.3 for f in rec["fks"])
