# taskgen/v2/taskgen_v2/audit.py
"""Audit of finished tasks (2026-10-06): rules for what neither the check nor the verifier looks at, run over every
task and, for reference, over DySQL's gold. A flag means "read this task", not "bad"; its rate among DySQL's own tasks
says how much of it is just DySQL's style.
- instr_matches_more: the values the instruction gives select more rows than the gold changes (ambiguous target).
- where_broader: the instruction names the changed rows by key, the gold's WHERE does not use that key.
- dangling_fk: a written row points at a row that does not exist at the end.
- claim_not_found: "from X to Y", "currently X": no row the gold updates held X.
- case_mismatch / new_category / format_shape / type_mismatch / padded_value: a written value unlike the column's.
- copy_order: an INSERT ... SELECT numbers its copies in table order, the instruction lists rows that differ in another
  order (copies of identical rows end the same whatever the order: WWE stores some matches several times).
- key_collision: a key the task writes (primary key, unique column, or a column other tables point at) ends up on
  two rows (Airlines declares no keys: tickets renumbered onto another booking's ticket numbers).
- noop_update: an UPDATE that leaves every row it matches as it was (the instruction's "it is wrong" is false).
- duplicate_name: an inserted name or title that a row of the same table already holds ('Silver' added to colour).
- update_then_delete: a row the task updates and later deletes (the update is moot).
- identity: the speaker's key and name are missing, ambiguous, or another person's name appears (person tasks).
- dysql_near_dup: an instruction close to one of DySQL's (leakage)."""
import json, re, sqlite3
from collections import Counter
from taskgen_common.db_select import _q
from taskgen_v2 import check, dedup, schema

JSON_ARGS = check.JSON_ARGS
_VALUE = r"""'(?:[^']|'')+'|"[^"]+"|\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|-?\d[\d,]*(?:\.\d+)?(?![\w-])"""
FROM_TO = re.compile(r"(?i)\bfrom\s+(?:(?:the|a|an|its|my|his|her|their|our)\s+)?(?:[a-z_]+\s+){0,3}?(" + _VALUE +
                     r")\s+(?:(?:up|down|back|over)\s+)?to\b")
# what a record holds now: after a strong cue ("currently", "still shows", "stored as"; not "should be recorded as"),
# "shows A, but" / "shows A instead of B", and B of "should read A, not B"; the words between a cue and its value are
# lower-case nouns ("currently shows passport '5740 173123'"), not part of a name ("listed as Deacon 'Deke' Kaye")
_GAP = r"\s+(?:(?:as|the|a|an)\s+)?(?-i:[a-z_]+\s+){0,2}?"
CURRENT = re.compile(r"(?i)\b(?:currently|still|(?:stored|recorded|listed|logged|entered|saved|keyed\s+in)\s+as)" + _GAP +
                     r"(" + _VALUE + r")")
SHOWS_BUT = re.compile(r"(?i)\b(?:shows?|reads?|says?|lists?|has)" + _GAP + r"(" + _VALUE + r")\s*,?\s+(?:but|instead|rather|whereas)\b")
NOT_B = re.compile(r"(?i)\b(?:should|must|ought\s+to)\s+(?:read|be|say|show|list)\s+(?:as\s+)?(?:" + _VALUE +
                   r")\s*,?\s+(?:not|instead\s+of|rather\s+than)\s+(?:the\s+)?(" + _VALUE + r")")
# a target, not the current value: the clause before the cue asks for it ("so the name reads X instead of Y",
# "wants the city recorded as X", "should be recorded as X")
TARGET = re.compile(r"(?i)\b(?:should|must|so|to|will|would|could|can|needs?|wants?|asks?|asked|make|set)\b")
SMALL_DOMAIN = 12        # a column with at most this many distinct values is a category
MIN_ROWS = 30            # ... over at least this many rows
SHAPE_SHARE = 0.95       # a column whose two commonest value shapes cover this share has a format
NEAR_DUP = 0.5           # word 3-gram Jaccard with a DySQL instruction


def _top_words(s):
    """(position, upper-cased word) of each word outside quotes and parentheses."""
    out, depth, i, n = [], 0, 0, len(s)
    while i < n:
        c = s[i]
        if c in "'\"`[":
            close = "]" if c == "[" else c
            j = i + 1
            while j < n:
                if s[j] == close:
                    if close in "'\"" and j + 1 < n and s[j + 1] == close:   # a doubled quote inside the literal
                        j += 2; continue
                    break
                j += 1
            i = j + 1; continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and (c.isalpha() or c == "_") and (i == 0 or not (s[i - 1].isalnum() or s[i - 1] in "_$")):
            m = re.match(r"[A-Za-z_][A-Za-z0-9_$]*", s[i:])
            out.append((i, m.group(0).upper())); i += m.end(); continue
        i += 1
    return out


def where_conjuncts(stmt):
    """The top-level AND terms of a statement's WHERE (the AND of a BETWEEN kept), the whole WHERE as one term when it
    has a top-level OR, None without a WHERE."""
    words = _top_words(stmt)
    w = next((p for p, x in words if x == "WHERE"), None)
    if w is None:
        return None
    end = next((p for p, x in words if p > w and x in ("ORDER", "LIMIT", "RETURNING")), len(stmt))
    inner = [(p, x) for p, x in words if w < p < end]
    if any(x == "OR" for _, x in inner):
        return [stmt[w + 5:end].strip()]
    parts, start, between = [], w + 5, False
    for p, x in inner:
        if x == "BETWEEN":
            between = True
        elif x == "AND":
            if between:
                between = False; continue
            parts.append(stmt[start:p].strip()); start = p + 3
    parts.append(stmt[start:end].strip())
    return [x for x in parts if x]


def conj_literals(conj):
    return check.literals("SELECT 1 WHERE " + conj)


def _norm(v):
    return check.norm_literal(v)


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def same_value(claim, stored):
    """A value an instruction states equals a stored one: numbers by value, text case- and accent-insensitive, a
    date by the date part of a stored datetime."""
    a, b = _num(claim), _num(stored)
    if a is not None and b is not None:
        return a == b
    x, y = _norm(claim), _norm(stored)
    return x == y or (re.match(r"^\d{4}-\d{2}-\d{2}$", x) is not None and y.startswith(x))


def claims(instruction):
    """The values an instruction says a record holds now: X of "from X to Y" and of "currently X" and the like."""
    out, text = [], instruction or ""
    quoted = [m.span() for m in re.finditer(r"'(?:[^']|'')*'|\"[^\"]*\"", text)]
    for rx in (FROM_TO, CURRENT, SHOWS_BUT, NOT_B):
        for m in rx.finditer(text):
            if any(a < m.start() < b for a, b in quoted):   # inside a quoted value ('... from 1910 to 1960.')
                continue
            clause = re.split(r"[.;:!?,]", text[:m.start()])[-1]
            if rx in (CURRENT, SHOWS_BUT) and TARGET.search(clause):
                continue
            v = m.group(1)
            if v[:1] in "'\"":
                v = v[1:-1].replace("''", "'")
            out.append(v.replace(",", "") if _num(v) is not None else v)
    return out


def shape(v):
    """Digits as 9, runs of letters as a, the rest kept: '2017-07-05' -> '9999-99-99', 'AB-12' -> 'a-99'."""
    return re.sub(r"[A-Za-z]+", "a", re.sub(r"\d", "9", str(v)))


def find_pos(text, n):
    """Where n first occurs in text as a whole token (check._contains), else None."""
    before = r"(?:(?<!\w)|(?<=\d))" if n.isalpha() else r"(?<!\w)"
    m = re.search(before + re.escape(n) + r"(?!\w)", text)
    return m.start() if m else None


def order_mismatch(keys, text):
    """The keys the text mentions, in the order a statement uses them, when the text names them in another order."""
    pos = [(k, find_pos(text, _norm(k))) for k in keys]
    seen = [(k, p) for k, p in pos if p is not None]
    if len(seen) < 2:
        return None
    return [k for k, _ in seen] if [p for _, p in seen] != sorted(p for _, p in seen) else None


def _json_row(cols, ref, rowid):
    """json_object of the row (BLOBs as NULL: JSON cannot hold them), with its rowid under '__rowid__' when it has one."""
    items = [f"'{c}', iif(typeof({ref}.{_q(c)}) = 'blob', NULL, {ref}.{_q(c)})" for c in cols]
    if rowid:
        items.insert(0, f"'__rowid__', {ref}.rowid")
    parts = [", ".join(items[i:i + JSON_ARGS]) for i in range(0, len(items), JSON_ARGS)]
    expr = f"json_object({parts[0]})"
    for p in parts[1:]:
        expr = f"json_patch({expr}, json_object({p}))"
    return expr


def insert_columns(stmt):
    """The columns an INSERT lists, or None when it lists none (every column)."""
    m = re.match(r'(?is)^\s*(?:insert|replace)\s+(?:or\s+\w+\s+)?into\s+' + check._NAME + r'\s*\(([^)]*)\)', stmt)
    return [c.strip().strip('"[]`') for c in m.group(5).split(",")] if m else None


class DbAudit:
    """One database: a writable in-memory copy (each task runs inside a transaction that is rolled back), the original
    file for column statistics, and the foreign keys (declared ones plus the given edges)."""

    def __init__(self, path, edges=()):
        self.path = path
        self.conn = check._memory_copy(path)
        self.orig = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.pk = schema.pk_info(self.conn)
        self.names = {n.lower(): n for (n,) in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.cols, self.stats, self.rowid = {}, {}, {}
        self.fks = {}
        for t in self.names.values():
            groups = {}
            for r in self.conn.execute(f"PRAGMA foreign_key_list({_q(t)})"):
                groups.setdefault(r[0], (r[2], []))[1].append((r[3], r[4]))
            for parent, pairs in groups.values():
                ref = [b for _, b in pairs]
                if any(b is None for b in ref):
                    ref = self.pk.get(self.canon(parent), {}).get("cols") or []
                if len(ref) == len(pairs):
                    self._edge(t, tuple(a for a, _ in pairs), parent, tuple(ref))
        for child, cols, parent, ref in edges:
            self._edge(child, tuple(cols), parent, tuple(ref))
        self.referenced = {}   # table -> columns another table points at (keys, declared or not)
        for lst in self.fks.values():
            for cols, parent, ref in lst:
                if len(ref) == 1:
                    self.referenced.setdefault(parent.lower(), set()).add(ref[0])

    def _edge(self, child, cols, parent, ref):
        if self.canon(parent).lower() not in self.names:
            return
        e = (tuple(cols), self.canon(parent), tuple(ref))
        lst = self.fks.setdefault(self.canon(child).lower(), [])
        if e not in lst:
            lst.append(e)

    def canon(self, t):
        return self.names.get(t.lower(), t)

    def columns(self, t):
        if t not in self.cols:
            self.cols[t] = [r[1] for r in self.conn.execute(f"PRAGMA table_info({_q(t)})")]
            sql = (self.conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (t,)).fetchone() or ("",))[0] or ""
            self.rowid[t] = not re.search(r"(?i)\bwithout\s+rowid\b", sql)
        return self.cols[t]

    def col_stats(self, t, c):
        k = (t, c)
        if k not in self.stats:
            o = self.orig
            n, d = o.execute(f"SELECT COUNT({_q(c)}), COUNT(DISTINCT {_q(c)}) FROM {_q(t)}").fetchone()
            vals = {v for (v,) in o.execute(f"SELECT DISTINCT {_q(c)} FROM {_q(t)} WHERE {_q(c)} IS NOT NULL")} if d <= SMALL_DOMAIN else None
            sample = [v for (v,) in o.execute(f"SELECT {_q(c)} FROM {_q(t)} WHERE {_q(c)} IS NOT NULL LIMIT 500")]
            types = Counter(type(v).__name__ for v in sample)
            shapes = Counter(shape(v) for v in sample if isinstance(v, str))
            self.stats[k] = {"n": n, "d": d, "vals": vals, "types": types, "shapes": shapes, "sample": len(sample)}
        return self.stats[k]

    def run(self, instruction, stmts, allowed=frozenset()):
        """Flags [{"k", ...}] and stats {} of one task. The database is unchanged afterwards."""
        flags, stats = [], Counter()
        text = check.text_forms(instruction)
        allowed = set(allowed)
        conn = self.conn
        conn.execute("BEGIN")
        try:
            conn.execute("CREATE TEMP TABLE _log (seq INTEGER PRIMARY KEY, n INTEGER, t TEXT, phase TEXT, j TEXT)")
            conn.execute("CREATE TEMP TABLE _cur (n INTEGER)"); conn.execute("INSERT INTO _cur VALUES (-1)")
            written = sorted({self.canon(w[1]) for st in stmts if (w := check.write_target(st))})
            for i, t in enumerate(written):
                cols = self.columns(t)
                if not cols:
                    continue
                for when, ev, ref, ph in (("BEFORE", "UPDATE", "OLD", "old"), ("BEFORE", "DELETE", "OLD", "old"),
                                          ("AFTER", "INSERT", "NEW", "new"), ("AFTER", "UPDATE", "NEW", "new")):
                    conn.execute(f"CREATE TEMP TRIGGER _a{i}_{ev}_{ph} {when} {ev} ON main.{_q(t)} BEGIN INSERT INTO _log "
                                 f"(n, t, phase, j) VALUES ((SELECT n FROM _cur), '{t}', '{ph}', "
                                 f"{_json_row(cols, ref, self.rowid[t])}); END")
            per = []   # (index, op, table, old rows, new rows)
            for n, st in enumerate(stmts):
                if check.TXN.match(st):
                    continue
                wt = check.write_target(st)
                conn.execute("UPDATE _cur SET n = ?", (n,))
                pre = {}
                if wt:
                    op, t = wt[0], self.canon(wt[1])
                    if op in ("UPDATE", "DELETE"):
                        pre["more"] = self._given_count(st, t, instruction, allowed, stats)
                    if op == "INSERT" and check.ARCHIVE_SRC.match(st):
                        pre["copy"] = self._copy_keys(st, t)
                try:
                    conn.execute(st).fetchall()
                except sqlite3.Error as e:
                    flags.append({"k": "sql_error", "stmt": n, "error": str(e)[:120]}); continue
                if not wt:
                    continue
                rows = conn.execute("SELECT phase, j FROM _log WHERE n = ? ORDER BY seq", (n,)).fetchall()
                old = [json.loads(j) for p, j in rows if p == "old"]
                new = [json.loads(j) for p, j in rows if p == "new"]
                per.append((n, op, t, old, new))
                if pre.get("more") and pre["more"][0] > len(old):
                    flags.append({"k": "instr_matches_more", "stmt": n, "table": t, "given": pre["more"][0],
                                  "gold": len(old), "not_given": pre["more"][1]})
                if op in ("UPDATE", "DELETE") and old:
                    flags += self._broader(n, st, t, old, text, allowed)
                if op == "UPDATE" and old and all(o == r for o, r in zip(old, new)):
                    flags.append({"k": "noop_update", "stmt": n, "table": t, "rows": len(old)})
                if op == "DELETE":
                    gone = {r.get("__rowid__") for r in old} - {None}
                    hit = [m for m, op2, t2, o2, _ in per[:-1] if op2 == "UPDATE" and t2 == t and gone & {r.get("__rowid__") for r in o2}]
                    if hit:
                        flags.append({"k": "update_then_delete", "stmt": n, "table": t, "updated_in": hit})
                if op == "INSERT" and not check.ARCHIVE_SRC.match(st):
                    flags += self._dup_names(n, t, new)
                if pre.get("copy") and len(new) >= 2:
                    mism = order_mismatch(pre["copy"], text)
                    if mism:
                        flags.append({"k": "copy_order", "stmt": n, "table": t, "keys_in_table_order": mism})
                    elif sum(find_pos(text, _norm(k)) is not None for k in pre["copy"]) < len(pre["copy"]):
                        stats["copy_order_unstated"] += 1
                flags += self._values(n, op, st, t, old, new)
                if op == "INSERT":   # keys the task itself created may appear in later statements
                    for r in new:
                        for c in (self.pk.get(t) or {}).get("cols") or []:
                            if r.get(c) is not None:
                                allowed.add(_norm(r[c]))
            flags += self._dangling(per)
            flags += self._collisions(per)
            flags += self._claims(instruction, per)
            self.last = per   # [(statement index, op, table, old rows, new rows)], for the reading packets
        finally:
            conn.execute("ROLLBACK")
        return flags, dict(stats)

    def _given_count(self, st, t, instruction, allowed, stats):
        """(rows the given terms select, the terms not given) when some WHERE terms use values the instruction does not
        give and the rest use at least one it does; None otherwise. Counts self-contained statements in stats."""
        conjs = where_conjuncts(st)
        if not conjs:
            return None
        given, missing, from_text = [], [], False
        for c in conjs:
            lits = conj_literals(c)
            if not lits:
                given.append(c); continue
            if all(check.literal_ok(l, instruction, allowed) for l in lits):
                given.append(c)
                from_text = from_text or any(check.literal_ok(l, instruction, set()) and _norm(l) not in check.IMPLIED
                                             for l in lits)
            else:
                missing.append(c)
        stats["stmts_with_where"] += 1
        if not missing:
            stats["stmts_self_contained"] += 1
            return None
        if not given or not from_text:
            return None
        try:
            (k,) = self.conn.execute(f"SELECT COUNT(*) FROM {_q(t)} WHERE " + " AND ".join(f"({c})" for c in given)).fetchone()
        except sqlite3.Error:
            return None
        return k, missing

    def _copy_keys(self, st, t):
        """The source keys of an INSERT ... SELECT into a table that numbers new rows itself, in the order the SELECT
        returns them (the order the copies get their numbers); None otherwise."""
        info = self.pk.get(t) or {}
        if not info.get("rowid_alias") or check.names_column(st, info["cols"][0]):
            return None
        m = check.ARCHIVE_SRC.match(st)
        src = self.canon(next(g for g in m.groups() if g))
        sk = (self.pk.get(src) or {}).get("cols") or []
        if len(sk) != 1:
            return None
        frm = next((p for p, x in _top_words(st[st.lower().index("select"):]) if x == "FROM"), None)
        if frm is None:
            return None
        rest = st[st.lower().index("select"):][frm:]
        try:
            keys = [str(k) for (k,) in self.conn.execute(f"SELECT {_q(src)}.{_q(sk[0])} {rest}").fetchall()]
            cols = [c for c in self.columns(src) if c != sk[0]]
            rows = self.conn.execute(f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(src)} WHERE {_q(sk[0])} IN "
                                     f"({', '.join('?' * len(keys))})", keys).fetchall() if keys and cols else []
        except sqlite3.Error:
            return None
        return keys if len(set(rows)) > 1 else None   # copies of identical rows: the order cannot matter

    def _dup_names(self, n, t, new):
        """Inserted names or titles another row of the table already holds (case and spaces aside)."""
        out = []
        fk_cols = {c for cols, _, _ in self.fks.get(t.lower(), []) for c in cols}   # enlist.name is the person's key
        names = [c for _, c in check.name_columns(self.orig, [t])]
        info = list(self.orig.execute(f"PRAGMA table_info({_q(t)})"))
        if len(info) <= 3:   # a small lookup's label column, whatever it is called (superhero colour.colour)
            names += [r[1] for r in info if re.search(r"(?i)char|text", r[2] or "") and r[1] not in names]
        for c in [c for c in names if c not in fk_cols]:
            st = self.col_stats(t, c)
            if not st["n"] or st["d"] < 0.9 * st["n"]:   # a lookup's names are unique; people share first names
                continue
            for r in new:
                v = r.get(c)
                # two rows hold it right after the insert (a row deleted and entered again is not a duplicate)
                if isinstance(v, str) and v.strip() and self.conn.execute(
                        f"SELECT COUNT(*) FROM {_q(t)} WHERE lower(trim({_q(c)})) = ?", (v.strip().lower(),)).fetchone()[0] > 1:
                    out.append({"k": "duplicate_name", "stmt": n, "table": t, "col": c, "value": v[:60]})
        return out

    def _collisions(self, per):
        """Key values the task wrote that two rows hold at the end: the primary key, a unique column, or a column other
        tables point at (most of these databases declare no keys on them)."""
        out, done = [], set()
        for n, op, t, old, new in per:
            info = self.pk.get(t) or {}
            keys = set(self.referenced.get(t.lower(), ())) | {u[0] for u in schema.unique_columns(self.conn, t) if len(u) == 1}
            if len(info.get("cols") or []) == 1:
                keys.add(info["cols"][0])
            olds = {r.get("__rowid__"): r for r in old}
            for r in new:
                for c in keys:
                    v = r.get(c)
                    o = olds.get(r.get("__rowid__")) if op == "UPDATE" else None
                    if v in (None, "") or (o is not None and o.get(c) == v) or (t, c, str(v)) in done:
                        continue
                    done.add((t, c, str(v)))
                    (k,) = self.conn.execute(f"SELECT COUNT(*) FROM {_q(t)} WHERE {_q(c)} = ?", (v,)).fetchone()
                    if k > 1:
                        out.append({"k": "key_collision", "stmt": n, "table": t, "col": c, "value": str(v)[:60], "rows": k})
        return out

    def _broader(self, n, st, t, old, text, allowed):
        """The instruction names every changed row by a key column the statement's WHERE does not use."""
        keys = (self.pk.get(t) or {}).get("cols") or next(iter(schema.key_groups(self.conn, t)), [])
        lits = {_norm(l) for l in check.literals(st)}
        nums = {_num(l) for l in lits if _num(l) is not None}
        out = []
        for c in keys:
            vals = [r.get(c) for r in old]
            if any(v is None for v in vals):
                continue
            nv = [_norm(v) for v in vals]
            if any(x in allowed for x in nv) or any(len(x) < 3 and x.isdigit() for x in nv):
                continue
            if all(check._contains(text, x) for x in nv) and not any(x in lits or _num(x) in nums for x in nv):
                out.append({"k": "where_broader", "stmt": n, "table": t, "col": c, "values": sorted(set(nv))[:5]})
        return out

    def _values(self, n, op, st, t, old, new):
        """Written values unlike the column's stored ones (copies of existing rows left out)."""
        if op == "INSERT" and check.ARCHIVE_SRC.match(st):
            return []
        out = []
        if op == "INSERT":
            named = insert_columns(st)
            pairs = [(None, r) for r in new]
        else:
            named = None
            pairs = list(zip(old, new))
        for o, r in pairs:
            for c, v in r.items():
                if c == "__rowid__" or v is None or (o is not None and o.get(c) == v):
                    continue
                if named is not None and c.lower() not in {x.lower() for x in named}:
                    continue
                if o is None and named is None and c in ((self.pk.get(t) or {}).get("cols") or []):
                    continue
                s = self.col_stats(t, c)
                if isinstance(v, str) and v != v.strip():
                    out.append({"k": "padded_value", "stmt": n, "table": t, "col": c, "value": v[:60]})
                if isinstance(v, str) and s["vals"] is not None and s["n"] >= MIN_ROWS and v not in s["vals"] \
                        and s["types"].most_common(1)[0][0] == "str":   # a text category; numbers are amounts, not labels
                    low = {str(x).lower() for x in s["vals"]}
                    kind = "case_mismatch" if str(v).lower() in low else "new_category"
                    out.append({"k": kind, "stmt": n, "table": t, "col": c, "value": str(v)[:60],
                                "existing": sorted(map(str, s["vals"]))[:12]})
                top = s["types"].most_common(1)
                kind = lambda x: "number" if x in ("int", "float") else x   # NUMERIC affinity stores 71950.00 as 71950
                if top and s["sample"] >= MIN_ROWS and top[0][1] >= SHAPE_SHARE * s["sample"] and kind(type(v).__name__) != kind(top[0][0]):
                    out.append({"k": "type_mismatch", "stmt": n, "table": t, "col": c, "value": str(v)[:60],
                                "usual": top[0][0]})
                strs = sum(s["shapes"].values())
                if isinstance(v, str) and re.search(r"\d", v) and strs >= MIN_ROWS:
                    common = [x for x, _ in s["shapes"].most_common(2)]
                    if sum(s["shapes"][x] for x in common) >= SHAPE_SHARE * strs and shape(v) not in common:
                        out.append({"k": "format_shape", "stmt": n, "table": t, "col": c, "value": v[:60], "usual": common})
        return out

    def _dangling(self, per):
        """Rows the task wrote that point, at the end, at a row that does not exist (a new value only)."""
        out, done = [], set()
        for n, op, t, old, new in per:
            olds = {r.get("__rowid__"): r for r in old}
            for r in new:
                rid = r.get("__rowid__")
                if rid is not None and not self.conn.execute(f"SELECT 1 FROM {_q(t)} WHERE rowid = ?", (rid,)).fetchone():
                    continue   # deleted again later in the task
                for cols, parent, ref in self.fks.get(t.lower(), []):
                    vals = [r.get(c) for c in cols]
                    if any(v in (None, "") for v in vals):
                        continue
                    o = olds.get(r.get("__rowid__")) if op == "UPDATE" else None
                    if o is not None and [o.get(c) for c in cols] == vals:
                        continue
                    key = (t, cols, tuple(map(str, vals)))
                    if key in done:
                        continue
                    done.add(key)
                    where = " AND ".join(f"{_q(c)} = ?" for c in ref)
                    try:
                        hit = self.conn.execute(f"SELECT 1 FROM {_q(parent)} WHERE {where} LIMIT 1", vals).fetchone()
                    except sqlite3.Error:
                        continue
                    if not hit:
                        out.append({"k": "dangling_fk", "stmt": n, "table": t, "cols": list(cols), "parent": parent,
                                    "values": [str(v) for v in vals]})
        return out

    def _claims(self, instruction, per):
        """Values the instruction says a record holds now that no row the gold updates or deletes held."""
        rows = [r for _, op, _, old, _ in per if op in ("UPDATE", "DELETE") for r in old]
        if not rows or not any(op == "UPDATE" for _, op, _, _, _ in per):
            return []
        held = [v for r in rows for c, v in r.items() if c != "__rowid__" and v is not None]
        return [{"k": "claim_not_found", "value": x} for x in claims(instruction) if not any(same_value(x, v) for v in held)]


def identity(conn, root, key, key_value, name_cols, instruction, name_index):
    """Person tasks: [flags] on how the instruction identifies the person. name_index: {normalized full name: count}
    over the root table."""
    text = check.text_forms(instruction)
    row = conn.execute(f"SELECT {', '.join(_q(c) for c in name_cols)} FROM {_q(root)} WHERE {_q(key)} = ?",
                       (key_value,)).fetchone() if name_cols else None
    parts = [str(v) for v in (row or ()) if v not in (None, "")]
    full = _norm(" ".join(parts))
    has_key = check._contains(text, _norm(key_value))
    tokens = [_norm(w) for p in parts for w in p.split() if len(w) >= 2]
    has_name = bool(tokens) and all(check._contains(text, x) for x in tokens)
    out = []
    if not has_key and not has_name:
        out.append({"k": "identity_missing"})
    elif not has_key and full and name_index.get(full, 0) > 1:
        out.append({"k": "identity_ambiguous", "name": full, "rows": name_index[full]})
    others = set()
    for run in re.findall(r"[A-Z][a-zA-Z'\-.]*(?:\s+[A-Z][a-zA-Z'\-.]*)+", instruction or ""):
        w = run.split()
        for i in range(len(w)):   # every two- and three-word stretch of a run of capitalized words ("I'm Bob Ray")
            for k in (2, 3):
                x = _norm(" ".join(w[i:i + k]).rstrip(".,"))
                if len(w[i:i + k]) == k and x in name_index and x != full and x not in full:   # WWE tag teams
                    others.add(x)
    others = sorted(others)
    if others and not has_name:
        out.append({"k": "identity_other_name", "names": others[:3], "own": full})
    return out


def name_index(conn, root, name_cols):
    """{normalized full name: rows} of a person table (first + last, or one name column)."""
    if not name_cols:
        return {}
    c = Counter()
    for r in conn.execute(f"SELECT {', '.join(_q(x) for x in name_cols)} FROM {_q(root)}"):
        full = _norm(" ".join(str(v) for v in r if v not in (None, "")))
        if " " in full:
            c[full] += 1
    return dict(c)


def near_dup(instruction, dysql_shingles):
    """The largest word 3-gram Jaccard between an instruction and DySQL's instructions."""
    s = dedup._shingles(instruction)
    if not s:
        return 0.0
    return max((len(s & k) / len(s | k) for k in dysql_shingles if k), default=0.0)
