#!/usr/bin/env python3
"""Render docs/data_gen/candidate_dbs.md from the selector CSV plus hand-written topics/notes (db_notes.csv).
Usage (from DySQL-Bench/):
  python scripts/render_candidates_md.py ../docs/data_gen/candidate_dbs.csv ../docs/data_gen/db_notes.csv \
    > ../docs/data_gen/candidate_dbs.md"""
import csv, sys

SOURCES = {"bird": "BIRD", "spider2": "Spider2-lite（SQLite）", "spider1": "Spider 1.0", "synsql": "SynSQL"}
HEAD = ("| 数据库 | 划分 | 主题 | 表 | 列 | 总行数 | MB | FK 有效/声明/推断 | 人物锚点（姓名列） | 实体锚点（名称列） "
        "| 无效外键 | 长文本列 | 备注 |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def _items(s):
    return [x for x in (s or "").split("; ") if x]


def _list(s, limit=None):
    xs = _items(s)
    if limit and len(xs) > limit:
        return ", ".join(xs[:limit]) + f" 等 {len(xs)} 个"
    return ", ".join(xs)


def _kind(r):
    kinds = set(_items(r["anchor_kinds"]))
    return "named" if r["has_person_named"] == "True" else ("id_only" if "person_id_only" in kinds else "entity")


def render(candidates_csv, notes_csv):
    rows = list(csv.DictReader(open(candidates_csv, encoding="utf-8")))
    notes = {(n["source"], n["db"]): n for n in csv.DictReader(open(notes_csv, encoding="utf-8"))}
    out = [f"# 候选库清单（{len(rows)} 个）\n",
           "由 `DySQL-Bench/scripts/render_candidates_md.py` 从 `docs/data_gen/candidate_dbs.csv`（筛选器输出）和 "
           "`docs/data_gen/db_notes.csv`（人工主题与备注）生成，不要手改。规则见 `docs/2026-09-24-data-gen-db-selection.md`。\n",
           "锚点写作 `表[姓名或名称列]`。人物锚点里有姓名列的是带名字的人，方括号为空的是只有 ID 的人；"
           "实体锚点按 有名称列 > 下游表多 > 行数多 排序，只列前 3 个。\n",
           "| 来源 | 候选数 | 有带名字的人物锚点 | 只有 ID 的人物锚点 | 只有实体锚点 |", "|---|---|---|---|---|"]
    tot = [0, 0, 0, 0]
    for s, label in SOURCES.items():
        rs = [r for r in rows if r["source"] == s]
        if not rs:
            continue
        k = [_kind(r) for r in rs]
        c = [len(rs), k.count("named"), k.count("id_only"), k.count("entity")]
        tot = [a + b for a, b in zip(tot, c)]
        out.append(f"| {label} | " + " | ".join(map(str, c)) + " |")
    out.append("| **合计** | " + " | ".join(f"**{x}**" for x in tot) + " |\n")
    for s, label in SOURCES.items():
        rs = [r for r in rows if r["source"] == s]
        if not rs:
            continue
        out.append(f"## {label}（{len(rs)} 个）\n\n{HEAD}")
        for r in rs:
            n = notes.get((s, r["db"]), {})
            note = n.get("note", "")
            if n.get("entity_anchors_ok"):
                note = (note + "；" if note else "") + f"确认锚点：{n['entity_anchors_ok']}"
            out.append(f"| {r['db']} | {r['split']} | {n.get('topic', '')} | {r['n_tables']} | {r['n_cols']} | "
                       f"{int(r['total_rows']):,} | {r['size_mb']} | "
                       f"{r['n_fks_valid']}/{r['n_fks_declared']}/{r['n_fks_inferred']} | "
                       f"{_list(r['person_anchors'])} | {_list(r['entity_anchors'], 3)} | {_list(r['invalid_fks'])} | "
                       f"{_list(r['long_text_cols'])} | {note} |")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.write(render(sys.argv[1], sys.argv[2]))
