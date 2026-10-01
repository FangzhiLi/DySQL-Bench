# taskgen/v2/taskgen_v2/prompt.py
"""Task plan sampling (type x difficulty x shape) and the generation prompt.
SYSTEM is DySQL's generation prompt (data_pipeline_shell/generate_sqlbench_multiTurn_qa.py) with one example
instruction chosen by task type; the USER message is built from the event tree (trees.py): the root row, then 3-12 of
its events with their parent rows nested, every row tagged with whose data it is."""
import json, os, random
from taskgen_v2 import trees

CFG = {
    "TYPE_MIX": {"1_self": 0.46, "2_self_and_public": 0.12, "3_public_only": 0.05, "4_other_person": 0.08, "5_proxy": 0.29},
    "DIFFICULTY_MIX": {"easy": 0.26, "medium": 0.45, "hard": 0.29},
    "FREE_TABLE_SHARE": 0.30,
    "MAX_ROWS_PER_STMT": 50,
    "EVENTS_SHOWN": {"easy": (3, 5), "medium": (5, 8), "hard": (8, 12)},   # design §4.2: 3-12 events, more when harder
    "DATA_CHARS": 16000,      # data blocks longer than this lose events from the end (about 4k tokens)
    "MAX_VALUE_CHARS": 200,   # longer text values are cut in the prompt
}
# style pools: the pilot reused the same invented names ("Priya Raghavan" x6), roles ("records coordinator") and
# openers ("Hi, this is ..."), so the plan now hands the model a sampled name, role and opening manner
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
OPENERS = ["terse and businesslike, no greeting, straight to the change",
           "friendly, gives a short reason for the change before asking",
           "formal, like an internal email or ticket",
           "slightly annoyed because this was already requested once",
           "asks a read-only question first, then requests the change",
           "casual chat message, lower-case tone is fine",
           "explains that a colleague or customer asked them to do this",
           "apologetic, corrects a mistake they made earlier",
           "lists the changes as numbered points",
           "mentions a deadline or an upcoming event as the reason"]
EXAMPLES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples.json")

SYSTEM = """Generate a NEW task instruction that mimics realistic human users and their intentions, such as with different personality and goals. The task instruction should be followed by 'actions' which is a list of the sql to be taken to solve this task and 'outputs' which is a list of the answers to specific information requests made by the user. Think step by step to come up with the action(s) and the corresponding sql(s) translating this thought that would be necessary to fulfill the user's request or solve their intentions. The new user instruction should have all the parameters for the SQL calls in Actions.

## Guidelines for generating NEW task instruction and Groundtruth Actions
1. You must generate a new user instruction according to the <Input Database>.
2. The main focus is to generate actions that can modify the underlying database.
3. For actions that do not modify the database like specific information requests, scan the provided data directly and append only the answer in 'outputs'. Do not make separate sql calls for this in 'actions'.
4. Include multiple SQL calls when the scenario requires multiple steps or modifications. Put exactly one SQL statement in each action.
5. Provide precise SQL calls with all necessary parameters for each action according to the given Dataset Schema, and ALL the parameters should be explicitly given in the new user instruction.
6. Every UPDATE or DELETE must match at least one existing row of the provided data, and no single statement may change more than {max_rows} rows.
7. Write standard SQLite. Wrap every table name in double quotes (some table names, e.g. "transaction" or "order", are SQL keywords and fail unquoted); quote column names that contain spaces or punctuation.
8. When inserting into a table listed under "Next unused primary keys", use that value as the new row's key so it does not collide with an existing row.

## Principles for generating SQL calls
- At the beginning of the conversation, you have to authenticate the user identity by locating their user.
- Once the user has been authenticated, you can provide the user with information, e.g. help the user look up order id.
- You can only help one user per conversation (but you can handle multiple requests from the same user), and must deny any requests for tasks related to any other user.
- You should not make up any information or knowledge or procedures not provided from the user, or give subjective recommendations or comments.
- You should at most make one sql call at a time, and if you take a sql call, you should not respond to the user at the same time. If you respond to the user, you should not make a sql call.
- You should transfer the user to a human agent if and only if the request cannot be handled within the scope of your actions.

## Output Format
Generate your response according to the following <Instruction Example> and <Format Example> format. Enclose the thought process within '<thought></thought>' tags, and the final structured response within '<answer></answer>' tags. The structured response should be in strict JSON format, without any additional comments or explanations.

## Instruction Example
{example_instruction}

## Format Example (only for reference)
{{
    "instruction": "...",
    "actions": [
        {{
            "sql": "..."
        }},
        {{
            "sql": "..."
        }}
    ],
    "outputs": []
}}

The new user instruction must have all the parameters for the SQL calls in Actions. Do not directly copy the instruction or the action patterns from the example. Ground the generation in the provided data."""

USER = """## Instructions
Generate a NEW task instruction that mimics realistic human users and their intentions, such as with different personality and goals. The task instruction should be followed by 'actions' which is a list of the sql to be taken to solve this task and 'outputs' which is a list of the answers to specific information requests made by the user. ALL SQL parameters in Actions MUST be explicitly given in the new user instruction.

# <Input Database>
{db_description}

{data_blocks}
{next_ids_block}
## Dataset Schema
The available Dataset schema in DDL format is as follows:
{schema}

## Task type
{type_text}

## Task shape
{shape_text}

## Style
{style_text}

> Every literal value used in the SQL (ids, names, amounts, dates, new values) must appear verbatim in the instruction, except the values that identify the person's own row ({id_fields}), which the agent can look up.
> Each UPDATE/DELETE must match at least one row shown above; no statement may change more than {max_rows} rows.
> Confirm the generated instruction has all the parameters in the SQL calls. Generate the task now."""

TYPE_TEXT = {
    "1_self": "The speaker is {name} ({key} = {kv}), a person in table {t}. They introduce themselves by name (optionally with one identifying field such as an email or the {key}). Every write must change rows that belong to this person: their own row in {t} or rows in {down} linked to it.",
    "2_self_and_public": "The speaker is {name} ({key} = {kv}), a person in table {t}. The writes must change at least one row that belongs to this person AND at least one row in a shared table ({up}) that belongs to nobody (reference data such as products, brands, locations).",
    "3_public_only": "The speaker is {name} ({key} = {kv}), a person in table {t}. They introduce themselves by name, but the writes change ONLY rows in shared tables ({up}) that belong to nobody; the person's own rows stay unchanged.",
    "4_other_person": "The speaker is {name} ({key} = {kv}), a person in table {t}. The writes change rows belonging to ANOTHER person: {other_name} ({key} = {other_kv}) or rows in {down} linked to that person. Give a plausible reason for the authority (manager, agent, guardian, colleague).",
    "5_proxy": "The speaker is NOT in the database. They introduce themselves with the name and role given under Style, then ask to change the data of {name} ({key} = {kv}) or rows in {down} linked to that person. Do not pretend to be that person.",
}


def load_examples():
    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _weighted(rng, weights):
    keys, w = zip(*weights.items())
    return rng.choices(keys, weights=w, k=1)[0]


def feasible_types(tree):
    """Types this tree can carry. Never 4_other_person (design D6); 2 and 3 need a public row to write."""
    return ["1_self"] + (["2_self_and_public", "3_public_only"] if trees.has_public(tree) else []) + ["5_proxy"]


def _shape(rng, difficulty, task_type, n_scope, has_events):
    s = {"n_writes": 1, "n_tables": 1, "ownership_subquery": False, "archive": False,
         "public_table": task_type in ("2_self_and_public", "3_public_only")}
    if difficulty == "medium":
        pick = rng.choice(["two_writes", "two_tables", "subquery"])
        if pick == "two_writes" or (pick == "two_tables" and n_scope < 2):
            s["n_writes"] = 2
        elif pick == "two_tables":
            s.update(n_writes=2, n_tables=2)
        else:
            s["ownership_subquery"] = True
    elif difficulty == "hard":
        s.update(n_writes=rng.choice([2, 3]), n_tables=2 if n_scope >= 2 else 1, ownership_subquery=True)
        if rng.random() < 0.25 and has_events:
            s["archive"] = True
    if s["public_table"] and s["n_tables"] < 2 and task_type == "2_self_and_public":
        s.update(n_writes=max(s["n_writes"], 2), n_tables=2)
    return s


def _who(task_type):
    return "the speaker's own row" if task_type != "5_proxy" else "the person the request is about"


def sample_plan(rng, tree, anchor, cfg=CFG):
    task_type = _weighted(rng, {k: v for k, v in cfg["TYPE_MIX"].items() if k in feasible_types(tree)})
    difficulty = _weighted(rng, cfg["DIFFICULTY_MIX"])
    lo, hi = cfg["EVENTS_SHOWN"][difficulty]
    refs = trees.pick_events(tree, rng, rng.randint(lo, hi), need_public=task_type in ("2_self_and_public", "3_public_only"))
    while len(refs) > 1 and len(data_blocks(tree, refs, _who(task_type), cfg)) > cfg["DATA_CHARS"]:
        refs.pop()                                           # the event a public type needs is first, so it stays
    tabs = trees.tables_by_label(tree, refs)
    shape = _shape(rng, difficulty, task_type, len(tabs["own"]) + len(tabs["public"]), bool(refs))
    pool = tabs["public"] if task_type == "3_public_only" else tabs["own"]
    free = rng.random() < cfg["FREE_TABLE_SHARE"]
    write_tables = None
    if not free:
        k = min(shape["n_tables"], len(pool)) if task_type != "2_self_and_public" else min(shape["n_tables"] - 1, len(pool))
        write_tables = rng.sample(pool, max(1, k))
        if task_type == "2_self_and_public":
            write_tables.append(rng.choice(tabs["public"]))
    style = {"opener": rng.choice(OPENERS), "name": None, "role": None}
    if task_type == "5_proxy":
        style.update(name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", role=rng.choice(ROLES))
    return {"task_type": task_type, "difficulty": difficulty, "shape": shape, "write_tables": write_tables,
            "events": refs, "tables": tabs, "example": rng.choice(load_examples()[task_type]),
            "scope": tabs["own"] + tabs["public"], "style": style}


def _short(row, cfg):
    """Long text (WWE keeps whole HTML pages in Cards) is cut for the prompt; nobody edits it by quoting it."""
    n = cfg["MAX_VALUE_CHARS"]
    return {k: (v[:n] + f"... ({len(v)} chars)" if isinstance(v, str) and len(v) > n else v) for k, v in row.items()}


def _label_text(label):
    if label.startswith("other:"):
        return f"another person's data: {label[6:]}"
    return {"own": "own", "public": "public, shared reference data owned by nobody"}.get(label, label)


def data_blocks(tree, refs, who, cfg=CFG):
    """The root row with its attributes and parent rows, then each shown event group; parent rows are indented under
    the row that references them, and every row says whose data it is."""
    def js(row):
        return json.dumps(_short(row, cfg), ensure_ascii=False, default=str)

    def lines(node, depth):
        out = [f"{'  ' * depth}- {node['table']} ({_label_text(node['label'])}): {js(node['row'])}"]
        for p in node["parents"]:
            out += lines(p, depth + 1)
        return out
    head = [f"## {tree['anchor_table']} record ({who})", js(tree["anchor_row"])]
    head += [f"- {t} (own): {js(r)}" for t, rs in tree["attributes"].items() for r in rs]
    head += [x for p in tree["parents"] for x in lines(p, 0)]
    blocks = ["\n".join(head)]
    for g in trees.shown(tree, refs):
        blocks.append(f"## {g['label']}: {g['table']} records ({len(g['rows'])} of {g['count']} shown)\n"
                      + "\n".join(x for n in g["rows"] for x in lines(n, 0)))
    return "\n\n".join(blocks)


def shape_text(anchor, plan):
    s, lines, tabs = plan["shape"], [], plan["tables"]
    lines.append(f"- Use exactly {s['n_writes']} write statement{'s' if s['n_writes'] > 1 else ''} (INSERT/UPDATE/DELETE) touching {s['n_tables']} distinct table{'s' if s['n_tables'] > 1 else ''}.")
    if s["ownership_subquery"]:
        lines.append(f"- Locate the rows to change through their owner with a subquery on {anchor['table']} (e.g. WHERE {anchor['key']} = (SELECT {anchor['key']} FROM {anchor['table']} WHERE ...)) instead of hard-coding the {anchor['key']}.")
    if s["archive"]:
        lines.append("- First copy the affected row(s) into another table in scope with INSERT ... SELECT, then change or delete the original row(s).")
    if s["public_table"]:
        lines.append(f"- At least one write must change a shared table: {', '.join(tabs['public'])}.")
    if plan["write_tables"]:
        lines.append(f"- Write to these tables: {', '.join(plan['write_tables'])}.")
    else:
        lines.append(f"- Choose freely which tables in scope to write ({', '.join(plan['scope'])}); prefer a combination that is not the obvious one.")
    lines.append(f"- Target difficulty: {plan['difficulty']}. Read-only questions (if any) go into 'outputs', not 'actions'.")
    return "\n".join(lines)


def style_text(plan):
    st = plan.get("style") or {}
    lines = [f"- Opening manner: {st.get('opener', 'natural, varied')}."]
    if st.get("name"):
        lines.append(f"- The speaker is {st['name']}, {st['role']}. Use exactly this name and role.")
    lines.append("- Vary wording; do not open with 'Hi, this is' or 'Good morning'. Do not use phrases from the example.")
    return "\n".join(lines)


def next_ids_block(plan, next_ids):
    """next_ids: schema.next_ids() output, {table: (pk_column, next value)}; only the tables the prompt shows."""
    items = [(t, *next_ids[t]) for t in plan["scope"] if t in (next_ids or {})]
    if not items:
        return ""
    return "\n## Next unused primary keys (use these for new rows)\n" + "\n".join(f"- {t}.{c} = {v}" for t, c, v in items) + "\n"


def build_messages(db_rec, anchor, tree, plan, db_description, schema_text, cfg=CFG, next_ids=None):
    tabs = plan["tables"]
    fmt = {"name": tree["anchor_name"] or f"the row with {anchor['key']} = {tree['key_value']}", "key": anchor["key"],
           "kv": tree["key_value"], "t": anchor["table"],
           "down": ", ".join(t for t in tabs["own"] if t != anchor["table"]) or "(none)",
           "up": ", ".join(tabs["public"]) or "(none)", "other_name": "", "other_kv": ""}
    user = USER.format(db_description=db_description, data_blocks=data_blocks(tree, plan["events"], _who(plan["task_type"]), cfg),
                       schema=schema_text, next_ids_block=next_ids_block(plan, next_ids),
                       type_text=TYPE_TEXT[plan["task_type"]].format(**fmt), shape_text=shape_text(anchor, plan),
                       style_text=style_text(plan),
                       id_fields=", ".join(anchor["names"] + [anchor["key"]]), max_rows=cfg["MAX_ROWS_PER_STMT"])
    system = SYSTEM.format(example_instruction=plan["example"], max_rows=cfg["MAX_ROWS_PER_STMT"])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
