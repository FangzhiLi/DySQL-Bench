# taskgen/v2/taskgen_v2/prompt.py
"""Task plan sampling (type x write count x shape) and the generation prompt (design §4.3, §4.4). The SYSTEM message
holds the rules and one hand-written example for the task type; the USER message holds the database (description,
quirks, the event tree with whose data each row is, the schema and key notes) and the plan."""
import json, os, random
from taskgen_v2 import db_profile, trees

CFG = {
    # weights before a tree's feasible types are taken: legislator, student_loan and synthea have no public rows, so
    # over the 23 databases this lands near design §3's 50/13/6/31 (simulated on the plan-2 trees: 49/15/6/30)
    "TYPE_MIX": {"1_self": 0.47, "2_self_and_public": 0.17, "3_public_only": 0.07, "5_proxy": 0.29},   # no type 4 (D6)
    # write statements per task; type 2 never writes once, so overall this lands near DySQL's 33/45/13/6/3 (§4.4)
    "WRITES_MIX": {1: 0.37, 2: 0.41, 3: 0.13, 4: 0.06, 5: 0.03},
    # shape shares, set so the task-level rates over the 23 databases match DySQL's gold (simulated on the plan-2
    # trees): two tables 56%, subquery 12%, archive 6.3%, batch 6.5%
    "TWO_TABLES": 0.85,      # multi-write tasks that write two tables, when two are in scope
    "SUBQUERY": 0.13,        # tasks that find the person through a subquery (D8), when the tree has a lookup
    "BATCH": 0.12,           # tasks with one UPDATE/DELETE over 2-50 of the person's rows, when a group has 2 to 50
    "BATCH_ALL": 0.6,        # ... of which change all of the group's rows (DySQL: "all my invoices"), the rest by a condition
    "ARCHIVE": 0.70,         # tasks that copy rows with INSERT ... SELECT before changing them, when a table can, no
                             # batch is drawn and there is a write left for each other table (copy and change take two)
    "FREE_TABLE_SHARE": 0.30,
    "MAX_ROWS_PER_STMT": 50,
    "WORDS": (40, 80),       # instruction length asked for (DySQL: mean 57, p90 80)
    "EVENTS_SHOWN": {1: (3, 5), 2: (5, 8), 3: (8, 12)},   # by write count (3 = three or more), design §4.2
    "DATA_CHARS": 16000,      # data blocks longer than this lose events from the end (about 4k tokens)
    "MAX_VALUE_CHARS": 200,   # longer text values are cut in the prompt
    # 6_entity (design 2026-10-04 §3.3): who speaks, as hand-counted on DySQL's car and cookbook (43/13/22 of 78)
    "SPEAKER_MIX": {"name": 0.55, "role_or_username": 0.17, "none": 0.28},
    "NAME_WITH_ROLE": 0.5,   # named speakers who also give a role from the profile ("Markus Klein, an auto dealer")
    "USERNAME": 0.5,         # role_or_username speakers who give a username ("dana_chef2001") instead of a role
    "NEW_LOOKUP": 0.10,      # entity tasks that add a public lookup row and point an own row at it (cookbook's hard tasks)
}
PUBLIC_TYPES = ("2_self_and_public", "3_public_only")
ENTITY = "6_entity"   # an entity profile's only type (design 2026-10-04)
SPEAKERS = ("name", "role", "username", "none")
# style pools: the pilot reused the same invented names ("Priya Raghavan" x6) and roles, so a proxy speaker gets a
# sampled name and role, and every plan a sampled tone
FIRST_NAMES = ["Aisha", "Ben", "Carlos", "Dmitri", "Elena", "Farid", "Grace", "Hiro", "Ingrid", "Jamal", "Keiko", "Luis",
               "Maren", "Nikhil", "Olu", "Petra", "Quinn", "Rosa", "Sven", "Tomasz", "Uma", "Viktor", "Wen", "Ximena",
               "Yusuf", "Zoe", "Amara", "Bastian", "Chloe", "Diego", "Esther", "Felix", "Gwen", "Hassan", "Ines", "Jonas",
               "Kwame", "Leila", "Mateo", "Noor", "Oscar", "Priya", "Rafael", "Sanjay", "Tessa", "Ulrich", "Vera", "Walter"]
LAST_NAMES = ["Abbott", "Bauer", "Castillo", "Dubois", "Eriksen", "Ferreira", "Gallagher", "Haddad", "Ivanova", "Jensen",
              "Kowalski", "Lindqvist", "Moreau", "Nakamura", "Oyelaran", "Petrov", "Quiroga", "Rossi", "Schneider",
              "Takahashi", "Underwood", "Varga", "Whitaker", "Xu", "Yilmaz", "Zimmerman", "Adeyemi", "Brennan", "Chen",
              "Delacroix", "Espinoza", "Fischer", "Goldberg", "Hoffmann", "Iqbal", "Jorgensen", "Kim", "Lopez", "Mbeki",
              "Novak", "Okafor", "Pereira", "Rahman", "Santos", "Thornton", "Vasquez", "Weber", "Yamada"]
ROLES = ["data analyst", "account manager", "support agent handling a ticket", "internal auditor", "branch supervisor",
         "intern doing data entry", "compliance officer", "sales representative", "operations coordinator",
         "customer success manager", "database administrator", "quality assurance reviewer", "regional manager",
         "billing specialist", "field technician", "office assistant"]
TONES = ["terse and businesslike, straight to the change", "friendly, with a short reason for the change",
         "formal, like a support ticket", "a little impatient because this was asked before", "a casual chat message",
         "explains that someone else asked for the change", "apologetic, fixing an earlier mistake",
         "lists the changes as numbered steps", "mentions a deadline as the reason"]
EXAMPLES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples.json")

SYSTEM = """You write tasks for training a database customer-service agent. A task is one user's request, written as the user would type it to the agent, and the SQL statements ('actions') that carry it out.

## The instruction
1. The speaker writes in the first person and only asks for changes: no questions, no requests to look anything up, report or confirm.
2. Every value the SQL uses appears in the instruction: ids, keys, names, amounts, dates and new values. The only exceptions are the person's own identifying fields and new keys that the key notes say may be left out.
3. Each record to change is named by its id or key as shown in the data (for example "order 7731"), never only described.

## The actions
4. Only INSERT, UPDATE or DELETE statements, one per action, exactly as many as the task shape asks; no SELECT statements.
5. Standard SQLite. Wrap every table name in double quotes ("transaction" and "order" are keywords); quote column names with spaces or punctuation.
6. Every UPDATE or DELETE matches at least one row shown in the data; no statement changes more than {max_rows} rows.
7. Never change a key column. Give new rows their keys as the key notes say, and never INSERT into a table marked "no new rows".
8. Copy table names, column names and stored values exactly, even when they look misspelled or oddly formatted.

## Principles for generating SQL calls
- At the beginning of the conversation, you have to authenticate the user identity by locating their user.
- Once the user has been authenticated, you can provide the user with information, e.g. help the user look up order id.
- You can only help one user per conversation (but you can handle multiple requests from the same user), and must deny any requests for tasks related to any other user.
- You should not make up any information or knowledge or procedures not provided from the user, or give subjective recommendations or comments.
- You should at most make one sql call at a time, and if you take a sql call, you should not respond to the user at the same time. If you respond to the user, you should not make a sql call.
- You should transfer the user to a human agent if and only if the request cannot be handled within the scope of your actions.

These are the agent's policy (DySQL's data_pipeline_shell/sql_wiki.md), so a task never changes rows marked as another person's.

## Output format
Think inside <thought></thought>, then give the final answer inside <answer></answer> as strict JSON without comments:
{{"instruction": "...", "actions": [{{"sql": "..."}}, {{"sql": "..."}}]}}

## Instruction example (for style only: do not copy its wording, its values or its actions)
{example}"""

USER = """# Database
{description}
{quirks}
{data_blocks}

## Schema
{schema}

## Key notes
{keys}

## Task type
{type_text}

## Task shape
{shape_text}

## Style
{style_text}

Generate the task now."""

TYPE_TEXT = {
    "1_self": "The speaker is {name}, the person in {t} with {key} = {kv}. Their first sentence gives their name and their ID, written with the word ID or the column name ({key} {kv} or ID {kv}). Every write changes only rows marked own: rows marked public stay unchanged, and no new row is added to {t} (that would be a new person) or to a public table.",
    "2_self_and_public": "The speaker is {name}, the person in {t} with {key} = {kv}. Their first sentence gives their name and their ID, written with the word ID or the column name ({key} {kv} or ID {kv}). At least one write changes a row marked own and at least one changes a row marked public ({up}).",
    "3_public_only": "The speaker is {name}, the person in {t} with {key} = {kv}. Their first sentence gives their name and their ID, written with the word ID or the column name ({key} {kv} or ID {kv}). The writes change only rows marked public ({up}); none of the speaker's own rows change.",
    "5_proxy": "The speaker is not in the database: {proxy}. Their first sentence gives their own name and role, and the name and ID of {name}, whose data they ask to change, written with the word ID or the column name ({key} {kv} or ID {kv}). Every write changes only rows marked own (that person's rows): rows marked public stay unchanged, and no new row is added to {t} (that would be a new person).",
    ENTITY: "The speaker is not in the database, and nothing in it records who they are: {speaker}. The request is about the {label} in {t} with {key} = {kv}{named}. {first}, written with the word ID or the column name ({key} {kv} or ID {kv}). Every write changes only rows marked own (this {label}'s rows){lookup}; rows marked public stay unchanged, rows of another {label} stay untouched, and no new row is added to {t} (that would be another {label}).",
}


def load_examples():
    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _weighted(rng, weights):
    keys, w = zip(*weights.items())
    return rng.choices(keys, weights=w, k=1)[0]


def feasible_types(tree):
    """Types this tree can carry. An entity tree carries 6_entity only; never 4_other_person (design D6); 2 and 3 need
    a public row to write."""
    if tree.get("kind") == "entity":
        return [ENTITY]
    return ["1_self"] + (list(PUBLIC_TYPES) if trees.has_public(tree) else []) + ["5_proxy"]


def _who(task_type):
    if task_type == ENTITY:
        return "the record the request is about"
    return "the speaker's own row" if task_type != "5_proxy" else "the person the request is about"


def _username(rng):
    f, l = rng.choice(FIRST_NAMES).lower(), rng.choice(LAST_NAMES).lower()
    return rng.choice([f"{f}.{l[0]}", f"{l}_{rng.randint(10, 99)}", f"user_{rng.randint(1000, 9999)}", f"{f}{rng.randint(1970, 2005)}"])


def entity_speaker(rng, roles, cfg=CFG):
    """Who asks for an entity task (design 2026-10-04 §3.3): a sampled name (half of them with a role from the
    profile), a role or a username, or nobody in particular. The model never invents the name: the plan-3 pilot
    repeated 'Priya Raghavan' six times."""
    kind = _weighted(rng, cfg["SPEAKER_MIX"])
    out = {"speaker": kind, "name": None, "role": None, "username": None}
    if kind == "name":
        out["name"] = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        out["role"] = rng.choice(roles) if roles and rng.random() < cfg["NAME_WITH_ROLE"] else None
    elif kind == "role_or_username":
        if roles and rng.random() >= cfg["USERNAME"]:
            out.update(speaker="role", role=rng.choice(roles))
        else:
            out.update(speaker="username", username=_username(rng))
    return out


def entity_fmt(tree, plan):
    """The 6_entity placeholders of TYPE_TEXT: who speaks, which record, what their first sentence gives."""
    st, label, name = plan["style"], tree["root_label"], tree["anchor_name"]
    speaker = {"name": f"{st['name']}, " + (st["role"] or f"who looks after this {label} and calls it 'my {label}'"),
               "role": f"{st['role']}, who gives no name",
               "username": f"a user with the username {st['username']}, who gives no other name",
               "none": "someone who gives no name, role or username"}[st["speaker"]]
    own = {"name": "their name" + (" and role" if st["role"] else ""), "role": "their role",
           "username": "their username", "none": None}[st["speaker"]]
    record = f"the {label}'s name and its ID" if name else f"the {label}'s ID"
    first = (f"Their first sentence gives {own}, then {record}" if own
             else f"Their first sentence says nothing about who they are and gives {record}")
    look = plan["shape"].get("new_lookup")
    return {"speaker": speaker, "label": label, "named": f" ({name})" if name else "", "first": first,
            "lookup": f", except the one new {look['table']} row the task shape asks for" if look
                      else " and no new row is added to a public table"}


def rows_by_table(tree, refs):
    """{table: [row, ...]} of every row the prompt shows: the root row, its attributes and parents, and the shown
    events with their parents."""
    out = {}

    def walk(node):
        out.setdefault(node["table"], []).append(node["row"])
        for p in node["parents"]:
            walk(p)
    out[tree["anchor_table"]] = [tree["anchor_row"]]
    for t, rs in tree["attributes"].items():
        out.setdefault(t, []).extend(rs)
    for p in tree["parents"]:
        walk(p)
    for g in trees.shown(tree, refs):
        for n in g["rows"]:
            walk(n)
    return out


def _targets(rng, shown, tables, fixed, k=2):
    """Up to k 'table.column' values worth changing (design §4.4): columns of shown rows that are not keys or foreign
    keys and hold a short value, one per table where possible."""
    out = []
    for t in rng.sample(tables, len(tables)):
        cols = sorted({c for r in shown.get(t, []) for c, v in r.items()
                       if c not in fixed.get(t, ()) and v not in (None, "") and len(str(v)) <= 60})
        if cols:
            out.append(f"{t}.{rng.choice(cols)}")
        if len(out) == k:
            break
    return out


def sql_value(v):
    """A value as an SQL literal: text in single quotes (doubled inside), numbers as they are."""
    return "'" + v.replace("'", "''") + "'" if isinstance(v, str) else str(v)


def level(features):
    """check.difficulty's levels from the same features: none easy, one or two medium, three or more hard."""
    score = sum(bool(f) for f in features)
    return "easy" if score == 0 else "medium" if score <= 2 else "hard"


def sample_plan(rng, tree, anchor, cfg=CFG, ctx=None):
    """ctx: generate.context() of the database -- "fixed" {table: key and foreign-key columns}, never a change target,
    "copyable", the tables an archive may copy rows into (keys SQLite fills in, open to INSERT), and "pk" {table: key columns}."""
    ctx = ctx or {}
    fixed, copyable = ctx.get("fixed") or {}, set(ctx.get("copyable") or ())
    entity = tree.get("kind") == "entity"
    task_type = ENTITY if entity else _weighted(rng, {k: v for k, v in cfg["TYPE_MIX"].items() if k in feasible_types(tree)})
    n_writes = _weighted(rng, cfg["WRITES_MIX"])
    if task_type == "2_self_and_public":
        n_writes = max(n_writes, 2)
    lo, hi = cfg["EVENTS_SHOWN"][min(n_writes, 3)]
    refs = trees.pick_events(tree, rng, rng.randint(lo, hi), need_public=task_type in PUBLIC_TYPES)
    while len(refs) > 1 and len(data_blocks(tree, refs, _who(task_type), cfg)) > cfg["DATA_CHARS"]:
        refs.pop()                                           # the event a public type needs is first, so it stays
    tabs = trees.tables_by_label(tree, refs)
    pool = {"3_public_only": tabs["public"], "2_self_and_public": tabs["own"] + tabs["public"]}.get(task_type, tabs["own"])
    lookup = None   # an entity task may add one public lookup row and point a row of its own at it (cookbook's hard tasks)
    options = [x for x in ctx.get("new_lookup") or [] if db_profile.parse_edge(x["via"]).child in tabs["own"]] if entity else []
    if options and rng.random() < cfg["NEW_LOOKUP"]:
        x = rng.choice(options)
        e = db_profile.parse_edge(x["via"])
        lookup = {"table": e.parent, "child": e.child, "via": x["via"], "name_cols": list(x["name_cols"])}
        # under the root itself (game.genre_id) the entity has one row to point: more writes would update it again
        n_writes = 2 if e.child == tree["anchor_table"] else max(n_writes, 2)
        pool = pool + [e.parent]
    if not refs:   # no events: one row per table to write (hr_1's employees), so no more statements than tables
        n_writes = min(n_writes, len(pool))
    events = {g["table"] for g in tree["events"]}

    batch = None   # one statement over 2-50 of the person's rows of one event group: all of them, or by a condition
    groups = [g for g in tree["events"] if 2 <= g["count"] <= cfg["MAX_ROWS_PER_STMT"] and g["table"] in tabs["own"]]
    if task_type != "3_public_only" and not lookup and groups and rng.random() < cfg["BATCH"]:
        g = max(groups, key=lambda g: g["count"])
        batch = {"table": g["table"], "label": g["label"], "count": g["count"],
                 "all": rng.random() < cfg["BATCH_ALL"] or g["count"] < 3}   # two rows: a condition would pick 1 of them
    n_tables = 1
    if task_type == "2_self_and_public" or lookup:
        n_tables = 2
    elif n_writes >= 2 and len(pool) >= 2 and rng.random() < cfg["TWO_TABLES"]:
        n_tables = 2
    archive = None   # copy rows as new rows of the same table, then change the originals by key; never with a batch,
    # whose condition or whole group would match the copies too
    sources = [t for t in pool if t in copyable and t != anchor["table"] and (t in events or task_type == "3_public_only")]
    if not batch and not lookup and n_writes >= n_tables + 1 and sources and rng.random() < cfg["ARCHIVE"]:   # copy + change, one more per other table
        archive = rng.choice(sources)
    subquery = bool(tree.get("lookup")) and task_type != "3_public_only" and rng.random() < cfg["SUBQUERY"]

    must = archive or (batch and batch["table"])   # the one table a batch or an archive needs written
    write_tables = None
    if lookup:
        write_tables = [lookup["table"], lookup["child"]]
    elif rng.random() >= cfg["FREE_TABLE_SHARE"]:
        if task_type == "2_self_and_public":
            write_tables = [must or rng.choice(tabs["own"]), rng.choice(tabs["public"])]
        else:
            rest = [t for t in pool if t != must]
            write_tables = ([must] if must else []) + rng.sample(rest, n_tables - bool(must))
    shape = {"n_writes": n_writes, "n_tables": n_tables, "ownership_subquery": subquery, "archive": archive,
             "batch": batch, "public_table": task_type in PUBLIC_TYPES, "new_lookup": lookup}
    if archive:
        shape["archive_key"] = ((ctx.get("pk") or {}).get(archive) or [None])[0]
    difficulty = level([n_writes >= 2, n_tables >= 2, subquery, archive, task_type == "2_self_and_public"])
    style = {"tone": rng.choice(TONES), "name": None, "role": None}
    if task_type == "5_proxy":
        style.update(name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", role=rng.choice(ROLES))
    elif entity:
        style.update(entity_speaker(rng, ctx.get("speaker_roles") or [], cfg))
    return {"task_type": task_type, "difficulty": difficulty, "shape": shape, "write_tables": write_tables,
            "events": refs, "tables": tabs, "scope": pool,
            # a new lookup row is used by pointing the child's foreign key at it, so that is what an UPDATE changes
            "targets": ([f"{lookup['child']}.{c}" for c in db_profile.parse_edge(lookup["via"]).cols] if lookup
                        else _targets(rng, rows_by_table(tree, refs), write_tables or pool, fixed)),
            "example": rng.choice(load_examples()[f"{ENTITY}/{style['speaker']}" if entity else task_type]), "style": style}


def _short(row, cfg):
    """Long text (WWE keeps whole HTML pages in Cards) is cut for the prompt; nobody edits it by quoting it."""
    n = cfg["MAX_VALUE_CHARS"]
    return {k: (v[:n] + f"... ({len(v)} chars)" if isinstance(v, str) and len(v) > n else v) for k, v in row.items()}


def _label_text(label, other="another person's data"):
    if label.startswith("other:"):
        return f"{other}: {label[6:]}"
    return {"own": "own", "public": "public, shared reference data owned by nobody"}.get(label, label)


def _taken_lines(g):
    """What a new row of the group must not repeat (trees.taken), so the model does not pick a used pair."""
    out = []
    for cols, vals in (g.get("taken") or {}).items():
        shown = ", ".join("(" + ", ".join(sql_value(v) for v in t) + ")" if len(t) > 1 else sql_value(t[0]) for t in vals)
        more = " and others" if g["count"] > len(vals) else ""
        out.append(f"A new {g['table']} row must not repeat these ({cols}) values, already used: {shown}{more}.")
    return out


def data_blocks(tree, refs, who, cfg=CFG):
    """The root row with its attributes and parent rows, then each shown event group; parent rows are indented under
    the row that references them, and every row says whose data it is."""
    other = f"another {tree['root_label']}'s data" if tree.get("kind") == "entity" else "another person's data"

    def js(row):
        return json.dumps(_short(row, cfg), ensure_ascii=False, default=str)

    def lines(node, depth):
        out = [f"{'  ' * depth}- {node['table']} ({_label_text(node['label'], other)}): {js(node['row'])}"]
        for p in node["parents"]:
            out += lines(p, depth + 1)
        return out
    head = [f"## {tree['anchor_table']} record ({who})", js(tree["anchor_row"])]
    head += [f"- {t} (own): {js(r)}" for t, rs in tree["attributes"].items() for r in rs]
    head += [x for p in tree["parents"] for x in lines(p, 0)]
    blocks = ["\n".join(head)]
    for g in trees.shown(tree, refs):
        blocks.append(f"## {g['label']}: {g['table']} records ({len(g['rows'])} of {g['count']} shown)\n"
                      + "\n".join([x for n in g["rows"] for x in lines(n, 0)] + _taken_lines(g)))
    return "\n\n".join(blocks)


def shape_text(anchor, tree, plan, cfg=CFG):
    s, lines = plan["shape"], []
    noun = tree["root_label"] if tree.get("kind") == "entity" else "person"
    n, k = s["n_writes"], s["n_tables"]
    lines.append(f"- Exactly {n} write statement{'s' if n > 1 else ''} (INSERT, UPDATE or DELETE) on {k} table{'s' if k > 1 else ''}.")
    if plan["write_tables"]:
        lines.append(f"- Write to {', '.join(plan['write_tables'])}.")
    else:
        lines.append(f"- Choose the table{'s' if k > 1 else ''} among {', '.join(plan['scope'])}.")
    if s["public_table"]:
        lines.append(f"- At least one write changes a public table: {', '.join(plan['tables']['public'])}.")
    if s["batch"] and s["batch"]["all"]:
        b = s["batch"]
        lines.append(f"- One UPDATE or DELETE changes all {b['count']} of the {noun}'s {b['label']} rows in {b['table']} at once; "
                     f"the instruction says it means all of them.")
    elif s["batch"]:
        b = s["batch"]
        lines.append(f"- One UPDATE or DELETE changes several of the {noun}'s {b['label']} rows in {b['table']} at once (there "
                     f"are {b['count']}): select them by a condition such as a date range, a status or a value, written in the "
                     f"instruction exactly as the SQL uses it, not by listing ids; it changes between 2 and {b['count'] - 1} rows.")
    if s["archive"]:
        lines.append(f"- First copy all the {s['archive']} rows you will change, in one statement, as new rows with INSERT INTO \"{s['archive']}\" ... "
                     f"SELECT ... FROM \"{s['archive']}\", then UPDATE or DELETE the original rows by their "
                     + (f"{s['archive_key']} values; the copies get new {s['archive_key']} values and stay as they are."
                        if s.get("archive_key") else "keys; the copies get new keys and stay as they are."))
    if s["ownership_subquery"]:
        cond = " AND ".join(f"{c} = {sql_value(v)}" for c, v in tree["lookup"].items())
        lines.append(f"- Find the {noun}'s rows through a subquery on {anchor['table']}, e.g. WHERE {anchor['key']} = "
                     f"(SELECT {anchor['key']} FROM \"{anchor['table']}\" WHERE {cond}), instead of writing {anchor['key']} = {sql_value(tree['key_value'])}.")
    elif plan["task_type"] != "3_public_only":
        lines.append(f"- In the SQL, identify the {noun} by {anchor['key']} = {sql_value(tree['key_value'])}; names can repeat.")
    if s.get("new_lookup"):
        x = s["new_lookup"]
        via = x["via"].split("->")[0].strip()
        then = (f"then point this {noun}'s own {x['child']} row at it through {via}." if x["child"] == tree["anchor_table"]
                else f"then make one {x['child']} row of this {noun} refer to it through {via}: change an existing row or add a new one.")
        lines.append(f"- First add one new row to {x['table']} whose {' and '.join(x['name_cols'])} no {x['table']} row has yet "
                     f"(say it in the instruction), {then} No other {x['table']} row changes.")
    if plan["targets"]:
        lines.append(f"- If you UPDATE, change {' or '.join(plan['targets'])}.")
    return "\n".join(lines)


def style_text(plan, cfg=CFG):
    st, (lo, hi) = plan.get("style") or {}, cfg["WORDS"]
    return "\n".join([f"- Tone: {st.get('tone', 'natural')}.",
                      f"- {lo} to {hi} words in three or four sentences.",
                      "- Do not reuse phrases from the example, and do not open with 'Hi, this is' or 'Good morning'."])


def build_messages(db_rec, anchor, tree, plan, materials, cfg=CFG):
    """materials: generate.context() output -- the profile's description and quirks, the schema text, key notes."""
    tabs, st = plan["tables"], plan.get("style") or {}
    fmt = {"name": tree["anchor_name"] or f"the person with {anchor['key']} = {tree['key_value']}", "key": anchor["key"],
           "kv": tree["key_value"], "t": anchor["table"], "up": ", ".join(tabs["public"]) or "(none)",
           "proxy": f"{st.get('name')}, {st.get('role')}"}
    if plan["task_type"] == ENTITY:
        fmt.update(entity_fmt(tree, plan))
    quirks = materials.get("quirks") or []
    user = USER.format(description=materials.get("description", ""),
                       quirks=("\nData quirks (copy names and values exactly as stored):\n" + "\n".join(f"- {q}" for q in quirks) + "\n") if quirks else "",
                       data_blocks=data_blocks(tree, plan["events"], _who(plan["task_type"]), cfg),
                       schema=materials.get("schema", ""),
                       keys="\n".join(materials.get("keys", {})[t] for t in plan["scope"] if t in materials.get("keys", {})) or "(none)",
                       type_text=TYPE_TEXT[plan["task_type"]].format(**fmt), shape_text=shape_text(anchor, tree, plan, cfg),
                       style_text=style_text(plan, cfg))
    system = SYSTEM.format(example=plan["example"], max_rows=cfg["MAX_ROWS_PER_STMT"])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
