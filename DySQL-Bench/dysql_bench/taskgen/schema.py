# dysql_bench/taskgen/schema.py
"""What the generation prompt says about a database: DDL, BIRD's per-column notes, and a one-paragraph description."""
import csv, glob, json, os, sqlite3

DESCRIBE_PROMPT = """Below is the DDL of a SQLite database{notes}. In two or three English sentences, say what this
database is about, who the people in it are (which tables hold persons, e.g. customers, employees, players) and what
the main transactional or fact tables record. Plain prose, no bullet points, no table names in quotes.

{ddl}"""


def ddl(db_path):
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return "\n".join(r[0] for r in c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY rowid"))
    finally:
        c.close()


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


def schema_block(db_path):
    text = ddl(db_path)
    cd = column_descriptions(db_path)
    if cd:
        notes = "\n".join(f"- {t}.{c}: {d}" for t, cols in cd.items() for c, d in cols.items())
        text += "\n\n## Column notes\n" + notes
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
