# taskgen/v2/taskgen_v2/owners.py
"""Whose data a row is: follow foreign keys from the row up to person tables (at most 3 hops) and collect the people
reached. The execution check labels every written row with it and the tree builder labels every row it shows with
it, so 'own', 'public' and 'another person's' mean the same thing in the prompt and in the check."""
import sqlite3
from taskgen_common.db_select import _q
from taskgen_v2 import db_profile

MAX_HOPS = db_profile.MAX_PATH   # an event row reaches its root through at most this many edges


def _key(e):
    return e.child.lower(), tuple(c.lower() for c in e.cols), e.parent.lower(), tuple(c.lower() for c in e.ref_cols)


class Tracer:
    def __init__(self, conn, edges, persons, names=None, tables=(), public=()):
        """edges: db_profile.Edge list, child -> parent; persons: {table: key column}; names: {table: [name columns]};
        tables: the names write targets are canonicalized to; public: tables whose rows belong to nobody, so tracing
        stops there (a department names its chair, but the chair does not own the department)."""
        self.conn, self.persons, self.names, self.public = conn, persons, names or {}, set(public)
        self.up, seen = {}, set()
        for e in edges:
            if e.child.lower() == e.parent.lower() or _key(e) in seen:   # a manager_id says nothing about whose row it is
                continue
            seen.add(_key(e))
            self.up.setdefault(e.child, []).append((tuple(e.cols), e.parent, tuple(e.ref_cols)))
        self.tables = {t.lower(): t for t in tables}

    @classmethod
    def from_rec(cls, db_rec, conn):
        """Without a profile (DySQL gold, v1 candidates), as in v1: the anchors' person tables, the recorded
        single-column foreign keys."""
        edges = [db_profile.Edge(f["table"], (f["col"],), f["ref_table"], (f["ref_col"],)) for f in db_rec["fks"]]
        persons = {a["table"]: a["key"] for a in db_rec["anchors"] if a["kind"].startswith("person")}
        names = {a["table"]: a["names"] for a in db_rec["anchors"]}
        tables = [a["table"] for a in db_rec["anchors"]] + [f[k] for f in db_rec["fks"] for k in ("table", "ref_table")]
        return cls(conn, edges, persons, names, tables)

    @classmethod
    def from_profile(cls, profile, db_rec, conn):
        """The profile's people and edges (same_as included) plus every recorded foreign key, composite ones too."""
        edges = db_profile.edges(profile)
        edges += [db_profile.Edge(f["table"], (f["col"],), f["ref_table"], (f["ref_col"],)) for f in db_rec["fks"]]
        edges += [db_profile.Edge(f["table"], tuple(f["cols"]), f["ref_table"], tuple(f["ref_cols"]))
                  for f in db_rec.get("fks_composite", ())]
        persons = {t: p["key"] for t, p in profile["persons"].items()}
        names = {t: p["name_cols"] for t, p in profile["persons"].items()}
        tables = [n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return cls(conn, edges, persons, names, tables, profile["public"])

    def canon(self, table):
        return self.tables.get(table.lower(), table)

    def trace(self, table, row, depth=0, acc=None):
        """{(person table, key as str)} the row belongs to: itself when it is a person row, plus the people its
        parents (up to MAX_HOPS) belong to."""
        acc = set() if acc is None else acc
        if table in self.public:
            return acc
        if table in self.persons:
            v = row.get(self.persons[table])
            if v is not None:
                acc.add((table, str(v)))
        if depth >= MAX_HOPS:
            return acc
        for cols, parent, ref_cols in self.up.get(table, []):
            vals = [row.get(c) for c in cols]
            if any(v in (None, "") for v in vals):
                continue
            where = " AND ".join(f"{_q(r)} = ?" for r in ref_cols)
            try:
                cur = self.conn.execute(f"SELECT * FROM {_q(parent)} WHERE {where} LIMIT 3", vals)
            except sqlite3.Error:
                continue
            names = [d[0] for d in cur.description]
            for r in cur.fetchall():
                self.trace(parent, dict(zip(names, r)), depth + 1, acc)
        return acc

    def name(self, table, key):
        cols = self.names.get(table) or []
        if cols and table in self.persons:
            try:
                r = self.conn.execute(f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(table)} "
                                      f"WHERE {_q(self.persons[table])} = ?", (key,)).fetchone()
            except sqlite3.Error:
                r = None
            if r and any(v not in (None, "") for v in r):
                return " ".join(str(v) for v in r if v not in (None, ""))
        return f"{table} {key}"

    def label(self, table, row, speaker):
        """'own' when the row reaches the speaker, 'other:<name>' when it reaches only other people, else 'public'."""
        owners = self.trace(table, row)
        if owners & speaker:
            return "own"
        if owners:
            t, k = sorted(owners)[0]
            return "other:" + self.name(t, k)
        return "public"
