# taskgen/v2/taskgen_v2/check.py
"""Execution check of a candidate task on an in-memory copy of its database, plus the derived labels
(task type, difficulty, template) that dedup and the pilot statistics use. Nothing here calls a model."""
import json, re, sqlite3, time, unicodedata
import sqlparse
from sqlparse import tokens as T
from taskgen_common.db_select import _q
from taskgen_v2 import prompt, schema, trees

WRITE = re.compile(r"(?is)^\s*(insert|update|delete|replace)\b")
TARGET = re.compile(r'(?is)^\s*(?:insert\s+(?:or\s+\w+\s+)?into|replace\s+into|update(?:\s+or\s+\w+)?|delete\s+from)\s+'
                    r'(?:"([^"]+)"|\[([^\]]+)\]|`([^`]+)`|([\w$]+))')
SUBQ = re.compile(r"(?is)\(\s*select\b")
TXN = re.compile(r"(?is)^\s*(begin|commit|end|rollback|savepoint|release)\b")
_NAME = r'(?:"([^"]+)"|\[([^\]]+)\]|`([^`]+)`|([\w$]+))'
# archive = INSERT whose source is a SELECT (not a subquery inside VALUES) ...
ARCHIVE_SRC = re.compile(r"(?is)^\s*insert\b(?:(?!\bvalues\b).)*?\bselect\b.*?\bfrom\s+" + _NAME)
# gold that reads the clock or random(): run it twice and compare what the eval hash compares
NONDET = re.compile(r"(?i)\bcurrent_(?:timestamp|time|date)\b|'now'|\brandom(?:blob)?\s*\(|\bunixepoch\s*\(")
# columns the eval hash skips, copied from DySQL-Bench/dysql_bench/envs/base.py (test_volatile_columns_match_the_eval)
VOLATILE_COL_RE = re.compile(
    r"(?i)^(last_?update|updated_?at|update_?time|modified(_at)?|modification_?time|create(d)?_?at|timestamp)$")
RERUN_GAP_S = 1.1   # CURRENT_TIMESTAMP has one-second resolution; date-only values agree within a day and pass


def split_statements(sql):
    """Statements with comments removed (a trailing '-- note' would swallow the appended RETURNING *)."""
    out = []
    for s in sqlparse.split(sql or ""):
        s = sqlparse.format(s, strip_comments=True).strip().rstrip(";").strip()
        if s:
            out.append(s)
    return out


def write_target(stmt):
    """(op, table) of an INSERT/UPDATE/DELETE, also after a WITH clause; None for anything else."""
    if WRITE.match(stmt):
        m = TARGET.match(stmt)
    elif re.match(r"(?is)^\s*with\b", stmt) and sqlparse.parse(stmt)[0].get_type() in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
        m = re.search(TARGET.pattern.replace("^\\s*", "\\b", 1), stmt)
    else:
        return None
    if not m:
        return None
    op = re.match(r"(?is)\s*(\w+)", m.group(0)).group(1).upper()
    return ("INSERT" if op == "REPLACE" else op), next(g for g in m.groups() if g)


def has_archive(stmts):
    """INSERT ... SELECT ... FROM t followed by an UPDATE or DELETE of t (spec §5)."""
    for i, st in enumerate(stmts):
        m = ARCHIVE_SRC.match(st)
        if not m:
            continue
        src = next(g for g in m.groups() if g).lower()
        for later in stmts[i + 1:]:
            wt = write_target(later)
            if wt and wt[0] in ("UPDATE", "DELETE") and wt[1].lower() == src:
                return True
    return False


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


IMPLIED = {"0", "1", "true", "false"}   # flags, counts and defaults nobody spells out (quantity 1, total 0)
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                           "august", "september", "october", "november", "december"])}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
WORDS = {w: str(i) for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
                                          "nine", "ten", "eleven", "twelve"])}
ORDINALS = {w: str(i + 1) for i, w in enumerate(["first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                                                 "eighth", "ninth", "tenth", "eleventh", "twelfth"])}
_MDY =re.compile(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\.?,?\s+(\d{4})\b")


def text_forms(instruction):
    """The normalized instruction plus ISO forms of its written dates and digits for small number words."""
    text = norm_literal(instruction)
    extra = []
    for mo, d, y in _MDY.findall(text):
        if mo in MONTHS:
            extra.append(f"{y}-{MONTHS[mo]:02d}-{int(d):02d}")
    for d, mo, y in _DMY.findall(text):
        if mo in MONTHS:
            extra.append(f"{y}-{MONTHS[mo]:02d}-{int(d):02d}")
    words = re.findall(r"[a-z]+", text)
    extra += [WORDS[w] for w in words if w in WORDS] + [ORDINALS[w] for w in words if w in ORDINALS]
    return text + " " + " ".join(extra)


def _contains(text, n):
    """n occurs in text as a whole token: '203' is not in '2030', 'ann' is not in 'joanna'."""
    return re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", text) is not None


def literal_ok(lit, instruction, allowed):
    n = norm_literal(lit)
    if not n or n in allowed or n in IMPLIED or "%" in n:   # '%Y' etc. are strftime/LIKE patterns, not values
        return True
    text = text_forms(instruction)
    if _contains(text, n):
        return True
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ t]\d{2}:\d{2}(:\d{2})?(\.\d+)?$", n)   # datetime: the date part suffices
    if m and _contains(text, m.group(1)):
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
    core = sorted({"public" if x == "new_person" else x for x in labels if x != "noop"})
    if not core:
        return "7_no_change"
    pattern = "+".join(core)
    if speaker_in_db:
        return {"own": "1_self", "own+public": "2_self_and_public", "public": "3_public_only"}.get(pattern, "4_other_person")
    return "5_proxy" if "person_obj" in pattern else "6_entity"


def difficulty(writes, task_type, stmts):
    f = {"multi_write": len(writes) >= 2, "multi_table": len({w["table"] for w in writes}) >= 2,
         "subquery": any(SUBQ.search(s) for s in stmts), "archive": has_archive(stmts),
         "public_or_other": task_type in ("2_self_and_public", "4_other_person")}
    score = sum(f.values())
    return {"score": score, "level": "easy" if score == 0 else "medium" if score <= 2 else "hard", "features": f}


def snapshot(db, tables):
    """Per table, what the eval hash compares: the non-volatile columns of every row, in a stable order."""
    out = {}
    for t in sorted(tables):
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({_q(t)})")]
        keep = ", ".join(_q(c) for c in cols if not VOLATILE_COL_RE.match(c))
        out[t] = (db.execute(f"SELECT {keep} FROM {_q(t)} ORDER BY {keep}").fetchall() if keep
                  else db.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone())
    return out


def rerun_changes(db, stmts, tables):
    """Run the statements again (every one that ran the first time, DDL included, so the second run starts from the
    same state), RERUN_GAP_S later. The caller's open transaction holds the first run. Returns the tables whose
    compared columns differ, '' when the runs agree."""
    first = snapshot(db, tables)
    db.execute("ROLLBACK"); time.sleep(RERUN_GAP_S); db.execute("BEGIN")
    try:
        for s in stmts:
            db.execute(s).fetchall()
    except sqlite3.Error as e:
        return f"rerun failed: {e}"
    second = snapshot(db, tables)
    return ", ".join(t for t in sorted(tables) if first[t] != second[t])


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
    # DySQL's validated property (2432/2432 gold writes) is "in SOME anchor's scope", not the speaker's anchor:
    # customers also edit public tables only another anchor reaches (chinook playlist_track)
    scope = {t for a in db_rec["anchors"] for t in (a["table"], *a["down"], *a["up"])}
    speaker_in_db = (cand.get("plan") or {}).get("task_type", "1_self") != "5_proxy" if "plan" in cand else cand.get("speaker_in_db", True)
    db = _memory_copy(db_rec["path"])
    tracer = Tracer(db_rec, db)
    pks = schema.pk_info(db)
    auto_next = {t.lower(): v["next"] for t, v in pks.items() if v["omittable"]}
    auto_col = {t.lower(): v["cols"][0] for t, v in pks.items() if v["omittable"]}
    row = db.execute(f"SELECT * FROM {_q(anchor['table'])} WHERE {_q(anchor['key'])} = ?", (cand["key_value"],)).fetchone()
    # calibration candidates may name several speaker rows (DySQL's classifier matched same-name people)
    speaker_ids = {tuple(x) for x in cand.get("speaker_ids") or [(anchor["table"], str(cand["key_value"]))]}
    rows = [row] if row else []
    for t, k in speaker_ids:
        if (t, k) != (anchor["table"], str(cand["key_value"])):
            key = next((a["key"] for a in db_rec["anchors"] if a["table"] == t), None)
            if key:
                rows += db.execute(f"SELECT * FROM {_q(t)} WHERE {_q(key)} = ?", (k,)).fetchall()
    allowed = {norm_literal(v) for r in rows for v in r if v not in (None, "")}
    # capture pre-update FK/key values, like classify_dysql_tasks.py: 'move my order to product 9' is still 'own'
    db.execute("CREATE TEMP TABLE _old (tbl TEXT, j TEXT)")
    for t in scope:
        need = {c for c, _, _ in tracer.up.get(t, [])} | ({tracer.persons[t]} if t in tracer.persons else set())
        if need:
            obj = ", ".join(f"'{c}', OLD.{_q(c)}" for c in sorted(need))
            db.execute(f"CREATE TEMP TRIGGER {_q('_u_' + t)} BEFORE UPDATE ON main.{_q(t)} BEGIN "
                       f"INSERT INTO _old VALUES ('{t}', json_object({obj})); END")
    stmts, labels, executed = [], [], []   # executed: every statement that ran, in order (writes and DDL)
    db.execute("BEGIN")
    try:
        for a in cand["actions"]:
            for st in split_statements(a["sql"]):
                if TXN.match(st):   # would commit or end the check's own transaction
                    out["reasons"].append(f"txn_control: {st[:40]}"); continue
                wt = write_target(st)
                try:
                    if not wt:
                        db.execute(st).fetchall(); executed.append(st); continue
                    cur = db.execute(st + " RETURNING *")
                    rcols = [d[0] for d in cur.description]
                    rs = cur.fetchall()
                except sqlite3.Error as e:
                    out["reasons"].append(f"sql_error: {e} in {st[:80]}"); continue
                executed.append(st)
                op, table = wt[0], tracer.canon(wt[1])
                stmts.append(st)
                key = table.lower()
                if op == "INSERT" and key in auto_next:
                    # keys SQLite would assign anyway: an agent may leave them out, so the user need not say them,
                    # here or in a later statement that refers to the new row
                    for r in rs:
                        v = dict(zip(rcols, r)).get(auto_col[key])
                        if v != auto_next[key]:
                            break
                        allowed.add(norm_literal(v)); auto_next[key] += 1
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
                    if owners & speaker_ids:
                        lab = "own"
                    elif op == "INSERT" and table in tracer.persons:
                        lab = "new_person"   # a person row that did not exist before is nobody else's data yet
                    else:
                        lab = "other" if owners else "public"
                else:
                    lab = "person_obj" if owners else "public"
                if len(rs) > cfg["MAX_ROWS_PER_STMT"]:
                    out["reasons"].append(f"bulk: {len(rs)} rows in {op} {table}")
                labels.append(lab)
                out["writes"].append({"op": op, "table": table, "rows": len(rs), "label": lab})
        if any(NONDET.search(s) for s in executed) and not any(x.startswith("sql_error") for x in out["reasons"]):
            changed = rerun_changes(db, executed, {tracer.canon(write_target(s)[1]) for s in stmts})
            if changed:
                out["reasons"].append("nondeterministic: " + changed)
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


def run_check_safe(db_rec, cand, **kw):
    """run_check that never raises: an unexpected failure becomes a 'crash:' reason, so one odd candidate cannot
    stop the check step for a whole database."""
    try:
        return run_check(db_rec, cand, **kw)
    except Exception as e:
        return {"id": cand.get("id"), "ok": False, "reasons": [f"crash: {type(e).__name__}: {e}"[:300]], "writes": [],
                "task_type": None, "template": None, "difficulty": None}
