"""Filter candidate SQLite DBs for DySQL-style task generation.
Criteria are documented in docs/2026-09-24-data-gen-db-selection.md."""
import os, re, sqlite3
from dysql_bench.db_anchor import GUID, update_targets, anchors, entity_rank

ID_LIKE = re.compile(r"(id|_key|_code)$", re.I)
GENERIC_KEYS = {"id", "rowid", "pk", "key", "code"}  # never FK evidence: Match.id vs Player_Attributes.id both run 1..N
UNIQUE_SCAN_MAX_ROWS = 3_000_000  # skip COUNT(DISTINCT) on huge tables; they fail the size filter anyway
SAMPLE_ROWS = 5000  # rows sampled per column when inferring FKs by value


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _open(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _composite_key(c, t, cols):
    """First pair of id-like columns that is unique and non-null together (tables without any single key)."""
    ids = [x for x in cols if ID_LIKE.search(x) and not GUID.search(x)][:6]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            nulls = c.execute(f"SELECT count(*) FROM {_q(t)} WHERE {_q(a)} IS NULL OR {_q(b)} IS NULL").fetchone()[0]
            dup = c.execute(f"SELECT count(*) FROM (SELECT 1 FROM {_q(t)} GROUP BY {_q(a)}, {_q(b)} "
                            f"HAVING count(*) > 1)").fetchone()[0]
            if not nulls and not dup:
                return [a, b]
    return []


def _col_stats(c, t, cols):
    """Per column: rows that are NULL or '', rows that are exactly '', average length of non-empty values."""
    out = {}
    for i in range(0, len(cols), 200):  # SQLite caps result columns at 2000
        part = cols[i:i + 200]
        sel = ", ".join(f"sum({_q(x)} IS NULL OR {_q(x)} = ''), sum({_q(x)} = ''), avg(nullif(length({_q(x)}), 0))"
                        for x in part)
        r = c.execute(f"SELECT {sel} FROM {_q(t)}").fetchone()
        out.update({x: {"empty": r[3 * j] or 0, "blank": r[3 * j + 1] or 0, "avg_len": float(r[3 * j + 2] or 0.0)}
                    for j, x in enumerate(part)})
    return out


def profile_db(path):
    c = _open(path)
    names = [r[0] for r in c.execute("select name from sqlite_master where type='table' "
                                     "and name not like 'sqlite_%' order by rowid")]
    tables = []
    for t in names:
        info = c.execute(f"pragma table_info({_q(t)})").fetchall()
        cols = [i[1] for i in info]
        fks = {}
        for r in c.execute(f"pragma foreign_key_list({_q(t)})").fetchall():
            f = fks.setdefault(r[0], {"cols": [], "ref_table": r[2], "ref_cols": []})
            f["cols"].append(r[3]); f["ref_cols"].append(r[4])
        pk = [i[1] for i in sorted(info, key=lambda i: i[5]) if i[5] > 0]
        rows = c.execute(f"select count(*) from {_q(t)}").fetchone()[0]
        scan = 0 < rows <= UNIQUE_SCAN_MAX_ROWS
        unique = [x for x in cols if ID_LIKE.search(x) and c.execute(
            f"select count(distinct {_q(x)}) = count(*) and count({_q(x)}) = count(*) from {_q(t)}").fetchone()[0]] \
            if not pk and scan else []
        composite = _composite_key(c, t, cols) if not pk and not unique and scan else []
        stats = _col_stats(c, t, cols) if scan else {}
        tables.append({"name": t, "cols": cols, "types": [i[2] for i in info], "pk": pk, "unique_keys": unique,
                       "composite_key": composite, "fks": list(fks.values()), "rows": rows, "stats": stats})
    c.close()
    return {"db": os.path.splitext(os.path.basename(path))[0], "path": path,
            "size_mb": os.path.getsize(path) / 2**20, "tables": tables}


def is_keyed(t):
    return bool(t["pk"] or t["unique_keys"] or t["composite_key"])


def _norm(name):
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return s[:-1] if s.endswith("s") else s


def row_key(t):
    """Column that identifies a row: single-column PK, else a unique id-like column (prefer one naming the table)."""
    if len(t["pk"]) == 1:
        return t["pk"][0]
    stem = _norm(re.split(r"[^A-Za-z0-9]", t["name"])[-1])
    return next((k for k in t["unique_keys"] if stem and stem in _norm(k)), (t["unique_keys"] or [None])[0])


def _fk_candidate(col):
    return bool(ID_LIKE.search(col)) and not GUID.search(col) and _norm(col) not in GENERIC_KEYS


def declared_fks(p):
    """Flatten the per-table PRAGMA foreign keys into the common fk dict format."""
    return [{"table": t["name"], "cols": f["cols"], "ref_table": f["ref_table"], "ref_cols": f["ref_cols"],
             "source": "declared"} for t in p["tables"] for f in t["fks"]]


def infer_fks(p, covered=None):
    """Join keys implied by column names, for DBs that declare few FKs (e.g. Kaggle CSV imports).
    A column that is its table's own row key may only reference a strictly larger table (1:1 extension,
    e.g. supplementary_demographics.cust_id -> customers); composite-PK members are ordinary candidates.
    `covered` holds (table, col_lower) pairs to skip; by default the columns of every declared FK."""
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    rows = {t["name"]: t["rows"] for t in p["tables"]}
    out = []
    for t in p["tables"]:
        skip = ({c.lower() for f in t["fks"] for c in f["cols"]} if covered is None
                else {c for tb, c in covered if tb == t["name"]})
        own = keys.get(t["name"])
        for col in t["cols"]:
            lc = col.lower()
            if lc in skip or not _fk_candidate(col):
                continue
            cands = [r for r, k in keys.items() if r != t["name"] and k.lower() == lc]
            if not cands:
                cands = [r for r in keys if r != t["name"] and
                         re.sub(r"_?id$", "", lc) in {r.lower(), _norm(r)}]
            if col == own:
                cands = [r for r in cands if rows[r] > t["rows"]]
            if len(cands) == 1:
                out.append({"table": t["name"], "cols": [col], "ref_table": cands[0],
                            "ref_cols": [keys[cands[0]]], "source": "name"})
    return out


def infer_fks_by_value(p, covered, min_hit=0.99, min_distinct=20, min_coverage=0.1):
    """Role-named FKs (winner_id, loser_id, *_order_id) that no name rule catches: an id-like column whose
    sampled non-empty values (almost) all fall inside exactly one other table's key. `covered` holds
    (table, col_lower) pairs already explained by declared or name-inferred FKs.
    The child's distinct values must also cover >= min_coverage of the referenced keys: a big dense integer key
    (customers.cust_id 1..55,500) 'contains' any small set of small ids by coincidence (times.calendar_month_id),
    while a real role FK (winner_id -> Wrestlers) covers most of them."""
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    rows = {t["name"]: t["rows"] for t in p["tables"]}
    c = _open(p["path"])
    out = []
    for t in p["tables"]:
        own = keys.get(t["name"])
        for col in t["cols"]:
            if (t["name"], col.lower()) in covered or col == own or not _fk_candidate(col):
                continue
            distinct = c.execute(f"SELECT count(DISTINCT {_q(col)}) FROM {_q(t['name'])}").fetchone()[0]
            if distinct < min_distinct:
                continue
            hits = []
            for ref, k in keys.items():
                if ref == t["name"] or rows[ref] < distinct or distinct < min_coverage * rows[ref]:
                    continue
                n, h = c.execute(
                    f"SELECT count(*), coalesce(sum({_q(col)} IN (SELECT {_q(k)} FROM {_q(ref)})), 0) FROM "
                    f"(SELECT {_q(col)} FROM {_q(t['name'])} WHERE {_q(col)} IS NOT NULL AND {_q(col)} != '' "
                    f"LIMIT {SAMPLE_ROWS})").fetchone()
                if n and h / n >= min_hit:
                    hits.append(ref)
            if len(hits) == 1:
                out.append({"table": t["name"], "cols": [col], "ref_table": hits[0],
                            "ref_cols": [keys[hits[0]]], "source": "value"})
    c.close()
    return out


def _resolve_ref_cols(ref, ref_cols):
    """Fill ref columns omitted in the DDL (`REFERENCES customers`) with the referenced table's PK."""
    if all(rc is None for rc in ref_cols) and len(ref["pk"]) == len(ref_cols):
        return list(ref["pk"])
    return [rc or (ref["pk"][0] if len(ref["pk"]) == 1 else None) for rc in ref_cols]


def fk_hit_rate(c, fk, p):
    """Share of the child's non-null, non-empty key values found in the referenced table.
    None when there is nothing to check (empty child, or every value empty): unverified, not wrong."""
    tables = {t["name"].lower(): t for t in p["tables"]}
    ref = tables.get(fk["ref_table"].lower())
    if not ref or any(rc is None for rc in fk["ref_cols"]):
        return 0.0
    cols = ", ".join(_q(x) for x in fk["cols"])
    rcols = ", ".join(_q(x) for x in fk["ref_cols"])
    notnull = " AND ".join(f"{_q(x)} IS NOT NULL AND {_q(x)} != ''" for x in fk["cols"])
    n, hit = c.execute(f"SELECT count(*), coalesce(sum(({cols}) IN (SELECT {rcols} FROM {_q(ref['name'])})), 0) "
                       f"FROM {_q(fk['table'])} WHERE {notnull}").fetchone()
    return hit / n if n else None


def validate_fks(p, fks):
    """Resolve ref table names/columns and attach the data-checked hit rate (None = unverified) to every fk."""
    tables = {t["name"].lower(): t for t in p["tables"]}
    c = _open(p["path"])
    out = []
    for f in fks:
        ref = tables.get(f["ref_table"].lower())
        g = {**f, "ref_table": ref["name"] if ref else f["ref_table"],
             "ref_cols": _resolve_ref_cols(ref, f["ref_cols"]) if ref else f["ref_cols"]}
        h = fk_hit_rate(c, g, p)
        g["hit"] = None if h is None else round(h, 3)
        out.append(g)
    c.close()
    return out


def all_fks(p, extra=(), min_hit=0.3):
    """Declared + name-inferred + value-inferred + manually supplied FKs, each with a data hit rate.
    Only usable declared FKs (hit >= min_hit, or unverified) keep inference off their columns: a broken
    declaration (computer_student: advisedBy -> person(p_id, p_id)) must not hide the real column-level FK."""
    declared = validate_fks(p, declared_fks(p))
    covered = {(f["table"], c.lower()) for f in declared if f["hit"] is None or f["hit"] >= min_hit
               for c in f["cols"]}
    by_name = infer_fks(p, covered)
    covered |= {(f["table"], c.lower()) for f in by_name for c in f["cols"]}
    same = {(f["table"], tuple(c.lower() for c in f["cols"]), f["ref_table"].lower()) for f in declared}
    inferred = [f for f in by_name + infer_fks_by_value(p, covered)
                if (f["table"], tuple(c.lower() for c in f["cols"]), f["ref_table"].lower()) not in same]
    return declared + validate_fks(p, inferred + [{**f, "source": "extra"} for f in extra])


def schema_items(p):
    """Normalized table.column items; a prefix shared by >= half the tables (e.g. `olist_`) is dropped."""
    heads = [m.group(1).lower() for t in p["tables"] if (m := re.match(r"([A-Za-z0-9]+)_", t["name"]))]
    top = max(set(heads), key=heads.count) if heads else None
    strip = top if top and heads.count(top) >= max(2, len(p["tables"]) / 2) else None
    def tname(n):
        return n[len(strip) + 1:] if strip and n.lower().startswith(strip + "_") else n
    return {f"{_norm(tname(t['name']))}.{_norm(c)}" for t in p["tables"] for c in t["cols"]}


def containment(a, b):
    """Share of the smaller schema's table.column items found in the other (catches subset/superset copies)."""
    a, b = set(a), set(b)
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def is_fragmented(p, fks, min_share):
    """True when the largest FK-connected component covers < min_share of tables (grab-bag DBs)."""
    names = [t["name"] for t in p["tables"]]
    if not names:
        return False
    lower = {n.lower(): n for n in names}
    parent = {n: n for n in names}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for f in fks:
        a, b = lower.get(f["table"].lower()), lower.get(f["ref_table"].lower())
        if a and b:
            parent[find(a)] = find(b)
    sizes = {}
    for n in names:
        sizes[find(n)] = sizes.get(find(n), 0) + 1
    return max(sizes.values()) / len(names) < min_share


def _fmt_fk(f):
    return f"{f['table']}.{','.join(f['cols'])}->{f['ref_table']}"


def evaluate(p, cfg, extra_fks=()):
    T = p["tables"]
    fks = all_fks(p, extra_fks, cfg["fk_min_hit"])
    usable = [f for f in fks if f["hit"] is None or f["hit"] >= cfg["fk_min_hit"]]
    keys = {t["name"]: row_key(t) for t in T if row_key(t)}
    targets = update_targets(p, keys, cfg["long_text_avg_len"])
    anc = anchors(p, usable, keys, targets, cfg["anchor_min_rows"])
    person = sorted([a for a in anc if a["kind"] != "entity"], key=lambda a: (a["kind"] != "person_named", -a["rows"]))
    entity = sorted([a for a in anc if a["kind"] == "entity"], key=entity_rank)
    n_cols = sum(len(t["cols"]) for t in T)
    rows = sum(t["rows"] for t in T)
    items = schema_items(p)
    leak_j = {k: containment(items, v) for k, v in cfg["leak_ref"].items()}
    leak_match = max(leak_j, key=leak_j.get) if leak_j else None
    fragmented = is_fragmented(p, usable, cfg["min_component_share"])
    keyed = {t["name"]: is_keyed(t) for t in T}
    fail = []
    if p["db"] in cfg["leak_names"] or (leak_match and leak_j[leak_match] >= cfg["overlap"]):
        fail.append("leak")
    lo, hi = cfg["tables"]
    if not lo <= len(T) <= hi: fail.append("tables")
    if n_cols > cfg["max_cols"]: fail.append("cols")
    lo, hi = cfg["rows"]
    if not lo <= rows <= hi: fail.append("rows")
    if p["size_mb"] > cfg["max_mb"]: fail.append("size")
    if len(usable) < cfg["min_fks"]: fail.append("fks")
    if not targets: fail.append("no_update_target")
    if not anc: fail.append("no_anchor")
    if fragmented: fail.append("fragmented")
    return {"db": p["db"], "n_tables": len(T), "n_cols": n_cols, "total_rows": rows,
            "size_mb": round(p["size_mb"], 1),
            "n_fks_declared": sum(f["source"] == "declared" for f in fks),
            "n_fks_inferred": sum(f["source"] != "declared" for f in fks),
            "n_fks_valid": sum(f["hit"] is not None and f["hit"] >= cfg["fk_min_hit"] for f in fks),
            "invalid_fks": [f"{_fmt_fk(f)} {f['hit']}" for f in fks if f["hit"] is not None and f["hit"] < cfg["fk_min_hit"]],
            "unverified_fks": [_fmt_fk(f) for f in fks if f["hit"] is None],
            "has_person_named": any(a["kind"] == "person_named" for a in anc),
            "anchor_kinds": sorted({a["kind"] for a in anc}),
            "person_anchors": [f"{a['table']}[{','.join(a['names'])}]" for a in person],
            "entity_anchors": [f"{a['table']}[{','.join(a['names'])}]" for a in entity],
            "anchors": anc,
            "update_targets": list(targets), "targets_no_key": [t for t in targets if not keyed[t]],
            "composite_key_tables": [t["name"] for t in T if t["composite_key"]],
            "long_text_cols": [f"{t['name']}.{c}" for t in T for c, s in t["stats"].items()
                               if s["avg_len"] > cfg["long_text_avg_len"]],
            "empty_string_cols": [f"{t['name']}.{c}" for t in T for c, s in t["stats"].items()
                                  if t["rows"] and s["blank"] >= 0.1 * t["rows"]],
            "fragmented": fragmented,
            "leak_match": leak_match if leak_match and leak_j[leak_match] >= cfg["overlap"] else None,
            "max_leak_overlap": round(leak_j[leak_match], 2) if leak_match else 0.0,
            "table_names": [t["name"] for t in T], "schema": sorted(items), "fail_reasons": fail, "pass": not fail}


def dedup(rows, order, threshold):
    """Mark passing DBs whose schema overlaps an already-kept DB from a preferred source."""
    rank = {s: i for i, s in enumerate(order)}
    kept, dup = [], {}
    for i in sorted(range(len(rows)), key=lambda i: rank.get(rows[i]["source"], len(order))):
        r = rows[i]
        if not r["pass"]:
            continue
        hit = next((k for k in kept if containment(r["schema"], k["schema"]) >= threshold), None)
        if hit:
            dup[i] = f'{hit["source"]}:{hit["db"]}'
        else:
            kept.append(r)
    return [{**r, "dup_of": dup.get(i)} for i, r in enumerate(rows)]
