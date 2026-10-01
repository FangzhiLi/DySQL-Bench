# taskgen/v2/taskgen_v2/schema.py
"""What the generation prompt says about a database: DDL, BIRD's per-column notes, and a one-paragraph description."""
import csv, glob, json, os, re, sqlite3
from taskgen_common.db_select import _q

DESCRIBE_PROMPT = """Below is the DDL of a SQLite database{notes}. In two or three English sentences, say what this
database is about, who the people in it are (which tables hold persons, e.g. customers, employees, players) and what
the main transactional or fact tables record. Plain prose, no bullet points, no table names in quotes.

{ddl}"""


def ddl(db_path, tables=None):
    """CREATE TABLE statements, of the given tables only when tables is set."""
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                         "AND sql IS NOT NULL ORDER BY rowid").fetchall()
    finally:
        c.close()
    return "\n".join(sql for name, sql in rows if tables is None or name in tables)


def column_descriptions(db_path):
    """BIRD ships <db dir>/database_description/<table>.csv; Spider databases have none -> {}."""
    out = {}
    for f in sorted(glob.glob(os.path.join(os.path.dirname(db_path), "database_description", "*.csv"))):
        table = os.path.splitext(os.path.basename(f))[0]
        with open(f, encoding="utf-8-sig", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                col = (r.get("original_column_name") or "").strip()
                desc = " ".join(x for x in [(r.get("column_description") or "").strip(),
                                            (r.get("value_description") or "").strip()] if x)
                if col and desc:
                    out.setdefault(table, {})[col] = desc
    return out


def schema_block(db_path, tables=None):
    """DDL plus BIRD's column notes; with tables set, only those tables (the profile's scope: excluded tables stay out
    of the prompt). BIRD names a notes file after its table, sometimes in another case."""
    text = ddl(db_path, tables)
    keep = None if tables is None else {t.lower() for t in tables}
    notes = [f"- {t}.{c}: {d}" for t, cols in column_descriptions(db_path).items() if keep is None or t.lower() in keep
             for c, d in cols.items()]
    if notes:
        text += "\n\n## Column notes\n" + "\n".join(notes)
    return text


def describe_db(db_key, db_path, client, cache_path):
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    if db_key in cache:
        return cache[db_key]
    cd = column_descriptions(db_path)
    notes = " and the column notes that follow it" if cd else ""
    body = schema_block(db_path)
    text = client.chat([{"role": "user", "content": DESCRIBE_PROMPT.format(notes=notes, ddl=body)}],
                       temperature=0.3, max_tokens=1024)["content"].strip()
    cache[db_key] = text
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    return text


def next_ids(db_path):
    """{table: (pk_column, MAX(pk) + 1)} for every table whose primary key is one INTEGER column (1 when empty).
    The generation prompt lists these so new rows do not collide with existing keys."""
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out = {}
    try:
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            pk = [r for r in c.execute(f'PRAGMA table_info("{t}")') if r[5]]
            if len(pk) != 1 or (pk[0][2] or "").upper() not in ("INTEGER", "INT"):
                continue
            (m,) = c.execute(f'SELECT MAX("{pk[0][1]}") FROM "{t}"').fetchone()
            out[t] = (pk[0][1], (m or 0) + 1)
    finally:
        c.close()
    return out


def pk_info(conn):
    """{table: {"cols", "rowid_alias", "omittable", "next"}} for every table of an open connection.
    omittable: an INSERT may leave the key out and SQLite assigns MAX + 1 -- the key is a rowid alias (one column
    declared exactly INTEGER, rowid table) and, with AUTOINCREMENT, sqlite_sequence has not run ahead of MAX (it has
    in 8 WWE tables). next is that MAX + 1 (1 for an empty table) for omittable tables, else None."""
    seq = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
        seq = dict(conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
    out = {}
    for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall():
        pk = sorted((r for r in conn.execute(f"PRAGMA table_info({_q(name)})") if r[5]), key=lambda r: r[5])
        cols = [r[1] for r in pk]
        rowid_alias = (len(pk) == 1 and (pk[0][2] or "").upper() == "INTEGER"
                       and not re.search(r"(?i)\bwithout\s+rowid\b", sql or ""))
        nxt = None
        if rowid_alias:
            (mx,) = conn.execute(f"SELECT MAX({_q(cols[0])}) FROM {_q(name)}").fetchone()
            autoinc = re.search(r"(?i)\bautoincrement\b", sql or "") is not None
            if not autoinc or (seq.get(name) or 0) <= (mx or 0):
                nxt = (mx or 0) + 1
        out[name] = {"cols": cols, "rowid_alias": rowid_alias, "omittable": nxt is not None, "next": nxt}
    return out


def next_rowid(conn, table, col):
    """The key SQLite gives the next row that leaves col (a rowid alias) out: one above the larger of MAX(col) and,
    with AUTOINCREMENT, the table's sqlite_sequence value."""
    (mx,) = conn.execute(f"SELECT MAX({_q(col)}) FROM {_q(table)}").fetchone()
    seq = None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
        seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
    return max(mx or 0, (seq or (0,))[0] or 0) + 1


def unique_columns(conn, table):
    """Column groups under a UNIQUE constraint or a unique index, those equal to the primary key left out (WWE
    declares its INTEGER keys UNIQUE as well)."""
    pk = tuple(r[1] for r in sorted((r for r in conn.execute(f"PRAGMA table_info({_q(table)})") if r[5]), key=lambda r: r[5]))
    out = set()
    for idx in conn.execute(f"PRAGMA index_list({_q(table)})").fetchall():
        cols = tuple(r[2] for r in conn.execute(f"PRAGMA index_info({_q(idx[1])})"))
        if idx[2] and idx[3] != "pk" and sorted(cols) != sorted(pk):
            out.add(cols)
    return sorted(out)


def _next_number(conn, table, col):
    """MAX + 1 when every value of a one-column key is a whole number, also when stored as text (college_2's IDs)."""
    vals = [v for (v,) in conn.execute(f"SELECT {_q(col)} FROM {_q(table)}") if v is not None]
    if not vals or not all(re.fullmatch(r"-?\d+(\.0+)?", str(v)) for v in vals):
        return None
    return max(int(float(v)) for v in vals) + 1


def key_notes(conn, tables, no_insert=(), fks=None):
    """design §4.3, one line per table: how a new row gets its key -- left out (SQLite assigns it), stated with a
    suggested value, stated as a new natural value, the key of the row it belongs to, every column of a composite
    key, or no new rows at all -- and which columns must stay unique. fks: {table: its foreign-key columns}."""
    pk, notes, fks = pk_info(conn), {}, fks or {}
    for t in tables:
        info = pk.get(t)
        if info is None:
            continue
        cols = info["cols"]
        if t in no_insert:
            note = "no new rows (UPDATE or DELETE only)"
        elif len(cols) == 1 and cols[0] in fks.get(t, ()):   # college_2's advisor.s_ID is a student's ID
            note = f"a new row states {cols[0]}, the key of the row it belongs to, written in the instruction"
        elif info["omittable"]:
            note = f"a new row may leave {cols[0]} out (SQLite assigns {info['next']})"
        elif len(cols) == 1:
            n = _next_number(conn, t, cols[0])
            note = (f"a new row must state {cols[0]} = {n}, written in the instruction" if n is not None
                    else f"a new row must state a new {cols[0]}, one not used yet, written in the instruction")
        elif cols:
            note = f"key ({', '.join(cols)}); a new row states every key column, in a combination not used yet"
        else:
            note = "no primary key"
        uniq = unique_columns(conn, t)
        if uniq:
            note += "; unique: " + ", ".join(u[0] if len(u) == 1 else f"({', '.join(u)})" for u in uniq) + " (no value used twice)"
        notes[t] = f"- {t}: {note}"
    return notes
