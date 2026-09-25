"""Filter candidate SQLite DBs for DySQL-style task generation.
Criteria are documented in docs/2026-09-24-data-gen-db-selection.md."""
import os, re, sqlite3
from dysql_bench.db_anchor import PERSON, NAME_COLS, GUID

ID_LIKE = re.compile(r"(id|_key|_code)$", re.I)
GENERIC_KEYS = {"id", "rowid", "pk", "key", "code"}  # never FK evidence: Match.id vs Player_Attributes.id both run 1..N
UNIQUE_SCAN_MAX_ROWS = 3_000_000  # skip COUNT(DISTINCT) on huge tables; they fail the size filter anyway


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _open(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


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
        tables.append({"name": t, "cols": cols, "pk": pk, "unique_keys": unique,
                       "fks": list(fks.values()), "rows": rows})
    c.close()
    return {"db": os.path.splitext(os.path.basename(path))[0], "path": path,
            "size_mb": os.path.getsize(path) / 2**20, "tables": tables}

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


def infer_fks(p):
    """Join keys implied by column names, for DBs that declare few FKs (e.g. Kaggle CSV imports).
    A column that is its table's own row key may only reference a strictly larger table (1:1 extension,
    e.g. supplementary_demographics.cust_id -> customers); composite-PK members are ordinary candidates."""
    keys = {t["name"]: row_key(t) for t in p["tables"] if row_key(t)}
    rows = {t["name"]: t["rows"] for t in p["tables"]}
    out = []
    for t in p["tables"]:
        declared = {c.lower() for f in t["fks"] for c in f["cols"]}
        own = keys.get(t["name"])
        for col in t["cols"]:
            lc = col.lower()
            if lc in declared or not _fk_candidate(col):
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


SAMPLE_ROWS = 5000  # rows sampled per column when inferring FKs by value


def infer_fks_by_value(p, covered, min_hit=0.99, min_distinct=20):
    """Role-named FKs (winner_id, loser_id, *_order_id) that no name rule catches: an id-like column whose
    sampled non-empty values (almost) all fall inside exactly one other table's key. `covered` holds
    (table, col_lower) pairs already explained by declared or name-inferred FKs."""
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
                if ref == t["name"] or rows[ref] < distinct:
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

def is_person_table(name, cols):
    return bool(PERSON.search(name.lower())) or any(_norm(c) in NAME_COLS for c in cols)

def transaction_tables(p, min_rows, extra_fks=()):
    """Tables with an outgoing FK and enough rows to be write targets."""
    has_fk = {t["name"] for t in p["tables"] if t["fks"]} | {f["table"] for f in extra_fks}
    return [t["name"] for t in p["tables"] if t["name"] in has_fk and t["rows"] >= min_rows]

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

def is_fragmented(p, inferred, min_share):
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
    edges = [(t["name"], f["ref_table"]) for t in p["tables"] for f in t["fks"]]
    edges += [(f["table"], f["ref_table"]) for f in inferred]
    for a, b in edges:
        b = lower.get(b.lower())
        if b:
            parent[find(a)] = find(b)
    sizes = {}
    for n in names:
        sizes[find(n)] = sizes.get(find(n), 0) + 1
    return max(sizes.values()) / len(names) < min_share

def evaluate(p, cfg):
    T = p["tables"]
    inferred = infer_fks(p)
    n_cols = sum(len(t["cols"]) for t in T)
    rows = sum(t["rows"] for t in T)
    n_decl = sum(len(t["fks"]) for t in T)
    txn = transaction_tables(p, cfg["txn_min_rows"], inferred)
    keyed = {t["name"]: bool(t["pk"] or t["unique_keys"]) for t in T}
    names = [t["name"] for t in T]
    items = schema_items(p)
    leak_j = {k: containment(items, v) for k, v in cfg["leak_ref"].items()}
    leak_match = max(leak_j, key=leak_j.get) if leak_j else None
    persons = [t["name"] for t in T if is_person_table(t["name"], t["cols"])]
    fragmented = is_fragmented(p, inferred, cfg["min_component_share"])
    fail = []
    if p["db"] in cfg["leak_names"] or (leak_match and leak_j[leak_match] >= cfg["overlap"]):
        fail.append("leak")
    lo, hi = cfg["tables"]
    if not lo <= len(T) <= hi: fail.append("tables")
    if n_cols > cfg["max_cols"]: fail.append("cols")
    lo, hi = cfg["rows"]
    if not lo <= rows <= hi: fail.append("rows")
    if p["size_mb"] > cfg["max_mb"]: fail.append("size")
    if n_decl + len(inferred) < cfg["min_fks"]: fail.append("fks")
    if not txn: fail.append("txn_table")
    elif not any(keyed[t] for t in txn): fail.append("txn_locatable")
    if fragmented: fail.append("fragmented")
    if cfg.get("require_person") and not persons: fail.append("no_person")
    return {"db": p["db"], "n_tables": len(T), "n_cols": n_cols, "total_rows": rows,
            "size_mb": round(p["size_mb"], 1), "n_fks_declared": n_decl, "n_fks_inferred": len(inferred),
            "has_person": bool(persons), "person_tables": persons, "txn_tables": txn,
            "txn_no_key": [t for t in txn if not keyed[t]], "fragmented": fragmented,
            "leak_match": leak_match if leak_match and leak_j[leak_match] >= cfg["overlap"] else None,
            "max_leak_overlap": round(leak_j[leak_match], 2) if leak_match else 0.0,
            "table_names": names, "schema": sorted(items), "fail_reasons": fail, "pass": not fail}

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
