# taskgen/v2/taskgen_v2/repair.py
"""Repair candidates the check rejected for orphans (2026-10-05): the gold also deletes, or re-points, the rows that
still point at what it deletes or renumbers, and the generation model rewrites the instruction to ask for that.
DySQL deletes the children first in 37 of its 53 deletes of a referenced row. A candidate rejected as a net no-op, or
whose cascade would change too many rows, is generated again from the same tree instead (scripts/repair_tasks.py)."""
import json, re, sqlite3
from taskgen_common.db_select import _q
from taskgen_v2 import check, io, prompt

MAX_ROWS = prompt.CFG["MAX_ROWS_PER_STMT"]   # one cascade statement may not change more (the check's bulk rule)
MAX_DEPTH = 3                                       # levels of children followed (owners.MAX_HOPS)
_DELETE = re.compile(r'(?is)^\s*delete\s+from\s+(?:"[^"]+"|\[[^\]]+\]|`[^`]+`|[\w$]+)\s*(.*)$')


def _cols(cols):
    return _q(cols[0]) if len(cols) == 1 else "(" + ", ".join(_q(c) for c in cols) + ")"


def _children(tracer):
    out = {}
    for child, refs in tracer.up.items():
        for cols, parent, ref_cols in refs:
            out.setdefault(parent.lower(), []).append((child, cols, ref_cols))
    return out


def _delete_cascade(conn, children, table, frm, max_rows, depth=0, path=()):
    """DELETE statements, deepest first, for the rows that point at the rows `frm` selects ('FROM t WHERE ...');
    None when a table would lose more than max_rows rows in one statement."""
    out = []
    if depth >= MAX_DEPTH:
        return out
    for child, cols, ref_cols in children.get(table.lower(), []):
        if child.lower() in path:
            continue
        sub = f"FROM {_q(child)} WHERE {_cols(cols)} IN (SELECT {', '.join(_q(r) for r in ref_cols)} {frm})"
        n = conn.execute(f"SELECT COUNT(*) {sub}").fetchone()[0]
        if not n:
            continue
        if n > max_rows:
            return None
        deeper = _delete_cascade(conn, children, child, sub, max_rows, depth + 1, path + (table.lower(),))
        if deeper is None:
            return None
        out += deeper + [f"DELETE {sub}"]
    return out


def cascade(conn, tracer, stmts, max_rows=MAX_ROWS):
    """The statements with a cascade added, or None when one would change more than max_rows rows of a table, or a
    statement fails. A DELETE is preceded by deletes of the rows that point at what it removes (through subqueries on
    its own WHERE, so no new values appear); an UPDATE that renumbers a key is followed by updates that move the rows
    pointing at the old key to the new one. conn: a writable copy of the database; it ends changed."""
    children = _children(tracer)
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _rk (seq INTEGER PRIMARY KEY, t TEXT, phase TEXT, j TEXT)")
    for t in {p for p in children}:
        name = tracer.canon(t)
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_q(name)})")]
        if not cols:
            continue
        for when, ref, phase in (("BEFORE", "OLD", "b"), ("AFTER", "NEW", "a")):
            conn.execute(f"CREATE TEMP TRIGGER IF NOT EXISTS {_q('_rk_' + phase + name)} {when} UPDATE ON main.{_q(name)} BEGIN "
                         f"INSERT INTO _rk (t, phase, j) VALUES ('{name}', '{phase}', {check._json_row(cols, ref)}); END")
    out = []
    try:
        for st in stmts:
            w = check.write_target(st)
            if w and w[0] == "DELETE":
                m = _DELETE.match(st)
                if not m:
                    return None
                pre = _delete_cascade(conn, children, tracer.canon(w[1]), f"FROM {_q(tracer.canon(w[1]))} {m.group(1)}".rstrip(), max_rows)
                if pre is None:
                    return None
                for s in pre:
                    conn.execute(s)
                out += pre
            conn.execute("DELETE FROM _rk")
            conn.execute(st).fetchall()
            out.append(st)
            if not (w and w[0] == "UPDATE"):
                continue
            rows = conn.execute("SELECT t, phase, j FROM _rk ORDER BY seq").fetchall()
            pairs = [(rows[i][0], json.loads(rows[i][2]), json.loads(rows[i + 1][2]))
                     for i in range(len(rows) - 1) if rows[i][1] == "b" and rows[i + 1][1] == "a" and rows[i][0] == rows[i + 1][0]]
            for t, old, new in pairs:
                for child, cols, ref_cols in children.get(t.lower(), []):
                    before, after = [old.get(r) for r in ref_cols], [new.get(r) for r in ref_cols]
                    if before == after or any(v in (None, "") for v in before):
                        continue
                    where = " AND ".join(f"{_q(c)} = {prompt.sql_value(v)}" for c, v in zip(cols, before))
                    n = conn.execute(f"SELECT COUNT(*) FROM {_q(child)} WHERE {where}").fetchone()[0]
                    if not n:
                        continue
                    if n > max_rows:
                        return None
                    s = f"UPDATE {_q(child)} SET " + ", ".join(f"{_q(c)} = {prompt.sql_value(v)}" for c, v in zip(cols, after)) + f" WHERE {where}"
                    conn.execute(s)
                    out.append(s)
    except sqlite3.Error:
        return None
    return out


SYSTEM = """You edit training tasks for a database customer-service agent. A task is one user's request and the SQL that carries it out. The SQL of this task was extended: it now also deletes, or re-points, the records that still referred to what the request deletes or renumbers, so that nothing is left pointing at a missing record.

Rewrite the request so it asks for exactly what the new SQL does:
1. Keep the speaker, their tone and the first sentence's identification (name, role or username, and the record's ID).
2. Keep every value the request already gives, and give every value the new SQL uses that the request does not.
3. Say plainly that the related records are deleted too, or moved to the new key; name the kinds of records (tables) involved.
4. First person, only asks for changes, no questions; 40 to 90 words.

Think inside <thought></thought>, then answer inside <answer></answer> as strict JSON: {"instruction": "..."}"""

USER = """# Database
{description}

## Original request
{instruction}

## Original SQL
{old_sql}

## New SQL (what the request must now ask for)
{new_sql}

Rewrite the request now."""


def rewrite_messages(cand, new_stmts, materials):
    old = "\n".join(s for a in cand["actions"] for s in check.split_statements(a["sql"]))
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(description=materials.get("description", ""), instruction=cand["instruction"],
                                                    old_sql=old, new_sql="\n".join(new_stmts))}]


def parse_rewrite(text):
    """The rewritten instruction from a model answer; ValueError when there is none."""
    for c in io.json_candidates(text or ""):
        try:
            obj = json.loads(c, strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("instruction"), str) and obj["instruction"].strip():
            return obj["instruction"].strip()
    raise ValueError("no JSON object with an instruction")
