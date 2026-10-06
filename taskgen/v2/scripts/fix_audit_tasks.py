#!/usr/bin/env python3
"""Fix the tasks the 2026-10-06 audit found bad (docs/2026-10-06-task-audit.md, results/audit/drop_candidates.json,
A and B), one database at a time (2026-10-07, user's decision: fix what can be fixed, drop the rest). Each fix is a new
candidate <tree>:<next index> carrying "fix": {"from", "kind"}; it goes through check and verify like any other, and
the original goes to excluded.jsonl. Kinds:
- reorder: the instruction names the rows to copy in the order the table holds them, so the copies' new ids are the
  same whichever way an agent copies (GLM rewrite, SQL unchanged);
- substitute: values replaced in the SQL and the instruction (unused ticket numbers; an instructor or a movie that
  exists);
- rewrite: the SQL edited here, the instruction rewritten by GLM to match it and to fix the note;
- regenerate: the tree generated again (a lookup value the database already holds; a copy-then-delete repair; an
  advisee who does not exist).
After check and verify, --validate audits the fixes and excludes those that still carry a dropped flag.
Usage (from taskgen/v2/):
  P=~/miniconda3/envs/dysql/bin/python
  $P scripts/fix_audit_tasks.py --plan                 # results/audit/fix_plan.json, every database
  $P scripts/fix_audit_tasks.py --plan-c               # adds the 11 IPL tasks (C, 2026-10-07)
  $P scripts/fix_audit_tasks.py --db bird:movie        # new candidates, originals excluded
  $P scripts/taskgen.py check --db bird:movie          # then verify (x3), then:
  $P scripts/fix_audit_tasks.py --db bird:movie --validate"""
import argparse, json, os, random, re, sqlite3, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [V2, os.path.join(os.path.dirname(V2), "common")]
from taskgen_v2 import audit, check, db_profile, fixes, generate, io, llm, repair

AUDIT = os.path.join(io.RESULTS, "audit")
PLAN = os.path.join(AUDIT, "fix_plan.json")
DROPPED = {"copy_order", "key_collision", "duplicate_name", "dangling_fk"}   # flags a fix may not carry
BY = "audit 2026-10-06"

# fixes chosen by reading the tasks and the data (2026-10-07)
SUBSTITUTE = {
    "spider1:college_2:student:55698:0": {"10101": "6569"},     # Mingoz, Finance: the student's department
    "spider1:college_2:student:50977:0": {"15151": "34175"},    # Bondi, Comp. Sci.: the department he moves to
    "spider1:college_2:student:30845:0": {"73612": "28400"},    # Statistics: no instructor is in Math
    "bird:movie:actor:1321:0": {"742": "235"},                  # How the Grinch Stole Christmas (2000), no credit of his
}
REWRITE = {
    "spider2:school_scheduling:Staff:98062:0": {
        "sql": {"""INSERT INTO "Categories" ("CategoryID", "CategoryDescription") VALUES ('CMP', 'Computer Applications')""":
                """INSERT INTO "Categories" ("CategoryID", "CategoryDescription", "DepartmentID") VALUES ('CMP', 'Computer Applications', 5)"""},
        "note": "A category belongs to a department, and the request gives none (the row got DepartmentID 0, which does "
                "not exist). The SQL now puts CMP in department 5, Information Technology, where CIS and CSC are. Say "
                "that the new category belongs to the Information Technology department (DepartmentID 5)."},
    "bird:menu:Menu:34397:0": {
        "note": "The SQL copies only page 73186's own row in MenuPage, not the dishes (MenuItem rows) on that page, and "
                "'a duplicate of page 73186 exactly as catalogued' reads as if the dishes came along. Say plainly that "
                "only the page record itself is to be duplicated, without the dishes listed on it."},
    "bird:synthea:patients:321014c4-4685-4606-b677-3073df130bfa:0": {
        "note": "Only one of this patient's observations has no value recorded: 'Sudden Cardiac Death' (code 95281009, "
                "dated 1939-09-29). The request says two. Make it ask for that one observation, naming it, to get code "
                "'410429000'."},
    "bird:college_completion:institution_details:240453:0": {
        "sql": {"""INSERT INTO "institution_grads" (unitid, year, gender, race, cohort, grad_cohort, grad_100, grad_150, grad_100_rate, grad_150_rate) VALUES (240453, 2011, 'B', 'X', '4y bach', '3974', '501', '1582', '12.6', '39.8')""":
                """UPDATE "institution_grads" SET grad_cohort = '3974', grad_100 = '501', grad_150 = '1582', grad_100_rate = '12.6', grad_150_rate = '39.8' WHERE unitid = 240453 AND year = 2011 AND gender = 'B' AND race = 'X' AND cohort = '4y bach'"""},
        "note": "A 2011 '4y bach' row for gender B, race X already exists (grad_cohort 4218, grad_100 604, grad_150 1704, "
                "grad_100_rate 14.3, grad_150_rate 40.4), so inserting another would duplicate it. The SQL now corrects "
                "that existing row. Ask to correct the existing 2011 row's figures to the new ones, not to insert a row."},
}
SCREENTIME = ["bird:movie:actor:913:0", "bird:movie:actor:1616:0", "bird:movie:actor:407:0", "bird:movie:actor:2503:0",
              "bird:movie:actor:1274:0"]   # 'N minutes' unquoted in the instruction; the column holds H:MM:SS
REGENERATE_EXTRA = ["spider1:college_2:instructor:3199:0"]   # the new advisees do not exist, and every student has an advisor

# C (2026-10-07, user's decision): IPL tasks whose "correction" makes a ball's batting team its bowling team, or a
# match's two teams one team; the stored values were right. With other requests the change is dropped from the SQL
# and the text; alone, the tree is generated again.
_IPL_NOTE = ("The request also asks to change {what}. The stored value is right: the new one would make {why}. The SQL "
             "no longer makes that change. Remove that request from the text and keep everything else as it is.")
IPL_DROP = {
    "spider2:IPL:player:370:1": ("SET team_batting = 13", "team_batting on ball 1 of over 15, innings 2 of match 980950",
                                 "the batting team the same as the bowling team (13)"),
    "spider2:IPL:player:397:0": ('SET "team_bowling" = 1', "team_bowling on ball 6 of over 15, innings 1 of match 829718",
                                 "the bowling team the same as the batting team (1)"),
    "spider2:IPL:player:151:0": ("SET team_batting = 8", "team_batting on ball 5 of over 18, innings 2 of match 419115",
                                 "the batting team the same as the bowling team (8)"),
    "spider2:IPL:player:381:0": ("SET team_bowling = 6", "team_bowling on ball 3 of over 10, innings 1 of match 734024",
                                 "the bowling team the same as the batting team (6)"),
    "spider2:IPL:player:315:0": ("SET team_1 = 7", "team_1 of match 733976",
                                 "a match whose toss winner, winner and 206 balls belong to team 3, which would no longer play in it"),
}
IPL_REGENERATE = ["spider2:IPL:player:374:0", "spider2:IPL:player:323:0", "spider2:IPL:player:339:0",
                  "spider2:IPL:player:182:0", "spider2:IPL:player:52:0", "spider2:IPL:player:296:0"]
INVARIANTS = {"spider2:IPL": [("ball_by_ball", "team_batting", "team_bowling"), ("match", "team_1", "team_2")]}   # never equal


def build_plan():
    d = json.load(open(os.path.join(AUDIT, "drop_candidates.json")))
    flags = {r["id"]: r["flags"] for r in io.read_jsonl(os.path.join(AUDIT, "flags.jsonl")) if r["src"] == "v2"}
    cands = {}
    for m in json.load(open(os.path.join(V2, "output", "manifest.json"))).values():
        for t in io.read_jsonl(os.path.join(V2, "output", m["tasks"])):
            cands[t["meta"]["id"]] = t
    plan = {}
    for i in d["A_scripted"]["copy_order"]:
        f = next(f for f in flags[i] if f["k"] == "copy_order")
        order = f["keys_in_table_order"]
        listed = fixes.listed_order(cands[i]["instruction"], order)
        plan[i] = {"kind": "reorder", "class": "copy_order", "note":
                   f"The request names the rows to copy in the order {', '.join(listed)}, but one INSERT ... SELECT gives "
                   f"the copies their new ids in the order the table holds the rows: {', '.join(order)}. An agent copying "
                   f"them one by one in the request's order would give them other ids. Name the rows to copy in exactly "
                   f"this order: {', '.join(order)}. Keep every detail attached to the same row id."}
    top = int(sqlite3.connect(f"file:{_db_path('spider2:Airlines')}?mode=ro", uri=True)
              .execute("SELECT MAX(ticket_no) FROM tickets").fetchone()[0])
    for i in d["A_scripted"]["key_collision"]:
        vals = sorted({f["value"] for f in flags[i] if f["k"] == "key_collision"})
        mapping = {}
        for v in vals:
            top += 1
            mapping[v] = f"{top:013d}"
        plan[i] = {"kind": "substitute", "class": "key_collision", "map": mapping}
    for i, mapping in SUBSTITUTE.items():
        plan[i] = {"kind": "substitute", "class": "dangling_fk", "map": mapping}
    for i, spec in REWRITE.items():
        plan[i] = {"kind": "rewrite", "class": "read", **spec}
    for i in SCREENTIME:
        sql = " ".join(a["kwargs"]["sql"] for a in cands[i]["actions"])
        mapping = {f"'{n} minutes'": f"'0:{int(n):02d}:00'" for n in re.findall(r"'(\d+) minutes'", sql)}
        plan[i] = {"kind": "rewrite", "class": "format", "sql": mapping, "note":
                   "The screentime column stores times as H:MM:SS ('0:32:30'), so 'N minutes' leaves the exact text to "
                   f"guess. The SQL now writes {', '.join(mapping.values())}; give that exact value in the request."}
    for i in [x for x in d["A_scripted"]["duplicate_name"] if x not in plan] + d["B_read"]["archive_cascade_copy_without_children"] + REGENERATE_EXTRA:
        plan.setdefault(i, {"kind": "regenerate", "class": "regenerate"})
    missing = [i for i in d["drop_AB"] if i not in plan]
    if missing:
        sys.exit(f"no fix planned for {missing}")
    json.dump(plan, open(PLAN, "w"), indent=1)
    c = {}
    for v in plan.values():
        c[v["kind"]] = c.get(v["kind"], 0) + 1
    print(f"{len(plan)} fixes planned: {c}")


def add_c_plan():
    plan = json.load(open(PLAN))
    for i, (key, what, why) in IPL_DROP.items():
        plan[i] = {"kind": "rewrite", "class": "ipl_impossible", "sql": {key: None}, "note": _IPL_NOTE.format(what=what, why=why)}
    for i in IPL_REGENERATE:
        plan[i] = {"kind": "regenerate", "class": "ipl_impossible"}
    json.dump(plan, open(PLAN, "w"), indent=1)
    print(f"{len(IPL_DROP) + len(IPL_REGENERATE)} IPL fixes added; {len(plan)} in the plan")


def _db_path(db_key):
    return io.resolve_db_path(io.load_db_recs(io.ANCHORS_JSON)[db_key]["path"])


def stmts_of(cand):
    return [s for x in cand["actions"] for s in check.split_statements(x["sql"])]


def edit_sql(stmts, mapping):
    """Each mapping: a whole statement or a quoted value replaced as text, a bare value as a whole token; None drops
    every statement containing the key."""
    drop = [k for k, v in mapping.items() if v is None]
    mapping = {k: v for k, v in mapping.items() if v is not None}
    out = []
    for s in stmts:
        if any(k in s for k in drop):
            continue
        for old, new in mapping.items():
            s = s.replace(old, new) if old.startswith(("INSERT", "UPDATE", "DELETE")) or "'" in old else fixes.substitute(s, {old: new})
        out.append(s)
    return out


def apply(db_key, workers, seed):
    rec = io.load_db_recs(io.ANCHORS_JSON)[db_key]
    prof = db_profile.get(db_key)
    out = os.path.join(io.RESULTS, rec["db"])
    plan = {i: p for i, p in json.load(open(PLAN)).items() if i.startswith(db_key + ":")}
    done = {r["from"] for r in io.read_jsonl(f"{out}/fixes.jsonl")}
    plan = {i: p for i, p in plan.items() if i not in done}
    if not plan:
        print(f"{db_key}: nothing to fix"); return
    cands = {c["id"]: c for c in io.read_jsonl(f"{out}/candidates.jsonl")}
    ids = list(cands)
    materials = generate.context(rec, prof)
    client = llm.client_from_env("GEN")
    new, logs, gen_jobs = [], [], []
    for i, p in plan.items():
        c = cands[i]
        if p["kind"] == "substitute":
            sql = edit_sql(stmts_of(c), p["map"])
            ins = fixes.substitute(c["instruction"], p["map"])
            if any(old in c["instruction"] and new not in ins for old, new in p["map"].items()) or ins == c["instruction"]:
                sys.exit(f"{i}: the instruction does not name {list(p['map'])}")
            nid = fixes.next_id(i, ids); ids.append(nid)
            new.append({**c, "id": nid, "instruction": ins, "actions": [{"sql": s} for s in sql],
                        "fix": {"from": i, "kind": "substitute"}})
            logs.append({"id": nid, "from": i, "kind": "substitute", "class": p["class"]})
        elif p["kind"] in ("reorder", "rewrite"):
            sql = edit_sql(stmts_of(c), p.get("sql") or {})
            if p.get("sql") and sql == stmts_of(c):
                sys.exit(f"{i}: the SQL edit did not apply")
            nid = fixes.next_id(i, ids); ids.append(nid)
            gen_jobs.append((i, nid, sql, p))
    def one(job):
        i, nid, sql, p = job
        try:
            resp = client.chat(fixes.messages(cands[i], sql, p["note"], materials), temperature=generate.GEN_TEMPERATURE,
                               max_tokens=generate.GEN_MAX_TOKENS, top_p=generate.GEN_TOP_P)
            return job, resp, repair.parse_rewrite(resp.get("content")), None
        except Exception as e:
            return job, None, None, f"{type(e).__name__}: {e}"
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for f in as_completed([ex.submit(one, j) for j in gen_jobs]):
            (i, nid, sql, p), resp, ins, err = f.result()
            if err:
                print(f"{i}: rewrite failed ({err[:120]}); the original stays excluded"); continue
            new.append({**cands[i], "id": nid, "instruction": ins, "actions": [{"sql": s} for s in sql],
                        "fix": {"from": i, "kind": p["kind"]}, "gen_model": resp.get("model"), "usage": resp.get("usage"),
                        "raw": resp.get("content"), "error": None})
            logs.append({"id": nid, "from": i, "kind": p["kind"], "class": p["class"]})
    regen = [i for i, p in plan.items() if p["kind"] == "regenerate"]
    if regen:   # every candidate of these trees goes into the scratch file, so generate.run writes the next index
        trees = {(t["anchor_table"], str(t["key_value"])): t for t in io.read_jsonl(f"{out}/trees.jsonl")}
        tmp = f"{out}/_fix_regenerate.jsonl"
        if os.path.exists(tmp):
            os.remove(tmp)
        tree_ids = {fixes.tree_of(i) for i in regen}
        io.append_jsonl(tmp, [c for c in cands.values() if fixes.tree_of(c["id"]) in tree_ids])
        nxt = {i: int(fixes.next_id(i, ids).rsplit(":", 1)[1]) for i in regen}
        for r in prof["roots"]:
            for n in sorted({nxt[i] for i in regen if cands[i]["anchor_table"] == r["table"]}):
                # per_tree counts from index 0 for every tree of the call, so trees go in groups of one next index
                mine = [i for i in regen if cands[i]["anchor_table"] == r["table"] and nxt[i] == n]
                ts = [trees[(cands[i]["anchor_table"], str(cands[i]["key_value"]))] for i in mine]
                generate.run(rec, db_profile.root_anchor(prof, r["table"]), ts, client, tmp,
                             random.Random(f"{seed}:fix:{r['table']}:{n}"), workers=workers, per_tree=n + 1, materials=materials)
        old = set(cands)
        for c in io.read_jsonl(tmp):
            if c["id"] in old:
                continue
            src = next(i for i in regen if fixes.tree_of(i) == fixes.tree_of(c["id"]))
            new.append({**c, "fix": {"from": src, "kind": "regenerate"}})
            logs.append({"id": c["id"], "from": src, "kind": "regenerate", "class": plan[src]["class"]})
        os.remove(tmp)
    io.append_jsonl(f"{out}/candidates.jsonl", new)
    io.append_jsonl(f"{out}/fixes.jsonl", logs)
    excl = {r["id"] for r in io.read_jsonl(f"{out}/excluded.jsonl")}
    io.append_jsonl(f"{out}/excluded.jsonl", [{"id": i, "reason": f"{BY}: {plan[i]['class']}", "by": "claude"}
                                               for i in plan if i not in excl])
    kinds = {k: sum(1 for x in logs if x["kind"] == k) for k in ("reorder", "substitute", "rewrite", "regenerate")}
    print(f"{db_key}: {len(plan)} to fix, {len(new)} new candidates {kinds}")


def validate(db_key):
    """Fixes that passed check and verify, audited: those with a dropped flag go to excluded.jsonl."""
    rec = io.load_db_recs(io.ANCHORS_JSON)[db_key]
    out = os.path.join(io.RESULTS, rec["db"])
    logs = io.read_jsonl(f"{out}/fixes.jsonl")
    chk = {r["id"]: r for r in io.read_jsonl(f"{out}/check.jsonl")}
    ver = {r["id"]: r for r in io.read_jsonl(f"{out}/verify.jsonl")}
    excl = {r["id"] for r in io.read_jsonl(f"{out}/excluded.jsonl")}
    cands = {c["id"]: c for c in io.read_jsonl(f"{out}/candidates.jsonl")}
    path = io.resolve_db_path(rec["path"])
    a = audit.DbAudit(path)
    bad, ok = [], 0
    for r in logs:
        i = r["id"]
        if i in excl or not (chk.get(i, {}).get("ok") and ver.get(i, {}).get("pass")):
            continue
        c = cands[i]
        conn = a.conn
        row = None
        try:
            prof = db_profile.get(db_key)
            key = db_profile.root_anchor(prof, c["anchor_table"])["key"]
            row = conn.execute(f'SELECT * FROM "{c["anchor_table"]}" WHERE "{key}" = ?', (c["key_value"],)).fetchone()
        except sqlite3.Error:
            pass
        allowed = {check.norm_literal(v) for v in (row or ()) if v not in (None, "")}
        flags, _ = a.run(c["instruction"], stmts_of(c), allowed)
        kinds = sorted({f["k"] for f in flags} & DROPPED)
        for t, x, y in INVARIANTS.get(db_key, []):
            if any(tb == t and any(r.get(x) is not None and r.get(x) == r.get(y) for r in new) for _, _, tb, _, new in a.last):
                kinds.append(f"{t}.{x} = {y}")
        if kinds:
            bad.append({"id": i, "reason": f"fix failed the audit: {', '.join(kinds)}", "by": "claude"})
        else:
            ok += 1
    io.append_jsonl(f"{out}/excluded.jsonl", bad)
    print(f"{db_key}: {ok} fixes pass the audit, {len(bad)} excluded")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true"); ap.add_argument("--plan-c", action="store_true")
    ap.add_argument("--db"); ap.add_argument("--validate", action="store_true")
    ap.add_argument("--workers", type=int, default=5, help="GLM plan limit: 5 concurrent requests"); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.plan:
        build_plan()
    elif a.plan_c:
        add_c_plan()
    elif a.db and a.validate:
        validate(a.db)
    elif a.db:
        apply(a.db, a.workers, a.seed)
    else:
        ap.error("--plan or --db")


if __name__ == "__main__":
    main()
