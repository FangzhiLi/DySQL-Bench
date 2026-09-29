# dysql_bench/taskgen/check.py
"""Execution check of a candidate task on an in-memory copy of its database, plus the derived labels
(task type, difficulty, template) that dedup and the pilot statistics use. Nothing here calls a model."""
import json, re, sqlite3, unicodedata
import sqlparse
from sqlparse import tokens as T
from dysql_bench.db_select import _q
from dysql_bench.taskgen import prompt, trees

WRITE = re.compile(r"(?is)^\s*(insert|update|delete|replace)\b")
TARGET = re.compile(r'(?is)^\s*(?:insert\s+(?:or\s+\w+\s+)?into|replace\s+into|update(?:\s+or\s+\w+)?|delete\s+from)\s+'
                    r'(?:"([^"]+)"|\[([^\]]+)\]|`([^`]+)`|([\w$]+))')
SUBQ = re.compile(r"(?is)\(\s*select\b")
INS_SEL = re.compile(r"(?is)^\s*insert\b.*?\bselect\b")


def split_statements(sql):
    return [s.strip().rstrip(";").strip() for s in sqlparse.split(sql or "") if s.strip().rstrip(";").strip()]


def write_target(stmt):
    m = TARGET.match(stmt)
    if not m:
        return None
    op = stmt.split(None, 1)[0].upper()
    return ("INSERT" if op == "REPLACE" else op), next(g for g in m.groups() if g)


def norm_literal(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()


def literals(stmt):
    out = []
    for tok in sqlparse.parse(stmt)[0].flatten():
        if tok.ttype in T.Literal.String.Single:
            out.append(tok.value[1:-1].replace("''", "'"))
        elif tok.ttype in T.Literal.Number:
            out.append(tok.value)
    return out


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def literal_ok(lit, instruction, allowed):
    n = norm_literal(lit)
    if not n or n in allowed:
        return True
    text = norm_literal(instruction)
    if n in text:
        return True
    v = _num(lit)
    if v is not None:
        if any(_num(a) == v for a in allowed):
            return True
        return any(_num(m) == v for m in re.findall(r"-?\d[\d,]*\.?\d*", text))
    return False


class Tracer:
    """Owner lookup for written rows: child -> parent along FK edges (<= 3 hops) to the person tables."""

    def __init__(self, db_rec, conn):
        self.conn = conn
        _, self.up = trees.fk_edges(db_rec["fks"])
        self.persons = {a["table"]: a["key"] for a in db_rec["anchors"] if a["kind"].startswith("person")}
        self.tables = {a["table"].lower(): a["table"] for a in db_rec["anchors"]}
        self.tables.update({f[k].lower(): f[k] for f in db_rec["fks"] for k in ("table", "ref_table")})

    def canon(self, table):
        return self.tables.get(table.lower(), table)

    def trace(self, table, row, depth=0, acc=None):
        acc = set() if acc is None else acc
        if table in self.persons:
            v = row.get(self.persons[table])
            if v is not None:
                acc.add((table, str(v)))
        if depth >= 3:
            return acc
        for col, parent, pcol in self.up.get(table, []):
            v = row.get(col)
            if v in (None, ""):
                continue
            try:
                cur = self.conn.execute(f"SELECT * FROM {_q(parent)} WHERE {_q(pcol)} = ? LIMIT 3", (v,))
            except sqlite3.Error:
                continue
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                self.trace(parent, dict(zip(cols, r)), depth + 1, acc)
        return acc


def task_group(speaker_in_db, labels):
    core = sorted({x for x in labels if x not in ("noop",)})
    if not core:
        return "7_no_change"
    pattern = "+".join(core)
    if speaker_in_db:
        return {"own": "1_self", "own+public": "2_self_and_public", "public": "3_public_only"}.get(pattern, "4_other_person")
    return "5_proxy" if "person_obj" in pattern else "6_entity"


def difficulty(writes, task_type, stmts):
    f = {"multi_write": len(writes) >= 2, "multi_table": len({w["table"] for w in writes}) >= 2,
         "subquery": any(SUBQ.search(s) for s in stmts), "archive": any(INS_SEL.match(s) for s in stmts),
         "public_or_other": task_type in ("2_self_and_public", "4_other_person")}
    score = sum(f.values())
    return {"score": score, "level": "easy" if score == 0 else "medium" if score <= 2 else "hard", "features": f}


def _memory_copy(path):
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:", isolation_level=None)
    src.backup(db); src.close()
    return db


def run_check(db_rec, cand, anchor=None, cfg=prompt.CFG):
    out = {"id": cand.get("id"), "ok": False, "reasons": [], "writes": [], "task_type": None, "template": None, "difficulty": None}
    if not cand.get("instruction"):
        out["reasons"].append("no_instruction"); return out
    if not cand.get("actions"):
        out["reasons"].append("no_actions"); return out
    anchor = anchor or next(a for a in db_rec["anchors"] if a["table"] == cand["anchor_table"])
    scope = {anchor["table"], *anchor["down"], *anchor["up"]}
    speaker_in_db = (cand.get("plan") or {}).get("task_type", "1_self") != "5_proxy" if "plan" in cand else cand.get("speaker_in_db", True)
    db = _memory_copy(db_rec["path"])
    tracer = Tracer(db_rec, db)
    row = db.execute(f"SELECT * FROM {_q(anchor['table'])} WHERE {_q(anchor['key'])} = ?", (cand["key_value"],)).fetchone()
    allowed = {norm_literal(v) for v in (row or ()) if v not in (None, "")}
    anchor_id = (anchor["table"], str(cand["key_value"]))
    # capture pre-update FK/key values, like classify_dysql_tasks.py: 'move my order to product 9' is still 'own'
    db.execute("CREATE TEMP TABLE _old (tbl TEXT, j TEXT)")
    for t in scope:
        need = {c for c, _, _ in tracer.up.get(t, [])} | ({tracer.persons[t]} if t in tracer.persons else set())
        if need:
            obj = ", ".join(f"'{c}', OLD.{_q(c)}" for c in sorted(need))
            db.execute(f"CREATE TEMP TRIGGER {_q('_u_' + t)} BEFORE UPDATE ON main.{_q(t)} BEGIN "
                       f"INSERT INTO _old VALUES ('{t}', json_object({obj})); END")
    stmts, labels = [], []
    db.execute("BEGIN")
    try:
        for a in cand["actions"]:
            for st in split_statements(a["sql"]):
                wt = write_target(st) if WRITE.match(st) else None
                try:
                    if not wt:
                        db.execute(st).fetchall(); continue
                    cur = db.execute(st + " RETURNING *")
                    rcols = [d[0] for d in cur.description]
                    rs = cur.fetchall()
                except sqlite3.Error as e:
                    out["reasons"].append(f"sql_error: {e} in {st[:80]}"); continue
                op, table = wt[0], tracer.canon(wt[1])
                stmts.append(st)
                if table not in scope:
                    out["reasons"].append(f"out_of_scope: {table}")
                for lit in literals(st):
                    if not literal_ok(lit, cand["instruction"], allowed):
                        out["reasons"].append(f"literal_missing: '{lit}' in {op} {table}"); break
                owners = set()
                for r in rs[:50]:
                    owners |= tracer.trace(table, dict(zip(rcols, r)))
                for (j,) in db.execute("SELECT j FROM _old WHERE tbl = ? LIMIT 50", (table,)).fetchall():
                    owners |= tracer.trace(table, json.loads(j))
                db.execute("DELETE FROM _old")
                if not rs:
                    lab = "noop"
                    if op != "INSERT":
                        out["reasons"].append(f"noop_write: {op} {table}")
                elif speaker_in_db:
                    lab = "own" if anchor_id in owners else ("other" if owners else "public")
                else:
                    lab = "person_obj" if owners else "public"
                if len(rs) > cfg["MAX_ROWS_PER_STMT"]:
                    out["reasons"].append(f"bulk: {len(rs)} rows in {op} {table}")
                labels.append(lab)
                out["writes"].append({"op": op, "table": table, "rows": len(rs), "label": lab})
    finally:
        db.execute("ROLLBACK"); db.close()
    if not out["writes"] or (all(w["rows"] == 0 for w in out["writes"])
                             and not any(r.startswith("noop_write") for r in out["reasons"])):
        out["reasons"].append("no_write")   # nothing written, or only zero-row INSERT ... SELECT
    out["task_type"] = task_group(speaker_in_db, labels) if out["writes"] else None
    if out["task_type"]:
        out["template"] = out["task_type"] + "|" + "+".join(sorted(f"{w['op']} {w['table']}" for w in out["writes"]))
        out["difficulty"] = difficulty(out["writes"], out["task_type"], stmts)
    out["ok"] = not out["reasons"]
    return out
