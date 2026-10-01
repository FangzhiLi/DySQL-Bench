# taskgen/v2/taskgen_v2/trees.py
"""Event trees (design §4.2): for one root row, its event records as the profile defines them, each event row with the
parent rows it actually references nested under it (purchase -> product -> brand), and the root's own parent rows and
1:1 attributes. Every row carries its owner label (owners.Tracer), the same label the execution check computes."""
import json, sqlite3
from taskgen_common.db_select import _q
from taskgen_v2 import db_profile

MAX_EVENTS = 30   # event rows kept per tree; the prompt shows 3-12 of them
MAX_DEPTH = 4     # levels of parent rows under an event


def _safe(v):
    return f"<blob {len(v)} bytes>" if isinstance(v, (bytes, memoryview)) else v


def _rows(c, sql, params=()):
    cur = c.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [{k: _safe(v) for k, v in zip(cols, r)} for r in cur.fetchall()]


def root_key_values(conn, profile, root, rng, n=None):
    """Key values of up to n root rows in sampling order: rows with at least one event first, then the others (each
    part shuffled), so a small database still gives n trees (hr_1: 7 of 107 employees have job_history rows)."""
    t, key = root["table"], profile["persons"][root["table"]]["key"]
    with_events = set()
    for e in (db_profile.parse_edge(ev["path"][0]) for ev in profile["events"]):
        if e.parent == t:
            sub = f"SELECT {', '.join(_q(c) for c in e.cols)} FROM {_q(e.child)}"
            ref = ", ".join(_q(c) for c in e.ref_cols)
            with_events |= {r[0] for r in conn.execute(f"SELECT {_q(key)} FROM {_q(t)} WHERE ({ref}) IN ({sub})")}
    every = [r[0] for r in conn.execute(f"SELECT {_q(key)} FROM {_q(t)} WHERE {_q(key)} IS NOT NULL ORDER BY {_q(key)}")]
    first, rest = [k for k in every if k in with_events], [k for k in every if k not in with_events]
    rng.shuffle(first)
    rng.shuffle(rest)
    return (first + rest)[:n] if n is not None else first + rest


def allocate(n, sizes):
    """n trees over roots that have sizes[i] rows each: equal shares, and a root with fewer rows passes the rest on."""
    alloc, left = [0] * len(sizes), n
    order = sorted(range(len(sizes)), key=lambda i: sizes[i])
    for done, i in enumerate(order):
        alloc[i] = min(sizes[i], left // (len(order) - done))
        left -= alloc[i]
    return alloc


def _event_rows(conn, path, root_row):
    """Rows of the path's last table under root_row, joined down the path; [] when the root's value is empty."""
    vals = [root_row.get(c) for c in path[0].ref_cols]
    if any(v in (None, "") for v in vals):
        return []
    n = len(path)
    sql = f"SELECT DISTINCT t{n - 1}.* FROM {_q(path[-1].child)} t{n - 1}"
    for i in range(n - 1, 0, -1):
        on = " AND ".join(f"t{i}.{_q(c)} = t{i - 1}.{_q(r)}" for c, r in zip(path[i].cols, path[i].ref_cols))
        sql += f" JOIN {_q(path[i - 1].child)} t{i - 1} ON {on}"
    sql += " WHERE " + " AND ".join(f"t0.{_q(c)} = ?" for c in path[0].cols)
    return sorted(_rows(conn, sql, vals), key=lambda r: json.dumps(r, sort_keys=True, default=str))


def _node(conn, table, row, specs, tracer, speaker, depth=0):
    return {"table": table, "row": row, "label": tracer.label(table, row, speaker),
            "parents": _parents(conn, row, specs, tracer, speaker, depth)}


def _parents(conn, row, specs, tracer, speaker, depth=0):
    out = []
    if depth >= MAX_DEPTH:
        return out
    for p in specs or []:
        e = db_profile.parse_edge(p["via"])
        vals = [row.get(c) for c in e.cols]
        if any(v in (None, "") for v in vals):
            continue
        where = " AND ".join(f"{_q(r)} = ?" for r in e.ref_cols)
        got = _rows(conn, f"SELECT * FROM {_q(e.parent)} WHERE {where} LIMIT 1", vals)
        if got:
            out.append(_node(conn, e.parent, got[0], p.get("parents"), tracer, speaker, depth + 1))
    return out


def _cap(groups, rng, k):
    """Row indices kept per group: all of them when they fit k, else one random row per group plus random others."""
    if sum(len(g) for g in groups) <= k:
        return [list(range(len(g))) for g in groups]
    keep, pool = [[] for _ in groups], []
    for gi, g in enumerate(groups):
        idx = list(range(len(g)))
        rng.shuffle(idx)
        keep[gi] += idx[:1]
        pool += [(gi, j) for j in idx[1:]]
    rng.shuffle(pool)
    for gi, j in pool[:max(0, k - sum(map(len, keep)))]:
        keep[gi].append(j)
    return [sorted(x) for x in keep]


def build_tree(conn, profile, root, key_value, rng, tracer, max_events=MAX_EVENTS):
    """The root row with its parents and attributes, and each of the root's event groups with up to max_events rows
    in all, every event row with its parent rows nested. None when no row has this key."""
    t, person = root["table"], profile["persons"][root["table"]]
    found = _rows(conn, f"SELECT * FROM {_q(t)} WHERE {_q(person['key'])} = ?", (key_value,))
    if not found:
        return None
    row, speaker = found[0], {(t, str(key_value))}
    groups = []
    for ev in profile["events"]:
        path = [db_profile.parse_edge(x) for x in ev["path"]]
        if path[0].parent == t:
            groups.append((ev, _event_rows(conn, path, row)))
    keep = _cap([rs for _, rs in groups], rng, max_events)
    attrs = {}
    for a in profile["attributes"]:
        e = db_profile.parse_edge(a["via"])
        vals = [row.get(r) for r in e.ref_cols]
        if a["of"] == t and all(v not in (None, "") for v in vals):
            got = _rows(conn, f"SELECT * FROM {_q(a['table'])} WHERE " + " AND ".join(f"{_q(c)} = ?" for c in e.cols), vals)
            if got:
                attrs[a["table"]] = got
    return {"anchor_table": t, "anchor_key": person["key"], "key_value": key_value,
            "anchor_name": " ".join(str(row[c]) for c in person["name_cols"] if row.get(c) not in (None, "")),
            "anchor_row": row, "profile_version": db_profile.version(profile),
            "parents": _parents(conn, row, root.get("parents"), tracer, speaker),
            "attributes": attrs,
            "events": [{"table": ev["table"], "label": ev["label"], "count": len(rs),
                        "rows": [_node(conn, ev["table"], rs[j], ev.get("parents"), tracer, speaker) for j in idx]}
                       for (ev, rs), idx in zip(groups, keep)]}


def _public_in(node):
    return node["label"] == "public" or any(_public_in(p) for p in node["parents"])


def has_public(tree):
    """Whether any row of the tree is public data: types 2 and 3 need one to write."""
    return any(_public_in(p) for p in tree["parents"]) or any(_public_in(n) for g in tree["events"] for n in g["rows"])


def pick_events(tree, rng, k, need_public=False):
    """[[group, row], ...] of the k event rows the prompt shows: with need_public an event with a public row under
    it first (when there is one), then one row of each group not shown yet, then random others."""
    refs = [(gi, j) for gi, g in enumerate(tree["events"]) for j in range(len(g["rows"]))]
    rng.shuffle(refs)
    first = [r for r in refs if _public_in(tree["events"][r[0]]["rows"][r[1]])][:1] if need_public else []
    seen, spread, rest = {r[0] for r in first}, [], []
    for r in refs:
        if r in first:
            continue
        (spread if r[0] not in seen else rest).append(r)
        seen.add(r[0])
    return [list(r) for r in (first + spread + rest)[:k]]


def shown(tree, refs):
    """The event groups cut down to refs, in tree order; groups without a shown row are left out."""
    want, out = {tuple(r) for r in refs}, []
    for gi, g in enumerate(tree["events"]):
        rows = [n for j, n in enumerate(g["rows"]) if (gi, j) in want]
        if rows:
            out.append({**g, "rows": rows})
    return out


def tables_by_label(tree, refs):
    """{'own', 'public', 'other'}: the tables of the rows the prompt shows, in first-seen order. The root table and
    the attribute tables are own."""
    out = {"own": [tree["anchor_table"]] + list(tree["attributes"]), "public": [], "other": []}

    def add(node):
        kind = node["label"] if node["label"] in ("own", "public") else "other"
        if node["table"] not in out[kind]:
            out[kind].append(node["table"])
        for p in node["parents"]:
            add(p)
    for p in tree["parents"]:
        add(p)
    for g in shown(tree, refs):
        for n in g["rows"]:
            add(n)
    return out


def open_ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
