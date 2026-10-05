# taskgen/v2/taskgen_v2/check.py
"""Execution check of a candidate task on an in-memory copy of its database, plus the derived labels
(task type, difficulty, template) that dedup and the pilot statistics use. Nothing here calls a model."""
import json, re, sqlite3, unicodedata
from collections import Counter
import sqlparse
from sqlparse import tokens as T
from taskgen_common.db_select import _q
from taskgen_v2 import db_profile, owners, prompt, schema

WRITE = re.compile(r"(?is)^\s*(insert|update|delete|replace)\b")
TARGET = re.compile(r'(?is)^\s*(?:insert\s+(?:or\s+\w+\s+)?into|replace\s+into|update(?:\s+or\s+\w+)?|delete\s+from)\s+'
                    r'(?:"([^"]+)"|\[([^\]]+)\]|`([^`]+)`|([\w$]+))')
SUBQ = re.compile(r"(?is)\(\s*select\b")
TXN = re.compile(r"(?is)^\s*(begin|commit|end|rollback|savepoint|release)\b")
_NAME = r'(?:"([^"]+)"|\[([^\]]+)\]|`([^`]+)`|([\w$]+))'
# archive = INSERT whose source is a SELECT (not a subquery inside VALUES) ...
ARCHIVE_SRC = re.compile(r"(?is)^\s*insert\b(?:(?!\bvalues\b).)*?\bselect\b.*?\bfrom\s+" + _NAME)
# gold that reads the clock or random(): run it twice and compare what the eval hash compares. Date functions called
# without a time value read the clock too: date(), datetime(), julianday(), strftime('%H:%M'); so does "now", which
# SQLite reads as the string 'now' when no column has that name
NONDET = re.compile(r"(?i)\bcurrent_(?:timestamp|time|date)\b|'now'|\"now\"|\brandom(?:blob)?\s*\(|\bunixepoch\s*\(|"
                    r"\b(?:date|time|datetime|julianday)\s*\(\s*\)|\bstrftime\s*\(\s*'(?:[^']|'')*'\s*\)")
# columns the eval hash skips, copied from DySQL-Bench/dysql_bench/envs/base.py (test_volatile_columns_match_the_eval)
VOLATILE_COL_RE = re.compile(
    r"(?i)^(last_?update|updated_?at|update_?time|modified(_at)?|modification_?time|create(d)?_?at|timestamp)$")
# the two clock readings of the rerun: the same day at two times, so values precise to the day agree and pass, and
# values precise to the hour, minute or second differ (the 1.1-second rerun of plan 1 let minutes and hours through)
INSTANTS = ("2000-01-01 00:00:00", "2000-01-01 13:37:42")

ENTITY = "6_entity"
# where names are kept: owner_name, LongTitle, artist; not owner_city (food_inspection) or name_id (imdb_movies)
NAME_COL = re.compile(r"(?i)(name|title)$|^owner$|author|artist|director|commander")
# a quote opened by an apostrophe (I'm, it's) is not a quote: it needs a non-letter before ' and after the closing '
QUOTED = re.compile(r"(?<![A-Za-z])'([^'\n]{2,80})'(?![A-Za-z])|\"([^\"\n]{2,80})\"|“([^”\n]{2,80})”|‘([^’\n]{2,80})’")
JSON_ARGS = 60   # columns per json_object(): SQLite lets a function take 127 arguments (card_games.cards has 74 columns)


def quoted(text):
    """The normalized strings an instruction puts in quotes ('Smoked Trout', "Menu 3")."""
    return {norm_literal(next(g for g in m.groups() if g is not None)) for m in QUOTED.finditer(text or "")}


def name_columns(db, tables):
    """[(table, column)] of the text columns that hold names or titles (NAME_COL) in the given tables."""
    out = []
    for t in sorted(tables):
        for r in db.execute(f"PRAGMA table_info({_q(t)})"):
            if NAME_COL.search(r[1]) and not re.search(r"(?i)int|real|num|float|double", r[2] or ""):
                out.append((t, r[1]))
    return out


def stored(db, cols, value):
    """The first (table, column) of cols where some row holds value (trimmed, case-insensitive), else None."""
    for t, c in cols:
        if db.execute(f"SELECT 1 FROM {_q(t)} WHERE lower(trim({_q(c)})) = ? LIMIT 1", (value,)).fetchone():
            return t, c
    return None


def person_name_stored(db, name):
    """Whether a sampled speaker name is stored in the database: as a whole value of a name column, or split over a
    first-name and a last-name column of one row (chicago_crime's alderman_first_name, alderman_last_name)."""
    n = norm_literal(name)
    tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    if stored(db, name_columns(db, tables), n):
        return True
    first, _, last = n.partition(" ")
    for t in tables:
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({_q(t)})")]
        f = next((c for c in cols if re.search(r"(?i)first.?name", c)), None)
        l = next((c for c in cols if re.search(r"(?i)last.?name|surname", c)), None)
        if f and l and db.execute(f"SELECT 1 FROM {_q(t)} WHERE lower(trim({_q(f)})) = ? AND lower(trim({_q(l)})) = ? LIMIT 1",
                                  (first, last)).fetchone():
            return True
    return False


def _json_row(cols, ref="OLD"):
    """json_object(...) of the columns, in chunks of JSON_ARGS merged with json_patch."""
    parts = [", ".join(f"'{c}', {ref}.{_q(c)}" for c in cols[i:i + JSON_ARGS]) for i in range(0, len(cols), JSON_ARGS)]
    expr = f"json_object({parts[0]})"
    for p in parts[1:]:
        expr = f"json_patch({expr}, json_object({p}))"
    return expr


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


def names_column(stmt, col):
    """Whether an INSERT gives a value for col: its column list names it, or it has no column list (every column)."""
    m = re.match(r'(?is)^\s*(?:insert|replace)\s+(?:or\s+\w+\s+)?into\s+' + _NAME + r'\s*\(([^)]*)\)', stmt)
    return not m or col.lower() in [c.strip().strip('"[]`').lower() for c in m.group(5).split(",")]


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
_MDY = re.compile(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")
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
    """n occurs in text as a whole token: '203' is not in '2030', 'ann' is not in 'joanna'. A word of three letters
    or more may take a plural ending ('cup' in '2 cups'; 'M' is not in 'Ms') and a unit may follow a number ('g' in
    '10g'), as in DySQL's cookbook gold."""
    before = r"(?:(?<!\w)|(?<=\d))" if n.isalpha() else r"(?<!\w)"
    after = r"(?:e?s)?(?!\w)" if n[-1:].isalpha() and len(n) >= 3 else r"(?!\w)"
    return re.search(before + re.escape(n) + after, text) is not None


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
        return any(_num(m) == v for m in re.findall(r"(?<![\w.])-?\d[\d,]*\.?\d*", text))   # a whole number: not 3174 in 'c00003174'
    return False


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


def at_instant(stmt, instant):
    """The statement with every clock reading replaced by a fixed instant: 'now' or "now", CURRENT_TIMESTAMP/DATE/TIME,
    and date functions called without a time value. A column default that reads the clock is not replaced; none of the
    36 databases (23 here, 13 in DySQL) has one."""
    day, tod = instant.split()
    s = re.sub(r"(?i)\bcurrent_timestamp\b", f"'{instant}'", stmt)
    s = re.sub(r"(?i)\bcurrent_date\b", f"'{day}'", s)
    s = re.sub(r"(?i)\bcurrent_time\b", f"'{tod}'", s)
    s = re.sub(r"(?i)'now'|\"now\"", f"'{instant}'", s)
    s = re.sub(r"(?i)\b(date|time|datetime|julianday|unixepoch)\s*\(\s*\)", rf"\1('{instant}')", s)
    return re.sub(r"(?i)\bstrftime\s*\(\s*('(?:[^']|'')*')\s*\)", rf"strftime(\1, '{instant}')", s)


def rerun_changes(db, stmts, tables):
    """Run the statements again twice, at the two INSTANTS (every statement that ran the first time, DDL included, so
    both runs start from the same state), and compare what the eval hash compares. The caller's open transaction
    holds the first run. Returns the tables whose compared columns differ, '' when the runs agree."""
    snaps = []
    for instant in INSTANTS:
        db.execute("ROLLBACK"); db.execute("BEGIN")
        try:
            for st in stmts:
                db.execute(at_instant(st, instant)).fetchall()
        except sqlite3.Error as e:
            return f"rerun failed: {e}"
        snaps.append(snapshot(db, tables))
    return ", ".join(t for t in sorted(tables) if snaps[0][t] != snaps[1][t])


def _keys(db, table, col):
    return {str(k) for (k,) in db.execute(f"SELECT {_q(col)} FROM {_q(table)}")}


def _max_rowid(db, table):
    """MAX(rowid) before an INSERT ... SELECT, so the rows it adds can be told apart; None for WITHOUT ROWID tables."""
    try:
        return db.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM {_q(table)}").fetchone()[0]
    except sqlite3.Error:
        return None


def _copy_rows(db, table, rowids):
    if not rowids:
        return None
    marks = ",".join("?" * len(rowids))
    return db.execute(f"SELECT rowid, * FROM {_q(table)} WHERE rowid IN ({marks}) ORDER BY rowid", sorted(rowids)).fetchall()


def _memory_copy(path):
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:", isolation_level=None)
    src.backup(db); src.close()
    return db


def final_state(db_path, stmts):
    """How the statements leave the tables they write, as the eval hash sees them: per table, the rows (non-volatile
    columns) added and removed against the original file, as sorted lists that keep duplicates. Run on a fresh copy
    with the clock read at INSTANTS[0]; None when a statement fails. Temporary triggers note the rowids a statement
    touches, so only those rows are compared (eu_soccer's Match has 26k rows of 115 columns)."""
    db = _memory_copy(db_path)
    try:
        db.execute("ATTACH DATABASE ? AS orig", (db_path,))
        db.execute("CREATE TEMP TABLE _touched (t TEXT, r INTEGER)")
        tables = sorted({w[1].lower() for st in stmts if (w := write_target(st))})
        for n, t in enumerate(tables):
            for ev, ref in (("INSERT", "NEW"), ("UPDATE", "OLD"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
                db.execute(f"CREATE TEMP TRIGGER _f{n}_{ev}_{ref} AFTER {ev} ON main.{_q(t)} BEGIN "
                           f"INSERT INTO _touched VALUES ('{n}', {ref}.rowid); END")
        for st in stmts:
            db.execute(at_instant(st, INSTANTS[0])).fetchall()
        out = {}
        for n, t in enumerate(tables):
            cols = [r[1] for r in db.execute(f"PRAGMA main.table_info({_q(t)})")]
            keep = ", ".join(_q(c) for c in cols if not VOLATILE_COL_RE.match(c)) or "1"
            now, before = (Counter(db.execute(f"SELECT {keep} FROM {s}.{_q(t)} WHERE rowid IN "
                                              f"(SELECT r FROM _touched WHERE t = '{n}')").fetchall()) for s in ("main", "orig"))
            out[t] = (sorted((now - before).elements(), key=repr), sorted((before - now).elements(), key=repr))
        return out
    except sqlite3.Error:
        return None
    finally:
        db.close()


def name_mismatches(db, profile, tracer, cand, stmts, seen):
    """A quoted name the database stores, but in none of the rows near the task (design 2026-10-04 §3.4): the root's
    row and its attribute rows, the rows the task touches (before and after), and every row these lead to within
    owners.MAX_HOPS foreign keys (region_sales -> game_platform -> platform). DySQL's cookbook named one ingredient and
    wrote another's ID in 16 of 51 tasks, and the verifier sees no rows. Values the SQL itself writes or matches are
    new names, not claims about a row."""
    def fetch(table, cols, vals, limit=3):
        try:
            cur = db.execute(f"SELECT * FROM {_q(table)} WHERE " + " AND ".join(f"{_q(c)} = ?" for c in cols) + f" LIMIT {limit}", vals)
        except sqlite3.Error:
            return []
        names = [d[0] for d in cur.description]
        return [(table, dict(zip(names, r))) for r in cur.fetchall()]
    root = cand["anchor_table"]
    rows = fetch(root, [profile["persons"][root]["key"]], [cand["key_value"]], 1)
    for a in profile["attributes"]:
        e = db_profile.parse_edge(a["via"])
        if a["of"] == root and rows:
            rows += fetch(e.child, e.cols, [rows[0][1].get(c) for c in e.ref_cols], 50)
    rows += list(seen)
    frontier = rows
    for _ in range(owners.MAX_HOPS):
        frontier = [x for t, r in frontier for cols, parent, ref_cols in tracer.up.get(t, [])
                    if all(r.get(c) not in (None, "") for c in cols) for x in fetch(parent, ref_cols, [r.get(c) for c in cols])]
        rows += frontier
    near = {norm_literal(v) for _, r in rows for v in r.values() if isinstance(v, str)}
    written = {norm_literal(x) for s in stmts for x in literals(s)}
    cols = name_columns(db, db_profile.scope_tables(profile))
    return [f"name_mismatch: {hit[0]}.{hit[1]}" for s in sorted(quoted(cand["instruction"]) - near - written)
            if (hit := stored(db, cols, s))]


def entity_reasons(db, profile, tracer, speaker_ids, cand, stmts, labels, writes, seen, new_public):
    """What an entity task may not do (design 2026-10-04 §3.4), checked on the database after its statements ran."""
    out = ["other_person"] if "other" in labels else []
    out += [f"root_insert: {w['table']}" for w in writes if w["label"] == "new_person"]
    lookups = {}
    for x in profile.get("new_lookup") or []:
        e = db_profile.parse_edge(x["via"])
        lookups.setdefault(e.parent, []).append((e, x["name_cols"]))
    out += [f"public_write: {w['op']} {w['table']}" for w in writes
            if w["label"] == "public" and (w["op"] != "INSERT" or w["table"] not in lookups)]
    if "own" not in labels and any(x != "noop" for x in labels):
        out.append("no_own_write")
    for table, new in new_public:
        used = False
        for e, names in lookups.get(table, []):
            cur = db.execute(f"SELECT * FROM {_q(e.child)} WHERE " + " AND ".join(f"{_q(c)} = ?" for c in e.cols) + " LIMIT 50",
                             [new.get(c) for c in e.ref_cols])
            cols = [d[0] for d in cur.description]
            used = used or any(tracer.trace(e.child, dict(zip(cols, r))) & speaker_ids for r in cur.fetchall())
            same = " AND ".join(f"lower(trim({_q(c)})) = lower(trim(?))" for c in names)
            if db.execute(f"SELECT COUNT(*) FROM {_q(table)} WHERE {same}", [new.get(c) for c in names]).fetchone()[0] > 1:
                out.append(f"lookup_name_taken: {table}")
        if table in lookups and not used:
            out.append(f"lookup_unreferenced: {table}")
    name = ((cand.get("plan") or {}).get("style") or {}).get("name")
    if name and person_name_stored(db, name):
        out.append("speaker_name_taken")
    out += name_mismatches(db, profile, tracer, cand, stmts, seen)
    return list(dict.fromkeys(out))   # one reason per kind and table


def run_check(db_rec, cand, anchor=None, cfg=prompt.CFG, profile=None):
    """With a profile (generated candidates), scope, people and ownership come from it, INSERT into no_insert tables
    and writes to another person's data are rejected; without one (DySQL gold, v1 candidates), as in v1."""
    out = {"id": cand.get("id"), "ok": False, "reasons": [], "writes": [], "task_type": None, "template": None, "difficulty": None}
    if not cand.get("instruction"):
        out["reasons"].append("no_instruction"); return out
    if not cand.get("actions"):
        out["reasons"].append("no_actions"); return out
    if profile:
        anchor = anchor or db_profile.root_anchor(profile, cand["anchor_table"])
        scope = db_profile.scope_tables(profile)
    else:
        anchor = anchor or next(a for a in db_rec["anchors"] if a["table"] == cand["anchor_table"])
        # DySQL's validated property (2432/2432 gold writes) is "in SOME anchor's scope", not the speaker's anchor:
        # customers also edit public tables only another anchor reaches (chinook playlist_track)
        scope = {t for a in db_rec["anchors"] for t in (a["table"], *a["down"], *a["up"])}
    entity = bool(profile) and db_profile.kind(profile) == "entity"
    # 6_entity is not 5_proxy, so speaker_in_db holds: the entity's rows are "own" the way a speaker's are
    speaker_in_db = (cand.get("plan") or {}).get("task_type", "1_self") != "5_proxy" if "plan" in cand else cand.get("speaker_in_db", True)
    db = _memory_copy(db_rec["path"])
    tracer = owners.Tracer.from_profile(profile, db_rec, db) if profile else owners.Tracer.from_rec(db_rec, db)
    auto = {t.lower(): (t, v["cols"][0]) for t, v in schema.pk_info(db).items() if v["omittable"]}   # D9 tables
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
        need = {c for cols, _, _ in tracer.up.get(t, []) for c in cols} | ({tracer.persons[t]} if t in tracer.persons else set())
        if entity:   # the whole row before the change: the names it held belong to the task (name_mismatches)
            need = {r[1] for r in db.execute(f"PRAGMA table_info({_q(t)})")}
        if need:
            db.execute(f"CREATE TEMP TRIGGER {_q('_u_' + t)} BEFORE UPDATE ON main.{_q(t)} BEGIN "
                       f"INSERT INTO _old VALUES ('{t}', {_json_row(sorted(need))}); END")
    seen, new_public = [], []   # rows the task touched (before and after); new public rows
    stmts, labels, executed = [], [], []   # executed: every statement that ran, in order (writes and DDL)
    copies = {}   # table -> rowids an INSERT ... SELECT added: the archived copies, which later writes must leave alone
    numbered = {}   # table -> INSERT ... SELECTs whose copies SQLite numbered, in statement order
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
                    op, table = wt[0], tracer.canon(wt[1])
                    key = table.lower()
                    # what SQLite would give a row that leaves the key out, at this point of the task
                    nxt = schema.next_rowid(db, *auto[key]) if op == "INSERT" and key in auto else None
                    existing = (_keys(db, table, tracer.persons[table])
                                if op == "INSERT" and speaker_in_db and table in tracer.persons else set())
                    top = _max_rowid(db, table) if op == "INSERT" and ARCHIVE_SRC.match(st) else None
                    before = _copy_rows(db, table, copies.get(table)) if op != "INSERT" else None
                    cur = db.execute(st + " RETURNING *")
                    rcols = [d[0] for d in cur.description]
                    rs = cur.fetchall()
                except sqlite3.Error as e:
                    out["reasons"].append(f"sql_error: {e} in {st[:80]}"); continue
                executed.append(st)
                stmts.append(st)
                if top is not None:
                    copies.setdefault(table, set()).update(
                        x for (x,) in db.execute(f"SELECT rowid FROM {_q(table)} WHERE rowid > ?", (top,)))
                if before:   # one statement over the copies and other rows: it meant the originals and hit the copies too
                    hit = len(set(before) - set(_copy_rows(db, table, copies[table]) or ()))
                    if hit and len(rs) > hit:
                        out["reasons"].append(f"archive_copy_changed: {op} {table}")
                if top is not None and key in auto and not names_column(st, auto[key][1]):
                    numbered[table] = numbered.get(table, 0) + 1
                    if numbered[table] == 2:   # one INSERT ... SELECT for all rows would number them in table order
                        out["reasons"].append(f"archive_split: {table}")
                if nxt is not None:
                    # keys SQLite would assign anyway: an agent may leave them out, so the user need not say them,
                    # here or in a later statement that refers to the new row
                    for r in rs:
                        v = dict(zip(rcols, r)).get(auto[key][1])
                        if v != nxt:
                            break
                        allowed.add(norm_literal(v)); nxt += 1
                if table not in scope:
                    out["reasons"].append(f"out_of_scope: {table}")
                if profile and op == "INSERT" and table in profile["no_insert"]:
                    out["reasons"].append(f"no_insert: {table}")
                for lit in literals(st):
                    if not literal_ok(lit, cand["instruction"], allowed):
                        out["reasons"].append(f"literal_missing: '{lit}' in {op} {table}"); break
                holders = set()
                for r in rs[:50]:
                    holders |= tracer.trace(table, dict(zip(rcols, r)))
                for (j,) in db.execute("SELECT j FROM _old WHERE tbl = ? LIMIT 50", (table,)).fetchall():
                    old = json.loads(j)
                    holders |= tracer.trace(table, old)
                    seen.append((table, old))
                seen += [(table, dict(zip(rcols, r))) for r in rs[:50]]
                db.execute("DELETE FROM _old")
                if not rs:
                    lab = "noop"
                    if op != "INSERT":
                        out["reasons"].append(f"noop_write: {op} {table}")
                elif speaker_in_db:
                    if holders & speaker_ids:
                        lab = "own"
                    elif op == "INSERT" and table in tracer.persons and not any(
                            str(dict(zip(rcols, r)).get(tracer.persons[table])) in existing for r in rs):
                        lab = "new_person"   # a person row that did not exist before is nobody else's data yet
                    else:
                        lab = "other" if holders else "public"
                else:
                    lab = "person_obj" if holders else "public"
                if len(rs) > cfg["MAX_ROWS_PER_STMT"]:
                    out["reasons"].append(f"bulk: {len(rs)} rows in {op} {table}")
                labels.append(lab)
                if entity and lab == "public" and op == "INSERT":
                    new_public += [(table, dict(zip(rcols, r))) for r in rs]
                out["writes"].append({"op": op, "table": table, "rows": len(rs), "label": lab})
        if entity:
            out["reasons"] += entity_reasons(db, profile, tracer, speaker_ids, cand, stmts, labels, out["writes"], seen, new_public)
        if any(NONDET.search(s) for s in executed) and not any(x.startswith("sql_error") for x in out["reasons"]):
            changed = rerun_changes(db, executed, {tracer.canon(write_target(s)[1]) for s in stmts})
            if changed:
                out["reasons"].append("nondeterministic: " + changed)
    finally:
        if db.in_transaction:   # a Ctrl-C between the rerun's ROLLBACK and BEGIN leaves none open; ROLLBACK would hide it
            db.execute("ROLLBACK")
        db.close()
    if not out["writes"] or (all(w["rows"] == 0 for w in out["writes"])
                             and not any(r.startswith("noop_write") for r in out["reasons"])):
        out["reasons"].append("no_write")   # nothing written, or only zero-row INSERT ... SELECT
    out["task_type"] = task_group(speaker_in_db, labels) if out["writes"] else None
    if entity and out["task_type"] not in (None, "7_no_change"):
        out["task_type"] = ENTITY
    if profile and out["task_type"] == "4_other_person":
        out["reasons"].append("other_person")   # design D6: the agent policy denies requests about another person
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
