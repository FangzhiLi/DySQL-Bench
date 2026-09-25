"""Anchors and update targets: the structure a DySQL-style task needs.
A task is anchored on a row (a person, or an entity such as a car or a recipe) and writes rows in the anchor's
scope: the anchor, the tables below it (<= 2 FK hops) and their parent tables.
Evidence: docs/data_gen/dysql_task_types.md. This module must not import db_select (db_select imports it)."""
import re

PERSON = re.compile(r"customer|client|employee|staff|member|player|user|student|patient|person|people|"
                    r"author|driver|agent|bowler|entertainer|actor|athlete|teacher|faculty|professor|"
                    r"instructor|doctor|physician|nurse|cyclist|voter|owner|guest|visitor|passenger|"
                    r"seller|buyer|investor|pilot|legislator|contact|coach|manager|artist|singer|"
                    r"wrestler|reviewer|donor|officer|swimmer|gymnast|scientist|musician|editor|journalist|candidate")
NAME_COLS = {"firstname", "lastname", "fname", "lname", "fullname", "first", "last",
             "surname", "givenname", "familyname", "forename"}
GUID = re.compile(r"guid|uuid", re.I)
LABEL = re.compile(r"(name|title|label)$", re.I)


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
