#!/usr/bin/env python3
"""Classify every DySQL-Bench task by who is speaking and whose rows the gold SQL writes.
Summary of the result: docs/data_gen/dysql_task_types.md.

Speaker (from the self-introduction at the start of the instruction):
  db_person  a real row of a person table, matched by name, by an attached person-key ID
             ('Topazz (EntertainerID 1002)'), or by 'my email/SSN is ...'
  invented   a proper name that is not in the DB ('I am Markus Klein, an auto dealer')
  role       a role or username ('As the casting coordinator', 'Authenticate as user_007')
  none       no identity at all
Writes: each gold write runs on an in-memory copy with RETURNING * (new values) plus a BEFORE UPDATE trigger
(old values). Every touched row is traced child->parent along FKs (<= 3 hops) to person-table rows, and the
write is labelled relative to the speaker: own / other (another DB person) / person_obj (a DB person, the
speaker is not in the DB) / public (reaches no person: products, costs, playlists, recipes, cars) / noop.

Validation: three random samples checked by hand (40, 40, 30 tasks); rules were fixed after the first two,
and the last sample was 30/30 correct. Known residual errors: a proxy who names the player right after the
introduction ('I am reviewing player data for X (player_api_id ...)') counts as db_person; people linked to
an entertainer only through Entertainer_Members count as 'other'; retail customers who share a name are all
treated as the speaker.

Usage (from DySQL-Bench/):
  ~/miniconda3/envs/dysql/bin/python scripts/classify_dysql_tasks.py --out ../docs/data_gen/dysql_task_types.csv"""
import argparse, csv, glob, importlib, json, os, re, sqlite3, sys, unicodedata
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dysql_bench.db_select import profile_db, infer_fks

PERSON = {  # env -> {person table: (key column, SQL expression for the full name)}
    "bowling": {"Bowlers": ("BowlerID", "BowlerFirstName||' '||BowlerLastName")},
    "car": {}, "cookbook": {},
    "chinook": {"customers": ("CustomerId", "FirstName||' '||LastName"),
                "employees": ("EmployeeId", "FirstName||' '||LastName")},
    "entertainment": {"Agents": ("AgentID", "AgtFirstName||' '||AgtLastName"),
                      "Customers": ("CustomerID", "CustFirstName||' '||CustLastName"),
                      "Entertainers": ("EntertainerID", "EntStageName"),
                      "Members": ("MemberID", "MbrFirstName||' '||MbrLastName")},
    "eu_soccer": {"Player": ("player_api_id", "player_name")},
    "human_resources": {"employee": ("ssn", "firstname||' '||lastname")},
    "ice_hockey": {"PlayerInfo": ("ELITEID", "PlayerName")},
    "law_episode": {"Person": ("person_id", "name")},
    "music": {"Customer": ("CustomerId", "FirstName||' '||LastName"),
              "Employee": ("EmployeeId", "FirstName||' '||LastName")},
    "pagila": {"customer": ("customer_id", "first_name||' '||last_name"),
               "staff": ("staff_id", "first_name||' '||last_name"),
               "actor": ("actor_id", "first_name||' '||last_name")},
    "retail": {"customers": ("cust_id", "cust_first_name||' '||cust_last_name")},
    "retail_world": {"Customers": ("CustomerID", "ContactName"),
                     "Employees": ("EmployeeID", "FirstName||' '||LastName")},
}
CONTACT = {  # env -> [(person table, key column, contact column)] for 'my email is ...' / 'My SSN is ...'
    "chinook": [("customers", "CustomerId", "Email")], "music": [("Customer", "CustomerId", "Email")],
    "entertainment": [("Entertainers", "EntertainerID", "EntEMailAddress"), ("Entertainers", "EntertainerID", "EntSSN")],
    "pagila": [("customer", "customer_id", "email")], "retail": [("customers", "cust_id", "cust_email")],
    "human_resources": [("employee", "ssn", "ssn")],
}
EXTRA_FKS = {  # FKs the current name rule misses (1:1 extension table whose key is also its PK)
    "retail": [("supplementary_demographics", "cust_id", "customers", "cust_id")],
}
GROUPS = {  # (speaker is a DB person?, write pattern) -> task group; see docs/data_gen/dysql_task_types.md
    "1_self": "真人改自己的数据", "2_self_and_public": "真人改自己的 + 公共数据", "3_public_only": "真人只改公共数据",
    "4_other_person": "真人改别人的数据", "5_proxy": "库外说话人改人物数据", "6_entity": "库外说话人改实体数据",
    "7_no_change": "标准答案不改库",
}

INTRO = re.compile(r"(?i)\b(i am|i'm|i’m|my name is|this is|you are|you're|your name is|as|authenticate as|"
                   r"authenticate me|verify me|it's)\b[:,]?\s+")
ROLE = re.compile(r"(?i)^(the|a|an|authorized|admin|administrator|manager|hr|database|system|team|store|staff|"
                  r"agent of|representative)\b")
ACTIVITY = re.compile(r"(?i)^(updating|managing|editing|working|compiling|responsible|in charge|reviewing|handling|"
                      r"processing|here|from|with)\b")
KEYVAL = re.compile(r"(?i)\b([A-Za-z_ ]{0,14}?(?:id|ssn|number|no\.?|#))\s*[:#=]?\s*['\"]?([A-Za-z0-9][A-Za-z0-9_-]*)")
ATTACHED = re.compile(r"(?i)^\s*[(,]\s*(?:with\s+)?([A-Za-z_ ]{0,20}?(?:id|ssn|number))\s*[:#=]?\s*['\"]?([\w-]+)")
MYCONTACT = re.compile(r"(?i)\b(?:my|me using my|with)\s+(?:registered\s+|current\s+)?(?:email(?:\s+address)?|e-mail|"
                       r"ssn|social security number)\s*(?:is|:|of)?\s*['\"]?([\w.+-]+@[\w.-]+\w|\d{3}-?\d{2}-?\d{4})")
WRITE = re.compile(r"(?i)^\s*(?:insert(?:\s+or\s+\w+)?\s+into|update(?:\s+or\s+\w+)?|delete\s+from|replace\s+into)"
                   r"\s+[\"`\[]?([\w ]+?)[\"`\]]?[\s(]")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"\s+", " ", "".join(ch for ch in s if not unicodedata.combining(ch)).lower().replace("’", "'")).strip()


def split_sql(sql):
    out, buf = [], ""
    for part in sql.split(";"):
        buf += part
        if sqlite3.complete_statement(buf + ";"):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
        else:
            buf += ";"
    if buf.strip():
        out.append(buf.strip())
    return out


def task_group(speaker, pattern):
    if pattern in ("noop_only", "read_only"):
        return "7_no_change"
    if speaker == "db_person":
        return {"own": "1_self", "own+public": "2_self_and_public", "public": "3_public_only"}.get(pattern, "4_other_person")
    return "5_proxy" if "person_obj" in pattern else "6_entity"


class Env:
    """One DySQL environment: an in-memory DB copy, its FK graph, and the name/key lookups of its person tables."""

    def __init__(self, env):
        self.env = env
        path = glob.glob(f"{ROOT}/dysql_bench/envs/{env}/data/*.sqlite")[0]
        self.p = profile_db(path)
        self.fks = defaultdict(list)  # child table -> [(col, parent, parent col)]
        for t in self.p["tables"]:
            for f in t["fks"]:
                if len(f["cols"]) == 1:
                    ref = next((x["name"] for x in self.p["tables"] if x["name"].lower() == f["ref_table"].lower()), None)
                    if ref:
                        pc = f["ref_cols"][0] or next(x["pk"][0] for x in self.p["tables"] if x["name"] == ref)
                        self.fks[t["name"]].append((f["cols"][0], ref, pc))
        for child, col, parent, pcol in EXTRA_FKS.get(env, []):
            self.fks[child].append((col, parent, pcol))
        for f in infer_fks(self.p):
            e = (f["cols"][0], f["ref_table"], f["ref_cols"][0])
            if e not in self.fks[f["table"]]:
                self.fks[f["table"]].append(e)
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        src.backup(self.db)
        src.close()
        self.persons = PERSON[env]
        self.lower = {t.lower(): t for t in self.persons}
        self.db.execute("CREATE TEMP TABLE _old (tbl TEXT, j TEXT)")
        for t in self.p["tables"]:  # capture pre-update FK/key values: 'transfer my engagement to agent 4' is still 'own'
            need = {c for c, _, _ in self.fks.get(t["name"], [])}
            if t["name"] in self.persons:
                need.add(self.persons[t["name"]][0])
            need &= set(t["cols"])
            if need:
                obj = ", ".join(f"'{c}', OLD.\"{c}\"" for c in sorted(need))
                self.db.execute(f'CREATE TEMP TRIGGER "_u_{t["name"]}" BEFORE UPDATE ON main."{t["name"]}" BEGIN '
                                f"INSERT INTO _old VALUES ('{t['name']}', json_object({obj})); END")
        self.names, self.keys = {}, defaultdict(set)  # normalized full name / str(key) -> {(table, key)}
        for t, (k, expr) in self.persons.items():
            for kv, nm in self.db.execute(f'SELECT "{k}", {expr} FROM "{t}"'):
                if nm:
                    self.names.setdefault(norm(nm), set()).add((t, str(kv)))
                self.keys[str(kv)].add((t, str(kv)))
        self.maxlen = max((len(n.split()) for n in self.names), default=0)

    def trace(self, table, row, depth=0, acc=None):
        """Person rows (table, key) that `row` of `table` belongs to, following FKs child->parent."""
        acc = set() if acc is None else acc
        tl = self.lower.get(table.lower())
        if tl:
            k = self.persons[tl][0]
            v = row.get(k, row.get(k.lower()))
            if v is not None:
                acc.add((tl, str(v)))
        if depth >= 3:
            return acc
        for col, parent, pcol in self.fks.get(table, []):
            v = row.get(col)
            if v is None or v == "":
                continue
            try:
                cur = self.db.execute(f'SELECT * FROM "{parent}" WHERE "{pcol}" = ? LIMIT 3', (v,))
            except sqlite3.Error:
                continue
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                self.trace(parent, dict(zip(cols, r)), depth + 1, acc)
        return acc

    def speaker(self, ins):
        """(speaker type, introduced phrase, {(person table, key)}, how the person was identified)."""
        m = INTRO.search(ins[:260]) or re.search(r"(?i)\b(authenticate me|verify me)\b", ins[:260])
        if not m:
            return "none", "", set(), set()
        tail = re.sub(r"\b([A-Z])\.", r"\1", ins[m.end():m.end() + 120])  # 'John A. Kennedy' -> 'John A Kennedy'
        who = re.split(r"[,.;:!?()\n]| and | with | who | from | at ", tail)[0].strip()
        sids, by = set(), set()
        toks = norm(tail).split()
        for n in range(min(self.maxlen, 6), 0, -1):  # a DB name that starts the introduced phrase
            cand = " ".join(toks[:n]).strip(" ,.;:()'\"")
            if cand in self.names:
                sids |= self.names[cand]; by.add("name")
                break
        att = ATTACHED.match(tail[len(who):len(who) + 50])  # 'Topazz (EntertainerID 1002)', 'X, EntertainerID 1011'
        span = who + (att.group(0) if att else "")
        for km in ([] if ROLE.match(who) else KEYVAL.finditer(span)):  # a role phrase takes no IDs
            kw, val = norm(km.group(1)), km.group(2)
            for tb, kv in self.keys.get(val, ()):
                kname = norm(self.persons[tb][0]).replace("_", "")
                if kname in kw.replace(" ", "").replace("_", "") or norm(tb).rstrip("s") in kw.replace(" ", ""):
                    sids.add((tb, kv)); by.add("id")
        if not sids:  # a DB name inside the phrase ('the entertainer 'Topazz'', 'Ann K Patterson'), not after 'for/of'
            wt = [x for x in norm(re.sub(r"['\"]", " ", who)).split() if len(x) > 1 or not x.isalpha()]
            for n in range(min(self.maxlen, 6), 0, -1):
                for s0 in range(0, max(0, len(wt) - n) + 1):
                    cand = " ".join(wt[s0:s0 + n])
                    if cand in self.names and not re.search(r"\b(for|of|representing|behalf)\b", " ".join(wt[:s0])):
                        sids |= self.names[cand]; by.add("name")
                if sids:
                    break
        for mm in MYCONTACT.finditer(ins):  # 'my email is x@y' / 'My SSN is 123-45-6789'
            val = mm.group(1).strip(".")
            for tb, k, col in CONTACT.get(self.env, []):
                q = f"SELECT \"{k}\" FROM \"{tb}\" WHERE lower(replace(\"{col}\", '-', '')) = lower(replace(?, '-', ''))"
                for (kv,) in self.db.execute(q, (val,)):
                    sids.add((tb, str(kv))); by.add("contact")
        if sids:
            return "db_person", who, sids, by
        if ROLE.match(who) or ACTIVITY.match(who):
            return "role", who, sids, by
        if re.match(r"^[A-Z][\w'’.-]+(\s+[A-Z][\w'’.-]+){0,3}$", who):
            return "invented", who, sids, by
        return "role", who, sids, by

    def classify(self, idx, task):
        stype, who, sids, by = self.speaker(task.instruction)
        self.db.execute("BEGIN")
        labels, nrows, errs, detail = [], [], 0, []
        for a in task.actions:
            for st in split_sql(a.kwargs.get("sql", "")):
                try:
                    if not re.match(r"(?i)^\s*(insert|update|delete|replace)\b", st):
                        self.db.execute(st).fetchall()
                        continue
                    cur = self.db.execute(st.rstrip("; \n") + " RETURNING *")
                    cols = [d[0] for d in cur.description]
                    rs = cur.fetchall()
                except sqlite3.Error:
                    errs += 1; labels.append("error")
                    continue
                m = WRITE.match(st + " ")
                tbl = m.group(1).strip() if m else "?"
                tbl = next((x["name"] for x in self.p["tables"] if x["name"].lower() == tbl.lower()), tbl)
                owners = set()
                for r in rs[:50]:
                    owners |= self.trace(tbl, dict(zip(cols, r)))
                for (j,) in self.db.execute("SELECT j FROM _old WHERE tbl = ? LIMIT 50", (tbl,)).fetchall():
                    owners |= self.trace(tbl, json.loads(j))
                self.db.execute("DELETE FROM _old")
                nrows.append(len(rs))
                if not rs:
                    lab = "noop"
                elif stype == "db_person":
                    lab = "own" if owners & sids else ("other" if owners else "public")
                else:
                    lab = "person_obj" if owners else "public"
                labels.append(lab)
                detail.append(f"{st.split()[0].upper()} {tbl}:{lab}:{len(rs)}")
        self.db.execute("ROLLBACK")
        core = sorted({x for x in labels if x not in ("noop", "error")})
        pattern = "+".join(core) or ("noop_only" if labels else "read_only")
        return {"env": self.env, "idx": idx, "group": task_group(stype, pattern), "speaker": stype,
                "speaker_by": "+".join(sorted(by)), "pattern": pattern, "who": who[:40],
                "speaker_ids": ";".join(f"{a}:{b}" for a, b in sorted(sids))[:60],
                "n_writes": len(labels), "noop_writes": labels.count("noop"), "errors": errs,
                "bulk": int(any(n > 10 for n in nrows)), "writes": " | ".join(detail)[:300],
                "instruction": task.instruction[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    for env in sorted(os.listdir(f"{ROOT}/dysql_bench/envs")):
        if not os.path.exists(f"{ROOT}/dysql_bench/envs/{env}/tasks_test.py"):
            continue
        e = Env(env)
        tasks = importlib.import_module(f"dysql_bench.envs.{env}.tasks_test").TASKS_TEST
        rows += [e.classify(i, t) for i, t in enumerate(tasks)]
        print("done", env, file=sys.stderr)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    print(f"{n} tasks")
    for k, v in Counter(r["speaker"] for r in rows).most_common():
        print(f"  speaker {k:10s} {v:4d} {v / n:6.1%}")
    g = Counter(r["group"] for r in rows)
    for k in GROUPS:
        print(f"  {k:18s} {GROUPS[k]:14s} {g[k]:4d} {g[k] / n:6.1%}")


if __name__ == "__main__":
    main()
