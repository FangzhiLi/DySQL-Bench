# taskgen/v2/taskgen_v2/calibrate.py
"""The verifier's calibration (design §4.6, D5). Three sets, each item a candidate-shaped record with a "db" key that
says which database it runs on ("dysql:<env>" for DySQL-Bench's own, a db key such as "bird:beer_factory" otherwise):
- positives: DySQL gold that passes the v2 check (good tasks; DySQL was filtered with DeepSeek-R1, so this pass rate
  is an upper bound, design D5);
- negatives: good tasks broken by corrupt.py that still pass the check and end in another state (bad tasks only the
  verifier can catch), from DySQL gold and from v2 candidates;
- labeled: v2 candidates that passed the check, labeled good or bad by hand (labels.jsonl).
Every item gets three votes; RULES turn them into verdicts, so one run compares one, two and three votes."""
import glob, os, random, sqlite3
from collections import Counter, defaultdict
from taskgen_v2 import check, corrupt, db_profile, dysql, io, schema

RULES = {"1 vote": 1, "2 votes, both Yes": 2, "3 votes, 2 Yes": 3}
REASONS = ("missing", "extra", "unclear", "wrong_rows", "other")   # design §4.6: SQL misses / adds / instruction unclear / wrong rows / other


class Databases:
    """db key -> what checking and verifying an item needs: the db record, its file, its profile (None for DySQL),
    the DDL and the data notes for the verifier. Built once per database."""

    def __init__(self, recs=None, profiles=None):
        self.recs, self.profiles, self.cache = recs, profiles, {}

    def get(self, key):
        if key not in self.cache:
            if key.startswith("dysql:"):
                rec = dysql.db_rec(key.split(":", 1)[1])
                path, prof = rec["path"], None
            else:
                self.recs = self.recs or io.load_db_recs()
                self.profiles = self.profiles or db_profile.load()
                rec, prof = self.recs[key], self.profiles[key]
                path = io.resolve_db_path(rec["path"])
            self.cache[key] = {"rec": rec, "path": path, "profile": prof, "ddl": schema.ddl(path),
                               "notes": list(prof["quirks"]) if prof else []}
        return self.cache[key]

    def check(self, item):
        d = self.get(item["db"])
        return check.run_check_safe(d["rec"], item, profile=d["profile"])

    def context(self, item):
        d = self.get(item["db"])
        return d["ddl"], d["notes"]


def positives(envs=None):
    """DySQL gold that changes the database and passes the v2 check, as items."""
    out = []
    for env in envs or dysql.ENVS:
        rec = dysql.db_rec(env)
        for c in dysql.candidates(env):
            if c["group"] != "7_no_change" and check.run_check(rec, c)["ok"]:
                out.append({**c, "db": f"dysql:{env}", "set": "positives"})
    return out


def v2_items(roots):
    """The v2 candidates under roots (results/<run>/<db>/) that passed the check, as items keyed by db key (the id
    is <db key>:<root table>:<key value>:<n>)."""
    out = []
    for d in sorted(p for root in roots for p in glob.glob(os.path.join(root, "*")) if os.path.isdir(p)):
        ok = {r["id"] for r in io.read_jsonl(os.path.join(d, "check.jsonl")) if r["ok"]}
        out += [{**c, "db": c["id"].rsplit(":", 3)[0], "set": "labeled"}
                for c in io.read_jsonl(os.path.join(d, "candidates.jsonl")) if c["id"] in ok]
    return out


def negatives(items, dbs, per_kind, rng, source, tries=3):
    """Up to per_kind broken copies of the items for every corruption kind, spread over databases (round robin over
    each database's shuffled items). A copy is kept only when it still passes the check and ends in another state;
    an item gets `tries` draws per kind to find one."""
    by_db = defaultdict(list)
    for it in items:
        by_db[it["db"]].append(it)
    for v in by_db.values():
        rng.shuffle(v)
    order = [it for row in _round_robin(sorted(by_db), by_db) for it in row]
    out, conns = [], {}
    for kind in corrupt.KINDS:
        n = 0
        for it in order:
            if n >= per_kind:
                break
            d = dbs.get(it["db"])
            conn = conns.setdefault(it["db"], sqlite3.connect(f"file:{d['path']}?mode=ro", uri=True))
            gold = None
            for t in range(tries):
                bad = corrupt.corrupt(it, kind, random.Random(f"{it['id']}:{kind}:{t}"), conn)
                if bad is None:
                    break   # the SQL has no place for this kind
                gold = gold or check.final_state(d["path"], corrupt.statements(it))
                after = check.final_state(d["path"], corrupt.statements(bad))
                neg = {**bad, "id": f"{it['id']}#{kind}", "set": "negatives", "kind": kind, "source": source, "of": it["id"]}
                if after is not None and after != gold and dbs.check(neg)["ok"]:
                    out.append(neg); n += 1
                    break
    return out


def _round_robin(keys, groups):
    rows, i = [], 0
    while any(i < len(groups[k]) for k in keys):
        rows.append([groups[k][i] for k in keys if i < len(groups[k])])
        i += 1
    return rows


def verdict(rec, k):
    """'pass' / 'fail' under the k-vote rule (the first k real votes; Yes must outnumber No), None while fewer than
    k votes exist (a vote cut off while thinking is retried, not counted)."""
    votes = [v for v in (rec or {}).get("votes", []) if "error" not in v][:k]
    if len(votes) < k:
        return None
    yes = sum(v["verdict"] == "yes" for v in votes)
    return "pass" if yes > len(votes) - yes else "fail"


def _rate(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs), sum(xs), len(xs)) if xs else (None, 0, 0)


def metrics(items, votes, labels):
    """Per rule: positives' pass rate; negatives' rejection rate per (source, kind) and in all; on the labeled set the
    good tasks' pass rate and the bad tasks' rejection rate (recall) and the rejected tasks' share of bad (precision)."""
    out = {}
    for rule, k in RULES.items():
        v = {i["id"]: verdict(votes.get(i["id"]), k) for i in items}
        pos = [i for i in items if i["set"] == "positives"]
        neg = [i for i in items if i["set"] == "negatives"]
        lab = [i for i in items if i["set"] == "labeled" and i["id"] in labels]
        m = {"positives_pass": _rate([None if v[i["id"]] is None else v[i["id"]] == "pass" for i in pos]),
             "negatives_reject": _rate([None if v[i["id"]] is None else v[i["id"]] == "fail" for i in neg]),
             "negatives_by_kind": {}}
        for key in sorted({(i["source"], i["kind"]) for i in neg}):
            m["negatives_by_kind"][key] = _rate([None if v[i["id"]] is None else v[i["id"]] == "fail"
                                                 for i in neg if (i["source"], i["kind"]) == key])
        good = [i for i in lab if labels[i["id"]]["label"] == "good"]
        bad = [i for i in lab if labels[i["id"]]["label"] == "bad"]
        m["labeled_good_pass"] = _rate([None if v[i["id"]] is None else v[i["id"]] == "pass" for i in good])
        m["labeled_bad_reject"] = _rate([None if v[i["id"]] is None else v[i["id"]] == "fail" for i in bad])
        m["labeled_precision"] = _rate([labels[i["id"]]["label"] == "bad" for i in lab if v[i["id"]] == "fail"])
        out[rule] = m
    return out


def choose_rule(m, floor=0.95):
    """The rule to run with (design §3): of the rules whose positives and labeled good tasks both pass at >= floor,
    the one that rejects the most negatives; fewer votes on a tie. None when no rule keeps the good tasks."""
    ok = [r for r in RULES if (m[r]["positives_pass"][0] or 0) >= floor and (m[r]["labeled_good_pass"][0] or 0) >= floor]
    if not ok:
        return None
    return max(ok, key=lambda r: (m[r]["negatives_reject"][0] or 0, -RULES[r]))


def final_labels(rows):
    """labels.jsonl rows -> {id: row}; a later row for the same id (the user's review) replaces an earlier one."""
    out = {}
    for r in rows:
        out[r["id"]] = r
    return out


def disagreements(items, votes, labels, k=3):
    """Labeled items to show the user: Claude unsure, or Claude's label against the k-vote verdict."""
    out = []
    for i in items:
        lab, v = labels.get(i["id"]), verdict(votes.get(i["id"]), k)
        if lab and (lab.get("unsure") or (v is not None and (lab["label"] == "good") != (v == "pass"))):
            out.append(i)
    return out


def counts(items):
    c = Counter(i["set"] for i in items)
    c.update(f"negatives:{i['source']}:{i['kind']}" for i in items if i["set"] == "negatives")
    return dict(c)
