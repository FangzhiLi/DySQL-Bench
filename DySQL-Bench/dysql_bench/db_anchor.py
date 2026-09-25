"""Anchors and update targets: the structure a DySQL-style task needs.
A task is anchored on a row (a person, or an entity such as a car or a recipe) and writes rows in the anchor's
scope: the anchor, the tables below it (<= 2 FK hops) and their parent tables.
Evidence: docs/data_gen/dysql_task_types.md. This module must not import db_select (db_select imports it)."""
import re
from collections import deque

PERSON = re.compile(r"customer|client|employee|staff|member|player|user|student|patient|person|people|"
                    r"author|driver|agent|bowler|entertainer|actor|athlete|teacher|faculty|professor|"
                    r"instructor|doctor|physician|nurse|cyclist|voter|owner|guest|visitor|passenger|"
                    r"seller|buyer|investor|pilot|legislator|contact|coach|manager|artist|singer|"
                    r"wrestler|reviewer|donor|officer|swimmer|gymnast|scientist|musician|editor|journalist|candidate")
NAME_COLS = {"firstname", "lastname", "fname", "lname", "fullname", "first", "last",
             "surname", "givenname", "familyname", "forename"}
GUID = re.compile(r"guid|uuid", re.I)
LABEL = re.compile(r"(name|title|label)$", re.I)
DESC = re.compile(r"(^|_)desc(ription)?$", re.I)
NUMERIC_TYPE = re.compile(r"int|real|floa|doub|num|dec", re.I)  # SQLite numeric affinities: not a name


def _norm(name):
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return s[:-1] if s.endswith("s") else s


def own_key_cols(t, key):
    """Columns that identify the row itself: declared PK, else the chosen single key, else the composite key."""
    return set(t["pk"]) or ({key} if key else set(t["composite_key"]))


def updatable_cols(t, key, max_avg_len):
    """Columns an UPDATE can set: anything but the row's own key, guid columns, all-empty and long-text columns.
    FK columns count: 37% of DySQL's gold UPDATEs reassign an FK (SET AgentID = 2)."""
    own = own_key_cols(t, key)
    out = []
    for col in t["cols"]:
        s = t["stats"].get(col)
        if col in own or GUID.search(col) or s is None:
            continue
        if s["empty"] >= t["rows"] or s["avg_len"] > max_avg_len:
            continue
        out.append(col)
    return out


def update_targets(p, keys, max_avg_len):
    """Tables an UPDATE can hit: >= 1 row and >= 1 updatable column, as name -> updatable columns.
    No larger row minimum: DySQL updates tables of 4-46 rows (Agents 9, position 4)."""
    out = {}
    for t in p["tables"]:
        if t["rows"] < 1:
            continue
        cols = updatable_cols(t, keys.get(t["name"]), max_avg_len)
        if cols:
            out[t["name"]] = cols
    return out


def anchor_kind(name, cols):
    """person_named: a person-like table with a name column, or any table with first/last/full-name columns;
    person_id_only: person-like table without names; entity: everything else (car, recipe, team)."""
    norm = [_norm(c) for c in cols]
    person = bool(PERSON.search(name.lower()))
    if any(c in NAME_COLS for c in norm) or (person and any(c.endswith("name") for c in norm)):
        return "person_named"
    return "person_id_only" if person else "entity"


def name_cols(cols):
    return [c for c in cols if _norm(c) in NAME_COLS or _norm(c).endswith("name")]


def _labels(t):
    """Text columns that name a row, best first: one named after the table (schools.School, Campuses.Campus),
    then name/title/label columns, then a description (Air Carriers.Description)."""
    tn = re.sub(r"[^a-z0-9]", "", t["name"].lower())
    forms = {tn, tn[:-1] if tn.endswith("s") else tn, tn[:-2] if tn.endswith("es") else tn}
    text = [c for c, ty in zip(t["cols"], t["types"]) if not NUMERIC_TYPE.search(ty or "")]
    exact = [c for c in text if re.sub(r"[^a-z0-9]", "", c.lower()) in forms]
    named = [c for c in text if LABEL.search(c) and c not in exact]
    desc = [c for c in text if DESC.search(c) and c not in exact and c not in named]
    return exact + named + desc


def label_cols(p, table, fks):
    """How an entity is referred to: its own name-like columns, else those of a 1:1 table whose single-column
    PK references it (cars: price has no name, data.car_name does)."""
    tables = {t["name"]: t for t in p["tables"]}
    own = _labels(tables[table])
    if own:
        return own
    out = []
    for f in fks:
        child = tables.get(f["table"])
        if f["ref_table"] == table and child and child["pk"] == f["cols"]:
            out += [f"{child['name']}.{c}" for c in _labels(child)]
    return out


def reachable_down(fks, start, max_hops):
    """Tables that reference `start` directly or through up to max_hops FK edges (child direction), BFS order."""
    children = {}
    for f in fks:
        if f["table"] != f["ref_table"]:
            children.setdefault(f["ref_table"], []).append(f["table"])
    seen, q = {start: 0}, deque([start])
    while q:
        x = q.popleft()
        if seen[x] >= max_hops:
            continue
        for y in children.get(x, []):
            if y not in seen:
                seen[y] = seen[x] + 1
                q.append(y)
    return [x for x in seen if x != start]


def parents(fks, names):
    """Tables referenced by any of `names`, excluding `names` themselves (the 'public' rows a task may also edit)."""
    return sorted({f["ref_table"] for f in fks if f["table"] in names} - set(names))


def anchors(p, fks, keys, targets, min_rows, max_hops=2):
    """Rows a task can be anchored on: a single-column key, >= min_rows rows, at least one table below it
    (a named person may instead be its own write target: 'update my salary'), and an update target in scope."""
    out = []
    for t in p["tables"]:
        key = keys.get(t["name"])
        if not key or t["rows"] < min_rows:
            continue
        kind = anchor_kind(t["name"], t["cols"])
        down = reachable_down(fks, t["name"], max_hops)
        if not down and kind != "person_named":
            continue
        up = parents(fks, [t["name"]] + down)
        upd = [x for x in [t["name"]] + down + up if x in targets]
        if not upd:
            continue
        names = name_cols(t["cols"]) if kind != "entity" else label_cols(p, t["name"], fks)
        out.append({"table": t["name"], "key": key, "kind": kind, "rows": t["rows"], "names": names,
                    "down": down, "up": up, "update_targets": upd})
    return out


def entity_rank(a):
    """Sort key for entity anchors: those with a name/title first, then more tables below, then more rows."""
    return (not a["names"], -len(a["down"]), -a["rows"])
