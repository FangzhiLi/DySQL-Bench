# taskgen/v2/taskgen_v2/corrupt.py
"""Five ways to break a task's SQL while its instruction stays, for the verifier's calibration (design D5): change a
literal, drop a WHERE condition, change the column an UPDATE sets, drop the last write, swap two values. A broken
task counts as a negative only when it still passes the execution check and ends in another database state --
the mistakes only the verifier can catch (calibrate.negatives filters them)."""
import sqlparse
from sqlparse import sql as S, tokens as T
from taskgen_common.db_select import _q
from taskgen_v2 import check

KINDS = ("literal", "where", "set_column", "drop_last", "swap_values")


def statements(cand):
    return [st for a in cand["actions"] for st in check.split_statements(a["sql"])]


def _render(stmt, new):
    """The statement's text with some leaf tokens replaced: new is {id(token): text}."""
    return "".join(new.get(id(t), t.value) for t in stmt.flatten())


def _literal_tokens(stmt):
    return [t for t in stmt.flatten() if t.ttype in T.Literal.String.Single or t.ttype in T.Literal.Number]


def _kind(tok):
    return "str" if tok.ttype in T.Literal.String.Single else "num"


def _writes(stmts):
    return [i for i, st in enumerate(stmts) if check.write_target(st)]


def _with(cand, stmts):
    return {**cand, "actions": [{"sql": st} for st in stmts]}


def change_literal(cand, rng, conn=None):
    """One literal of a write becomes another value of the same kind that the task's writes use elsewhere (an
    amount for another amount, a name for another name), so the check's literal rule still holds."""
    stmts = statements(cand)
    parsed = {i: sqlparse.parse(stmts[i])[0] for i in _writes(stmts)}
    toks = [(i, t) for i, p in parsed.items() for t in _literal_tokens(p)]
    pairs = [(i, t, u.value) for i, t in toks for _, u in toks if _kind(u) == _kind(t) and u.value != t.value]
    if not pairs:
        return None
    i, t, v = rng.choice(pairs)
    return _with(cand, stmts[:i] + [_render(parsed[i], {id(t): v})] + stmts[i + 1:])


def swap_values(cand, rng, conn=None):
    """Two different literals of one write trade places (two new values, or a value and a key)."""
    stmts = statements(cand)
    opts = []
    for i in _writes(stmts):
        p = sqlparse.parse(stmts[i])[0]
        lits = _literal_tokens(p)
        opts += [(i, p, a, b) for x, a in enumerate(lits) for b in lits[x + 1:] if a.value != b.value]
    if not opts:
        return None
    i, p, a, b = rng.choice(opts)
    return _with(cand, stmts[:i] + [_render(p, {id(a): b.value, id(b): a.value})] + stmts[i + 1:])


def _conjuncts(where):
    """The top-level AND-ed conditions of a WHERE clause as token lists; None when it has a top-level OR or a
    BETWEEN (whose AND is not a conjunction)."""
    parts, cur = [], []
    for t in where.tokens[1:]:
        if t.ttype is T.Keyword and t.normalized in ("OR", "BETWEEN"):
            return None
        if t.ttype is T.Keyword and t.normalized == "AND":
            parts.append(cur); cur = []
        else:
            cur.append(t)
    parts.append(cur)
    return [p for p in parts if "".join(x.value for x in p).strip()]


def drop_where(cand, rng, conn=None):
    """An UPDATE or DELETE loses one of its AND-ed WHERE conditions, or its whole WHERE when it has only one."""
    stmts = statements(cand)
    opts = []
    for i in _writes(stmts):
        if check.write_target(stmts[i])[0] == "INSERT":
            continue
        p = sqlparse.parse(stmts[i])[0]
        where = next((t for t in p.tokens if isinstance(t, S.Where)), None)
        parts = _conjuncts(where) if where else None
        if parts:
            opts += [(i, p, where, parts, k) for k in range(len(parts))]
    if not opts:
        return None
    i, p, where, parts, k = rng.choice(opts)
    rest = [p for j, p in enumerate(parts) if j != k]
    clause = (" WHERE " + " AND ".join("".join(x.value for x in q).strip() for q in rest)) if rest else ""
    head = "".join(t.value for t in p.tokens[:p.tokens.index(where)]).rstrip()
    return _with(cand, stmts[:i] + [head + clause] + stmts[i + 1:])


def set_column(cand, rng, conn):
    """An UPDATE sets another column of the same table and declared type instead of the one asked for (not a key
    column, not one the statement already sets)."""
    stmts = statements(cand)
    opts = []
    for i in _writes(stmts):
        op, table = check.write_target(stmts[i])
        if op != "UPDATE":
            continue
        p = sqlparse.parse(stmts[i])[0]
        k = next((x for x, t in enumerate(p.tokens) if t.ttype is T.Keyword and t.normalized == "SET"), None)
        nxt = next((t for t in p.tokens[k + 1:] if not t.is_whitespace), None) if k is not None else None
        comps = ([c for c in nxt.get_sublists() if isinstance(c, S.Comparison)] if isinstance(nxt, S.IdentifierList)
                 else [nxt] if isinstance(nxt, S.Comparison) else [])
        info = conn.execute(f"PRAGMA table_info({_q(table)})").fetchall()
        types = {r[1].lower(): (r[2] or "").upper() for r in info}
        keys = {r[1].lower() for r in info if r[5]}
        used = {c.left.get_real_name().lower() for c in comps if c.left.get_real_name()}
        for c in comps:
            col = (c.left.get_real_name() or "").lower()
            if col not in types:
                continue
            for r in info:
                if r[1].lower() not in used | keys and (r[2] or "").upper() == types[col]:
                    opts.append((i, p, c, r[1]))
    if not opts:
        return None
    i, p, c, new = rng.choice(opts)
    leaves = list(c.left.flatten())
    return _with(cand, stmts[:i] + [_render(p, {id(leaves[0]): _q(new), **{id(x): "" for x in leaves[1:]}})] + stmts[i + 1:])


def drop_last(cand, rng=None, conn=None):
    """The last write statement is gone (tasks with two writes or more)."""
    stmts = statements(cand)
    w = _writes(stmts)
    if len(w) < 2:
        return None
    return _with(cand, stmts[:w[-1]] + stmts[w[-1] + 1:])


FUNCS = {"literal": change_literal, "where": drop_where, "set_column": set_column, "drop_last": drop_last,
         "swap_values": swap_values}


def corrupt(cand, kind, rng, conn):
    """The task with its SQL broken in the given way, or None when the SQL offers no place for it."""
    return FUNCS[kind](cand, rng, conn)
