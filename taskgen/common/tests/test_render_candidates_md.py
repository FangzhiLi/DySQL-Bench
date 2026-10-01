# tests/test_render_candidates_md.py
import csv, importlib.util, os
spec = importlib.util.spec_from_file_location("render_candidates_md", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "render_candidates_md.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def _csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0])); w.writeheader(); w.writerows(rows)

ROW = dict(n_fks_declared=14, n_fks_inferred=0, n_fks_valid=14, invalid_fks="", long_text_cols="")

def test_render_counts_anchor_types_and_lists_anchors(tmp_path):
    cand, notes = tmp_path / "c.csv", tmp_path / "n.csv"
    _csv(cand, [
        {**ROW, "source": "bird", "split": "train", "db": "books", "n_tables": 15, "n_cols": 50, "total_rows": 84337,
         "size_mb": 4.1, "has_person_named": "True", "anchor_kinds": "entity; person_named",
         "person_anchors": "customer[first_name,last_name]; author[author_name]",
         "entity_anchors": "book[title]; publisher[publisher_name]; country[country_name]; cust_order[]"},
        {**ROW, "source": "spider2", "split": "test", "db": "Airlines", "n_tables": 8, "n_cols": 40, "total_rows": 1000,
         "size_mb": 30.0, "has_person_named": "False", "anchor_kinds": "entity", "person_anchors": "",
         "entity_anchors": "flights[]", "long_text_cols": "boarding_passes.seat_no"}])
    _csv(notes, [{"source": "bird", "db": "books", "topic": "网上书店订单", "note": "customer 2,000 人", "entity_anchors_ok": ""},
                 {"source": "spider2", "db": "Airlines", "topic": "", "note": "", "entity_anchors_ok": "flights"}])
    md = mod.render(str(cand), str(notes))
    assert "| BIRD | 1 | 1 | 0 | 0 |" in md and "| Spider2-lite（SQLite） | 1 | 0 | 0 | 1 |" in md
    assert "| **合计** | **2** | **1** | **0** | **1** |" in md
    assert "## BIRD（1 个）" in md and "| books | train | 网上书店订单 | 15 | 50 | 84,337 | 4.1 | 14/14/0 |" in md
    assert "customer[first_name,last_name], author[author_name]" in md
    assert "book[title], publisher[publisher_name], country[country_name] 等 4 个" in md
    assert "| Airlines | test |  |" in md and "boarding_passes.seat_no | 确认锚点：flights |" in md
