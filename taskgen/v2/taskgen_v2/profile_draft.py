# taskgen/v2/taskgen_v2/profile_draft.py
"""The generation model drafts a database profile (design §4.1): it sees every table with its key, columns, foreign
keys, BIRD's column notes and a few rows, the reviewer's hints (the roots, known data quirks) and two hand-written
DySQL profiles. A draft that fails db_profile.validate goes back with the problems, at most REPAIR_ROUNDS times;
whatever is left is saved with the problems for the reviewer."""
import json, os
from taskgen_common.db_select import _q
from taskgen_v2 import db_profile, io, schema

HINTS_JSON = os.path.join(io.DATA, "profile_hints.json")
EXAMPLES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile_examples.json")
SAMPLE_ROWS, VALUE_CHARS, NOTE_CHARS = 3, 60, 150
DRAFT_TEMPERATURE, DRAFT_MAX_TOKENS, REPAIR_ROUNDS = 0.3, 16384, 2

SYSTEM = """You write the profile of a SQLite database for a task generator. The generator writes realistic requests in which one person asks a database agent to change data (their orders, bookings, records), so it needs to know who the people are, which records belong to them, and which rows those records point to.

## Fields
- roots: the people requests are about; use exactly the tables the hints name. [{{"table", "label", "parents"}}]
  label: a word or two for the person ("customer"). parents: rows the person's own row points to that help understand it (their department, their sales rep); same shape as an event's parents.
- persons: every table whose rows are people, the roots and anyone else (employees, drivers, agents): {{"<table>": {{"key", "name_cols", "same_as"}}}}.
  key: the column that identifies one person. name_cols: the columns holding the person's name. same_as: ["table.column", ...] for columns elsewhere that hold this person's key without a foreign key (usually []).
- events: the records that belong to a root person, one entry per way of reaching them: {{"table", "label", "path", "parents"}}.
  path: the foreign keys from the root table down to the event table, root side first, each written "child_table.column -> parent_table.column". The first one ends at a root table; each next one ends at the table the previous one starts from.
  A table appears twice when a person reaches it two ways (matches won, matches lost).
  parents: the rows an event row points to that a person needs to understand it (a purchase -> the product -> its brand; a shipment -> its truck, driver and city): [{{"table", "via", "parents"}}], via being the foreign key from the row above to this table. Nest one or two levels.
- attributes: one-to-one tables that only add facts about a person: [{{"table", "of", "via"}}], via going from the attribute table to the person table.
- public: reference tables that belong to nobody (products, brands, locations, categories, courses) and that a request may change. Never a table of people.
- exclude: tables requests must not touch: calendar or helper tables, tables of other people that the roots never reach, tables whose changes would make no sense.
- no_insert: tables that must not get new rows because their key has no meaningful next value (UUIDs, codes like 'rec4Xa0').
- quirks: short English sentences about data oddities the generator must respect (misspelled column names, swapped values).
- description: two or three English sentences: what the database records and who the people in it are.
- confirmed: false

## Rules
- Use table and column names exactly as the schema writes them (case, spaces, hyphens).
- Every table must appear somewhere: in roots, persons, events (as the table or on a path), parents, attributes, public or exclude.
- A composite foreign key is written "child.(a, b) -> parent.(x, y)".
- Use the foreign keys listed under "references", or columns whose values clearly hold another table's key.
- Answer with the profile as JSON inside <answer></answer>.

## Examples
{examples}"""

USER = """# Database {key}

## Hints from the person who will review the profile
Roots: {roots}
{notes}

## Schema
{schema}

Write the profile."""

REPAIR = """The profile has these problems:
{errors}
Answer with the whole corrected profile as JSON inside <answer></answer>."""


def _short(v):
    return v[:VALUE_CHARS] + "..." if isinstance(v, str) and len(v) > VALUE_CHARS else v


def compact_schema(conn, fks=(), composite=(), notes=None, samples=SAMPLE_ROWS):
    """Every table the way the drafting prompt shows it: rows, key and how new keys come about, columns with types,
    foreign keys, BIRD's column notes, a few rows."""
    pk, out = schema.pk_info(conn), []
    for t in sorted(pk, key=str.lower):
        cols = list(conn.execute(f"PRAGMA table_info({_q(t)})"))
        (n,) = conn.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()
        k = pk[t]
        if k["omittable"]:
            key = f"key {k['cols'][0]} (INTEGER; a new row may leave it out)"
        elif k["rowid_alias"]:
            key = f"key {k['cols'][0]} (INTEGER AUTOINCREMENT, sequence ahead of MAX; a new row needs an explicit id)"
        elif len(k["cols"]) == 1:
            key = f"key {k['cols'][0]} ({next(c[2] for c in cols if c[1] == k['cols'][0]) or 'no type'})"
        else:
            key = f"key ({', '.join(k['cols'])})" if k["cols"] else "no primary key"
        lines = [f"TABLE {t} -- {n} rows; {key}", "  columns: " + ", ".join(f"{c[1]} {c[2]}".strip() for c in cols)]
        refs = [f"{f['col']} -> {f['ref_table']}.{f['ref_col']}" + ("" if f.get("source") == "declared" else " (inferred)")
                for f in fks if f["table"] == t]
        refs += [f"({', '.join(f['cols'])}) -> {f['ref_table']}.({', '.join(f['ref_cols'])})" for f in composite if f["table"] == t]
        if refs:
            lines.append("  references: " + "; ".join(refs))
        if (notes or {}).get(t):
            lines.append("  notes: " + "; ".join(f"{c}: {d[:NOTE_CHARS]}" for c, d in notes[t].items()))
        for r in conn.execute(f"SELECT * FROM {_q(t)} LIMIT {samples}").fetchall() if samples else []:
            row = {c[1]: (f"<blob {len(v)} bytes>" if isinstance(v, (bytes, memoryview)) else _short(v)) for c, v in zip(cols, r)}
            lines.append("  row: " + json.dumps(row, ensure_ascii=False, default=str))
        out.append("\n".join(lines))
    return "\n".join(out)


def pragma_fks(conn):
    """The foreign keys a database declares, in the anchors JSON shape (single-column ones; DySQL's example databases
    have no anchors record)."""
    out = []
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
        out += [{"table": t, "col": r[3], "ref_table": r[2], "ref_col": r[4], "source": "declared"}
                for r in conn.execute(f"PRAGMA foreign_key_list({_q(t)})")]
    return out


def load_examples(path=EXAMPLES_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _examples_text(examples):
    return "\n\n".join(f"### {x['db']}\nSchema:\n{x['schema']}\n\nProfile:\n{json.dumps(x['profile'], ensure_ascii=False, indent=1)}"
                       for x in examples)


def messages(db_key, conn, rec, db_path, hints, examples):
    notes = "\n".join(f"- {n}" for n in hints.get("notes") or []) or "(no notes)"
    user = USER.format(key=db_key, roots=", ".join(hints["roots"]), notes=notes,
                       schema=compact_schema(conn, rec["fks"], rec.get("fks_composite", ()), schema.column_descriptions(db_path)))
    return [{"role": "system", "content": SYSTEM.format(examples=_examples_text(examples))}, {"role": "user", "content": user}]


def parse(text):
    """The profile JSON object in a model answer; ValueError when there is none."""
    last = None
    for cand in io.json_candidates(text or ""):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError as e:
            last = e
            continue
        if isinstance(obj, dict) and "roots" in obj:
            return obj
    raise ValueError(f"no profile JSON in the answer: {last}")


def draft(client, db_key, conn, rec, db_path, hints, examples):
    """A profile draft with confirmed=false and a 'draft' record {model, rounds, errors}; errors is [] when it validates."""
    msgs = messages(db_key, conn, rec, db_path, hints, examples)
    prof, errs, rounds, model = None, [], 0, None
    for rounds in range(1, REPAIR_ROUNDS + 2):
        resp = client.chat(msgs, temperature=DRAFT_TEMPERATURE, max_tokens=DRAFT_MAX_TOKENS)
        model = resp.get("model")
        try:
            got = parse(resp["content"])
        except ValueError as e:
            errs = [str(e)]
        else:
            prof = {**got, "confirmed": False}
            errs = db_profile.validate(prof, conn, rec["fks"], rec.get("fks_composite", ()))
            roots = [r.get("table") for r in prof.get("roots") or [] if isinstance(r, dict)]
            if roots != list(hints["roots"]):
                errs.append(f"roots: must be exactly {', '.join(hints['roots'])}, as the hints say")
        if not errs:
            break
        msgs = msgs + [{"role": "assistant", "content": resp["content"]},
                       {"role": "user", "content": REPAIR.format(errors="\n".join(f"- {e}" for e in errs))}]
    return {**(prof or {}), "confirmed": False, "notes": [], "draft": {"model": model, "rounds": rounds, "errors": errs}}
