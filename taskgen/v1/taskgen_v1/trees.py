# taskgen/v1/taskgen_v1/trees.py
"""Anchor trees: for one anchor row, the rows in its scope. Down tables are reached by joining FK edges
(two hops go through the intermediate table); up tables hold the parent rows the tree references
(the 'public' data a task may also edit). The scope recomputed from the edges must equal the anchor record."""
import json, sqlite3
from collections import deque
from taskgen_common.db_select import _q
from taskgen_common.db_anchor import reachable_down, parents


def fk_edges(fks):
    """down: parent -> [(child, child_col, parent_col)]; up: child -> [(child_col, parent, parent_col)]."""
    down, up = {}, {}
    for f in fks:
        if f["table"] == f["ref_table"]:
            continue
        down.setdefault(f["ref_table"], []).append((f["table"], f["col"], f["ref_col"]))
        up.setdefault(f["table"], []).append((f["col"], f["ref_table"], f["ref_col"]))
    return down, up


def check_scope(anchor, fks, composite=(), max_hops=2):
    """Composite (multi-column) FKs count for the scope like the selector counted them; trees only join
    single-column edges, so parents reached only through a composite FK get no rows in the tree."""
    edges = [{"table": f["table"], "ref_table": f["ref_table"]} for f in list(fks) + list(composite)]
    down = reachable_down(edges, anchor["table"], max_hops)
    up = parents(edges, [anchor["table"]] + down)
    if sorted(down) != sorted(anchor["down"]) or sorted(up) != sorted(anchor["up"]):
        raise ValueError(f"{anchor['table']}: scope from fks down={sorted(down)} up={sorted(up)} "
                         f"!= record down={sorted(anchor['down'])} up={sorted(anchor['up'])}")


def _safe(v):
    return f"<blob {len(v)} bytes>" if isinstance(v, (bytes, memoryview)) else v


def _rows(c, sql, params=()):
    cur = c.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [{k: _safe(v) for k, v in zip(cols, r)} for r in cur.fetchall()]


def _in(c, table, col, values):
    out = []
    for i in range(0, len(values), 500):
        chunk = values[i:i + 500]
        out += _rows(c, f'SELECT * FROM {_q(table)} WHERE {_q(col)} IN ({",".join("?" * len(chunk))})', chunk)
    return out


def anchor_key_values(c, anchor, fks, rng, n):
    """Key values of anchor rows with at least one direct child row; every row when the anchor has no down table."""
    down_e, _ = fk_edges(fks)
    kids = [(child, ccol) for child, ccol, pcol in down_e.get(anchor["table"], [])
            if child in anchor["down"] and pcol == anchor["key"]]
    key = _q(anchor["key"])
    if kids:
        sub = " UNION ".join(f"SELECT {_q(ccol)} FROM {_q(child)}" for child, ccol in kids)
        sql = f"SELECT {key} FROM {_q(anchor['table'])} WHERE {key} IN ({sub})"
    else:
        sql = f"SELECT {key} FROM {_q(anchor['table'])}"
    vals = [r[0] for r in c.execute(sql) if r[0] is not None]
    rng.shuffle(vals)
    return vals[:n]


def build_tree(c, anchor, fks, key_value, rng, max_down=15, max_up=3):
    down_e, up_e = fk_edges(fks)
    root = _rows(c, f"SELECT * FROM {_q(anchor['table'])} WHERE {_q(anchor['key'])} = ?", (key_value,))
    if not root:
        return None
    row = root[0]
    tree = {"anchor_table": anchor["table"], "anchor_key": anchor["key"], "key_value": key_value,
            "anchor_name": " ".join(str(row[n]) for n in anchor["names"] if n in row and row[n] not in (None, "")),
            "anchor_row": row, "down": {}, "up": {}}
    frontier, seen = deque([(anchor["table"], [row])]), {anchor["table"]}
    while frontier:
        t, trows = frontier.popleft()
        for child, ccol, pcol in down_e.get(t, []):
            if child in seen or child not in anchor["down"]:
                continue
            vals = sorted({r[pcol] for r in trows if r.get(pcol) not in (None, "")}, key=str)
            got = _in(c, child, ccol, vals) if vals else []
            if len(got) > max_down:
                got = rng.sample(got, max_down)
            if got:
                tree["down"][child] = got
                seen.add(child)
                frontier.append((child, got))
    for t, trows in [(anchor["table"], [row])] + list(tree["down"].items()):
        for ccol, parent, pcol in up_e.get(t, []):
            if parent not in anchor["up"]:
                continue
            vals = sorted({r[ccol] for r in trows if r.get(ccol) not in (None, "")}, key=str)[:max_up]
            if vals:
                tree["up"].setdefault(parent, []).extend(_in(c, parent, pcol, vals))
    for p, rs in tree["up"].items():
        uniq = {json.dumps(r, sort_keys=True, default=str): r for r in rs}
        tree["up"][p] = list(uniq.values())[:max_up]
    return tree


def open_ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
