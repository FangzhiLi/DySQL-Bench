# taskgen/v2/taskgen_v2/db_profile.py
"""Per-database profiles (design §4.1). A profile says which tables are the roots (the people tasks are about), which
tables hold people at all, which records are a root's events and which parent rows hang under them, which tables are
1:1 attributes of a person, public reference data, excluded, or closed to INSERT. The generation model drafts a
profile and a person confirms it; trees, the generation prompt and the execution check use confirmed profiles only.
Edges are foreign keys written 'child.col -> parent.col', or 'child.(a, b) -> parent.(x, y)' when composite."""
import hashlib, json, os, re
from collections import namedtuple
from taskgen_common.db_select import _q
from taskgen_v2 import io

PROFILES_JSON = os.path.join(io.DATA, "db_profiles.json")
FIELDS = ("roots", "persons", "events", "attributes", "public", "exclude", "no_insert", "quirks", "description", "confirmed")
MIN_EDGE_HIT = 0.3   # an edge that no recorded foreign key backs must match like a validated FK (db_select.all_fks)
EDGE_SAMPLE = 2000   # child rows sampled for that match rate
MAX_PATH = 3         # edges from an event to its root; ownership tracing (owners.MAX_HOPS) follows no more

Edge = namedtuple("Edge", "child cols parent ref_cols")


def _side(text):
    m = re.match(r"^\s*(.+?)\.\(([^()]*)\)\s*$", text)
    if m:
        table, cols = m.group(1).strip(), tuple(c.strip() for c in m.group(2).split(","))
    else:
        table, dot, col = text.strip().rpartition(".")
        cols = (col.strip(),) if dot else ()
    if not table or not cols or not all(cols):
        raise ValueError(f"not 'table.column' or 'table.(a, b)': {text.strip()!r}")
    return table, cols


def parse_edge(text):
    if not isinstance(text, str) or text.count("->") != 1:
        raise ValueError(f"an edge is 'child.col -> parent.col': {text!r}")
    left, right = text.split("->")
    (child, cols), (parent, ref_cols) = _side(left), _side(right)
    if len(cols) != len(ref_cols):
        raise ValueError(f"{len(cols)} column(s) point to {len(ref_cols)}: {text!r}")
    return Edge(child, cols, parent, ref_cols)


def edge_text(e):
    def side(t, cs):
        return f"{t}.{cs[0]}" if len(cs) == 1 else f"{t}.({', '.join(cs)})"
    return f"{side(e.child, e.cols)} -> {side(e.parent, e.ref_cols)}"


def load(path=PROFILES_JSON):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(profiles, path=PROFILES_JSON):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(profiles.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")


def get(db_key, path=PROFILES_JSON):
    """The confirmed profile of db_key; ValueError when there is none, it is not confirmed yet, or its content changed
    after it was confirmed (design D1)."""
    p = load(path).get(db_key)
    if p is None:
        raise ValueError(f"no profile for {db_key} in {path}: run `taskgen.py profile draft --db {db_key}`")
    if status(p) == "not confirmed":
        raise ValueError(f"the profile of {db_key} is not confirmed: review it, then `taskgen.py profile confirm --db {db_key}`")
    if status(p) != "confirmed":
        raise ValueError(f"the profile of {db_key} changed after it was confirmed: review the change, then "
                         f"`taskgen.py profile confirm --db {db_key}`")
    return p


def version(profile):
    """Short hash of what the profile says (the review fields left out), recorded in every tree."""
    body = {k: profile.get(k) for k in FIELDS if k != "confirmed"}
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]


def confirm(profile):
    """The profile marked confirmed for exactly what it says now; a later edit to its content undoes that."""
    return {**profile, "confirmed": True, "confirmed_version": version(profile)}


def status(profile):
    """'confirmed', 'changed since confirmed' (edited after `profile confirm`) or 'not confirmed'."""
    if profile.get("confirmed") is not True:
        return "not confirmed"
    return "confirmed" if profile.get("confirmed_version") == version(profile) else "changed since confirmed"


def root_anchor(profile, table):
    """A root in the anchor shape the prompt, generate and check use: {table, key, names}."""
    if table not in {r["table"] for r in profile["roots"]}:
        raise ValueError(f"{table} is not a root of this profile")
    p = profile["persons"][table]
    return {"table": table, "key": p["key"], "names": list(p["name_cols"])}


def parent_nodes(profile):
    """(table the parent hangs under, parent spec, location) for every parent: under roots, under events, nested."""
    out = []

    def walk(container, nodes, where):
        for i, p in enumerate(nodes or []):
            loc = f"{where}.parents[{i}]"
            out.append((container, p, loc))
            walk(p.get("table"), p.get("parents"), loc)
    for i, r in enumerate(profile.get("roots") or []):
        walk(r.get("table"), r.get("parents"), f"roots[{i}]")
    for i, e in enumerate(profile.get("events") or []):
        walk(e.get("table"), e.get("parents"), f"events[{i}]")
    return out


def _parsed(texts):
    for x in texts:
        try:
            yield parse_edge(x)
        except ValueError:
            continue


def edges(profile):
    """Every edge the profile states: event paths, parent links, attribute links, and same_as identity columns."""
    out = [parse_edge(x) for e in profile["events"] for x in e["path"]]
    out += [parse_edge(p["via"]) for _, p, _ in parent_nodes(profile)]
    out += [parse_edge(a["via"]) for a in profile["attributes"]]
    for t, p in profile["persons"].items():
        for s in p.get("same_as") or []:
            st, _, sc = s.rpartition(".")
            out.append(Edge(st, (sc,), t, (p["key"],)))
    return out


def used_tables(profile):
    """Every table the profile gives a role (exclude not counted)."""
    used = {r.get("table") for r in profile.get("roots") or []} | set(profile.get("persons") or {})
    used |= set(profile.get("public") or []) | {a.get("table") for a in profile.get("attributes") or []}
    for e in profile.get("events") or []:
        used.add(e.get("table"))
        for x in _parsed(e.get("path") or []):
            used |= {x.child, x.parent}
    used |= {p.get("table") for _, p, _ in parent_nodes(profile)}
    return used - {None}


def scope_tables(profile):
    """The tables a task may write (design §4.5): every table with a role, minus exclude."""
    return used_tables(profile) - set(profile["exclude"])


def _tables(conn):
    return {n: [r[1] for r in conn.execute(f"PRAGMA table_info({_q(n)})")]
            for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}


def edge_hit(conn, e):
    """Share of sampled child rows (edge columns filled) whose values exist in the parent; None when there are none."""
    cols = ", ".join(_q(c) for c in e.cols)
    filled = " AND ".join(f"{_q(c)} IS NOT NULL AND {_q(c)} != ''" for c in e.cols)
    ref = ", ".join(_q(c) for c in e.ref_cols)
    n, hit = conn.execute(f"SELECT COUNT(*), COALESCE(SUM(({cols}) IN (SELECT {ref} FROM {_q(e.parent)})), 0) "
                          f"FROM (SELECT {cols} FROM {_q(e.child)} WHERE {filled} LIMIT {EDGE_SAMPLE})").fetchone()
    return hit / n if n else None


def repeated(conn, e):
    """Whether a value of the edge's parent columns sits in more than one parent row, so the edge does not lead to one
    row (written from the wrong side, like book -> book_author, or to a table keyed by more columns)."""
    cols = ", ".join(_q(c) for c in e.ref_cols)
    filled = " AND ".join(f"{_q(c)} IS NOT NULL" for c in e.ref_cols)
    return conn.execute(f"SELECT 1 FROM {_q(e.parent)} WHERE {filled} GROUP BY {cols} HAVING COUNT(*) > 1 LIMIT 1").fetchone() is not None


def validate(profile, conn, fks=(), composite=()):
    """What makes a profile unusable, as readable lines; [] when it is fine. Checks names against the database, the
    shape of paths and parent links, that edges are foreign keys, and that every table has a role."""
    try:
        return _validate(profile, conn, fks, composite)
    except (AttributeError, KeyError, TypeError) as e:   # wrong JSON shapes in a draft or a hand edit
        return [f"malformed profile: {type(e).__name__}: {e}"]


def _validate(profile, conn, fks, composite):
    miss = [k for k in FIELDS if k not in profile]
    if miss:
        return [f"missing fields: {', '.join(miss)}"]
    shapes = [k for k in ("roots", "events", "attributes", "public", "exclude", "no_insert") if not isinstance(profile[k], list)]
    shapes += ["persons"] if not isinstance(profile["persons"], dict) else []
    shapes += [f"events[{i}].path" for i, e in enumerate(profile["events"] or []) if not isinstance(e.get("path"), list)]
    if shapes:
        return [f"{k}: wrong JSON type (see the field list)" for k in shapes]
    errs, tables = [], _tables(conn)
    known = {(f["table"].lower(), (f["col"].lower(),), f["ref_table"].lower(), (f["ref_col"].lower(),)) for f in fks}
    known |= {(f["table"].lower(), tuple(c.lower() for c in f["cols"]), f["ref_table"].lower(),
               tuple(c.lower() for c in f["ref_cols"])) for f in composite}

    def has(table, where, cols=()):
        if table not in tables:
            errs.append(f"{where}: no table {table!r}")
            return False
        bad = [c for c in cols if c not in tables[table]]
        if bad:
            errs.append(f"{where}: no column {', '.join(f'{table}.{c}' for c in bad)}")
            return False
        return True

    def edge(text, where, child=None, parent=None):
        try:
            e = parse_edge(text)
        except ValueError as x:
            errs.append(f"{where}: {x}")
            return None
        if child is not None and e.child != child:
            errs.append(f"{where}: starts at {e.child}, expected {child}")
        if parent is not None and e.parent != parent:
            errs.append(f"{where}: ends at {e.parent}, expected {parent}")
        if not (has(e.child, where, e.cols) and has(e.parent, where, e.ref_cols)):
            return None
        k = (e.child.lower(), tuple(c.lower() for c in e.cols), e.parent.lower(), tuple(c.lower() for c in e.ref_cols))
        if k not in known:
            h = edge_hit(conn, e)
            if h is not None and h < MIN_EDGE_HIT:
                errs.append(f"{where}: only {h:.0%} of {e.child} rows find a {e.parent} row; not a foreign key")
        if repeated(conn, e):
            side = e.parent + "." + (e.ref_cols[0] if len(e.ref_cols) == 1 else f"({', '.join(e.ref_cols)})")
            errs.append(f"{where}: {side} repeats values, so the edge leads to several rows; "
                        f"write it from the table that holds the reference")
        return e

    persons = profile["persons"]
    for t, p in persons.items():
        if has(t, f"persons.{t}", [p.get("key")] + list(p.get("name_cols") or [])):
            n, d = conn.execute(f"SELECT COUNT(*), COUNT(DISTINCT {_q(p['key'])}) FROM {_q(t)}").fetchone()
            if n != d:
                errs.append(f"persons.{t}: key {p['key']} has empty or repeated values ({d} distinct in {n} rows)")
        if not p.get("name_cols"):
            errs.append(f"persons.{t}: name_cols is empty")
        for s in p.get("same_as") or []:
            st, dot, sc = s.rpartition(".")
            if not dot:
                errs.append(f"persons.{t}.same_as: {s!r} is not table.column")
            elif has(st, f"persons.{t}.same_as", [sc]) and p.get("key") in tables.get(t, ()):
                h = edge_hit(conn, Edge(st, (sc,), t, (p["key"],)))   # held to the same match rate as an edge
                if h is not None and h < MIN_EDGE_HIT:
                    errs.append(f"persons.{t}.same_as: only {h:.0%} of {s} values are {t} keys")
    roots = profile["roots"]
    if not roots:
        errs.append("roots: needs at least one root")
    for i, r in enumerate(roots):
        if r.get("table") not in persons:
            errs.append(f"roots[{i}]: {r.get('table')!r} must also be listed in persons")
        if not r.get("label"):
            errs.append(f"roots[{i}]: label is empty")
    root_tables = {r.get("table") for r in roots}
    event_tables = set()
    for i, ev in enumerate(profile["events"]):
        where, t = f"events[{i}]", ev.get("table")
        if not ev.get("label"):
            errs.append(f"{where}: label is empty")
        if not has(t, where):
            continue
        event_tables.add(t)
        path, prev = ev.get("path") or [], None
        if not path:
            errs.append(f"{where}: empty path")
            continue
        if len(path) > MAX_PATH:
            errs.append(f"{where}: path has {len(path)} edges, but ownership tracing follows at most {MAX_PATH}; "
                        f"its rows would not reach the person")
        for j, text in enumerate(path):
            e = edge(text, f"{where}.path[{j}]", parent=prev)
            if e is None:
                break
            if j == 0 and e.parent not in root_tables:
                errs.append(f"{where}.path[0]: {e.parent} is not a root")
            prev = e.child
        else:
            if prev != t:
                errs.append(f"{where}: path ends at {prev}, not at {t}")
    public = set(profile["public"])
    for container, p, where in parent_nodes(profile):
        t = p.get("table")
        if has(t, where):
            edge(p.get("via"), f"{where}.via", child=container, parent=t)
            if t not in persons and t not in event_tables and t not in public:
                errs.append(f"{where}: {t} hangs under {container} but is not public, a person or an event table")
    for i, a in enumerate(profile["attributes"]):
        where = f"attributes[{i}]"
        if a.get("of") not in persons:
            errs.append(f"{where}: of={a.get('of')!r} is not in persons")
        if has(a.get("table"), where):
            edge(a.get("via"), f"{where}.via", child=a.get("table"), parent=a.get("of"))
    for k in ("public", "exclude", "no_insert"):
        for t in profile[k]:
            has(t, k)
    if public & set(persons):
        errs.append(f"public: {', '.join(sorted(public & set(persons)))} hold people, not public data")
    owned = event_tables | {a.get("table") for a in profile["attributes"]}   # tracing stops at public tables (owners)
    owned |= {t for ev in profile["events"] for x in _parsed(ev.get("path") or []) for t in (x.child, x.parent)}
    for t in sorted((public & owned) - set(persons)):
        errs.append(f"public: {t} holds a person's own rows (event, path or attribute table), so it cannot be public")
    used, excl = used_tables(profile), set(profile["exclude"])
    if used & excl:
        errs.append(f"exclude: {', '.join(sorted(used & excl))} also have a role")
    loose = set(tables) - used - excl
    if loose:
        errs.append(f"tables without a role (list them in public or exclude): {', '.join(sorted(loose))}")
    if set(profile["no_insert"]) - (used - excl):
        errs.append(f"no_insert: {', '.join(sorted(set(profile['no_insert']) - (used - excl)))} are not in scope")
    if not isinstance(profile["confirmed"], bool):
        errs.append("confirmed: must be true or false")
    if not isinstance(profile["quirks"], list) or not all(isinstance(q, str) for q in profile["quirks"]):
        errs.append("quirks: must be a list of sentences")
    if not isinstance(profile["description"], str) or not profile["description"].strip():
        errs.append("description: is empty")
    return errs


def pk_classes(pk):
    """design §4.3 key classes from schema.pk_info, for the review page."""
    out = {"可省 ID": [], "ID 须用户给出": [], "非整数或复合主键": [], "无主键": []}
    for t, v in sorted(pk.items()):
        if v["omittable"]:
            out["可省 ID"].append(t)
        elif v["rowid_alias"]:
            out["ID 须用户给出"].append(t)
        elif v["cols"]:
            out["非整数或复合主键"].append(f"{t}({', '.join(v['cols'])})")
        else:
            out["无主键"].append(t)
    return out


def _parent_lines(nodes, depth):
    out = []
    for p in nodes or []:
        via = p.get("via") or ""
        out.append(f"{'  ' * depth}- {p.get('table')} ← {via.split('->')[0].strip()}")
        out += _parent_lines(p.get("parents"), depth + 1)
    return out


def render_md(entries):
    """Review page (Chinese headings, profile content as is). entries: [{key, profile, errors, pk}]."""
    lines = []
    for x in entries:
        p, errs = x["profile"], x["errors"]
        state = {"confirmed": "已确认", "changed since confirmed": "确认后改过"}.get(status(p), "未确认")
        lines += [f"## {x['key']}　{state}　" + ("校验通过" if not errs else f"{len(errs)} 个问题"), ""]
        if p.get("description"):
            lines += [f"> {p['description']}", ""]
        persons = p.get("persons") or {}
        rows = [("根", "；".join(f"{r.get('table')}（{r.get('label')}）" for r in p.get("roots") or [])),
                ("人物表", "；".join(f"{t}（{v.get('key')}；{', '.join(v.get('name_cols') or [])}"
                                    + (f"；same_as {', '.join(v['same_as'])}" if v.get("same_as") else "") + "）"
                                    for t, v in persons.items())),
                ("事件", "；".join(f"{e.get('table')}（{e.get('label')}）：{' / '.join(e.get('path') or [])}"
                                  for e in p.get("events") or [])),
                ("属性表", "；".join(f"{a.get('table')} → {a.get('of')}" for a in p.get("attributes") or [])),
                ("公共表", ", ".join(p.get("public") or [])), ("排除", ", ".join(p.get("exclude") or [])),
                ("不出 INSERT", ", ".join(p.get("no_insert") or [])), ("数据怪异点", "；".join(p.get("quirks") or []))]
        lines += ["| 项 | 内容 |", "|---|---|"] + [f"| {k} | {v or '—'} |" for k, v in rows] + [""]
        nested = []
        for r in p.get("roots") or []:
            if r.get("parents"):
                nested += [f"- 根 {r.get('table')}"] + _parent_lines(r["parents"], 1)
        for e in p.get("events") or []:
            if e.get("parents"):
                nested += [f"- {e.get('table')}（{e.get('label')}）"] + _parent_lines(e["parents"], 1)
        if nested:
            lines += ["挂在根和事件下面的父行（← 后面是外键列）：", ""] + nested + [""]
        if x.get("pk"):
            lines += ["主键：" + "；".join(f"{k}：{', '.join(v)}" for k, v in pk_classes(x["pk"]).items() if v), ""]
        if p.get("notes"):
            lines += ["Claude 的改动："] + [f"- {n}" for n in p["notes"]] + [""]
        d = p.get("draft") or {}
        if d:
            lines += [f"起草：{d.get('model')}，{d.get('rounds')} 轮" + (f"，没改掉的问题 {len(d['errors'])} 条" if d.get("errors") else ""), ""]
        if errs:
            lines += ["**校验问题：**"] + [f"- {e}" for e in errs] + [""]
    return "\n".join(lines)
