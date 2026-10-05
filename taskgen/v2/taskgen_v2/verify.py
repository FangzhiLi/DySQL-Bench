# taskgen/v2/taskgen_v2/verify.py
"""LLM verification by majority vote. DySQL's verify prompt (verify_qa_voting_request.py) judged the gold SQL as an
agent transcript against the agent policy, so a 27B verifier failed every pilot task for missing confirmation turns;
this prompt judges only whether the SQL implements the request, and whether the request is complete and solvable.
Several models may vote (design §4.6, D4): each passes a task when its Yes votes outnumber its No votes, and a task
passes when every model passes it."""
import json, os, re, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from taskgen_v2 import io, llm

VERIFY_TEMPERATURE, VERIFY_MAX_TOKENS = 1.2, 16384
DEFAULT_VOTES = 3   # majority of three, settled after two when they agree: the user's choice for the full run
                    # (plan 5); one vote was enough in plan 4's calibration
FINAL = "Verification: Is the answer correct (Yes/No)?"

SYSTEM = """You are checking a training task for a database agent. The task has two parts: the user's request (what a
customer or staff member will ask the agent for) and the ground-truth SQL statements that a correct agent must end up
executing. The SQL list is the expected final database changes, not a conversation transcript: greetings,
authentication chat, asking the user for confirmation and answering read-only questions all happen in the dialogue and
are NOT expected in the SQL list. Do not fail the task for missing conversational steps.

Check these five things.
1. [Correctness] Executed in order on the database whose schema is given, the SQL performs exactly the changes the
   request asks for: right tables, right rows, right columns, right new values. Nothing requested is missing.
2. [No extra changes] The SQL changes nothing the request did not ask for.
3. [Completeness of parameters] Every value the SQL uses (ids, names, amounts, dates, new values) is stated in the
   request, except values that identify the requester's own record (or the record the request is about), which the
   agent can look up once it knows who or what is meant.
4. [Solvability] A competent agent that can only read the request and query the database, without seeing these SQL
   statements, would arrive at the same final database state. Ambiguous requests that allow several reasonable
   end states fail this check.
5. [Validity] The SQL is valid SQLite for the given schema.

## Response format
Reason step by step, then end with: "Verification: Is the answer correct (Yes/No)?" followed by "Yes" or "No".
"""

USER = """Here is the user's request:
{user_requirements}

Here are the ground-truth SQL statements, in order:
{action_outputs}

Here is the database schema (DDL):
{ddl}
"""

NOTES = """
Notes on this database's data (true of the stored rows; the SQL may rely on them):
{notes}
"""


ENTITY_NOTE = ("This database has no table of people: the requester is not stored in it and cannot be looked up or "
               "authenticated. The request is about one {label} record, named by its ID; the requester's name, role or "
               "username is not used by the SQL.")


def notes_for(profile):
    """The data notes the verifier reads for a database: the profile's quirks, plus ENTITY_NOTE for an entity profile
    (design 2026-10-04 §3.5)."""
    notes = list(profile["quirks"])
    if profile.get("kind") == "entity":
        notes.append(ENTITY_NOTE.format(label=" or ".join(r["label"] for r in profile["roots"])))
    return notes


class Truncated(RuntimeError):
    """The model spent its tokens thinking and gave no verdict: not a vote, asked again on the next run."""


def parse_models(spec):
    """'deepseek-v4.1-flash:2,other:1' -> [('deepseek-v4.1-flash', 2), ('other', 1)]; a model without ':n' votes
    DEFAULT_VOTES times. A model name may itself contain ':' (qwen3:8b:3), so the count is the last field."""
    out = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        name, _, n = part.rpartition(":")
        out.append((name, int(n)) if name and n.isdigit() else (part, DEFAULT_VOTES))
    return out


def models_from_env(spec=None):
    """[(client, votes)] for spec, else TASKGEN_VERIFY_MODELS, else TASKGEN_VERIFY_MODEL with DEFAULT_VOTES; every
    model goes to TASKGEN_VERIFY_BASE_URL with TASKGEN_VERIFY_API_KEY."""
    io.load_dotenv()
    if not (spec or os.environ.get("TASKGEN_VERIFY_MODELS") or os.environ.get("TASKGEN_VERIFY_MODEL")):
        raise llm.LLMError("missing env TASKGEN_VERIFY_MODELS or TASKGEN_VERIFY_MODEL (see .env)")
    spec = spec or os.environ.get("TASKGEN_VERIFY_MODELS") or f"{os.environ['TASKGEN_VERIFY_MODEL']}:{DEFAULT_VOTES}"
    return [(llm.client_from_env("VERIFY", model=name), n) for name, n in parse_models(spec)]


def build_messages(cand, ddl_text, notes=()):
    user = USER.format(user_requirements=cand["instruction"],
                       action_outputs=json.dumps(cand["actions"], ensure_ascii=False, indent=1), ddl=ddl_text)
    if notes:   # the profile's data quirks: address stores congress surnames in first_name
        user += NOTES.format(notes="\n".join(f"- {n}" for n in notes))
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse_verdict(text):
    """The first Yes or No after the last 'Verification', whatever the model did to the question
    ('Verification: Is the answer correct?  Yes', '**No**'); the first, since a reason may follow ('No, not yes')."""
    text = text or ""
    if "Verification" not in text:
        return "unparsed"
    tail = text.rsplit("Verification", 1)[1].replace("(Yes/No)", "")
    words = re.findall(r"(?i)\b(yes|no)\b", tail)
    return words[0].lower() if words else "unparsed"


def _vote(client, msgs):
    r = client.chat(msgs, temperature=VERIFY_TEMPERATURE, max_tokens=VERIFY_MAX_TOKENS)
    verdict = parse_verdict(r["content"])
    if verdict == "unparsed" and (r.get("finish_reason") == "length" or not (r["content"] or "").strip()):
        raise Truncated(f"no verdict within {(r.get('usage') or {}).get('completion_tokens')} completion tokens")
    return {"verdict": verdict, "content": r["content"], "reasoning_chars": len(r.get("reasoning") or ""),
            "usage": r.get("usage")}


def _vote_safe(client, msgs):
    model = getattr(client, "model", None)
    try:
        return {**_vote(client, msgs), "model": model}
    except Exception as e:  # an API failure is not a vote: kept for the record, ignored by counts, retried on resume
        return {"verdict": "error", "error": f"{type(e).__name__}: {e}", "content": "", "reasoning_chars": 0, "usage": None,
                "model": model}


def _real(votes, model=None):
    return [v for v in votes if "error" not in v and (model is None or v.get("model") == model)]


def settled(votes, k):
    """'pass' / 'fail' for a model's real votes under its k-vote rule (the first k; Yes must outnumber No, unparsed
    counts as No) as soon as more votes cannot change it: two Yes or two No settle three votes. None until then."""
    votes = votes[:k]
    yes = sum(v["verdict"] == "yes" for v in votes)
    if yes > k / 2:
        return "pass"
    if len(votes) - yes >= k / 2:
        return "fail"
    return None


def needed(votes, k):
    """How many more votes could settle the rule now: enough for one side to reach a majority (two of three at the
    start, one after a split); 0 once settled."""
    if settled(votes, k):
        return 0
    votes = votes[:k]
    yes = sum(v["verdict"] == "yes" for v in votes)
    return k // 2 + 1 - max(yes, len(votes) - yes)


def tally(rec, models):
    """models: [(name, k)]. Per model Yes/No counts and pass (settled(), None while unsettled); the task passes when
    every model passes it. A task some model has not settled -- every call cut off or failed, or a split still
    waiting for its third vote -- is 'unvoted': not passed, not rejected either, and voted again on the next run."""
    rec["models"] = {}
    for name, k in models:
        votes = _real(rec["votes"], name)[:k]
        yes = sum(v["verdict"] == "yes" for v in votes)
        v = settled(votes, k)
        rec["models"][name] = {"yes": yes, "no": len(votes) - yes, "pass": None if v is None else v == "pass"}
    rec["pass"] = all(m["pass"] is True for m in rec["models"].values())
    rec["unvoted"] = any(m["pass"] is None for m in rec["models"].values())
    rec["verify_model"] = ",".join(name for name, _ in models)
    return rec


def run(cands, models, out_path, workers=3, context=lambda cand: ("", ()), max_failures=20):
    """models: [(client, votes)]; context(cand) -> (ddl_text, notes). Votes go out in rounds: each round asks, for
    every task and model, only the votes that could still settle it (needed()), so three votes by majority cost about
    two a task. A call that fails is not asked again in the same run. After max_failures failed calls in a row (an
    exhausted quota answers every call with an error) the run stops and returns paused=True; the same command
    resumes it. A new task's record is appended as soon as its votes of a round are in, so an interrupted run keeps
    them; records that got more votes are rewritten in place at the end."""
    names = [(getattr(c, "model", None), k) for c, k in models]
    existing = {r["id"]: r for r in io.read_jsonl(out_path)}
    in_file, dirty, voted, failed = set(existing), set(), set(), set()
    settled_before = sum(1 for c in cands if not any(
        needed(_real(existing.get(c["id"], {}).get("votes", []), getattr(cl, "model", None)), k) for cl, k in models))
    stop, lock, streak = threading.Event(), threading.Lock(), [0]

    def job(client, msgs):   # counts failures where they happen, so no call goes out after the limit
        if stop.is_set():
            return None
        v = _vote_safe(client, msgs)
        with lock:
            if "error" not in v or v["error"].startswith("Truncated"):   # cut off while thinking: the API works
                streak[0] = 0
            else:
                streak[0] += 1
                if streak[0] >= max_failures:
                    stop.set()
        return v

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        while not stop.is_set():
            jobs = [(c, client) for c in cands for client, k in models
                    if (c["id"], getattr(client, "model", None)) not in failed
                    for _ in range(needed(_real(existing.get(c["id"], {}).get("votes", []), getattr(client, "model", None)), k))]
            if not jobs:
                break
            pending = {}
            for c, _ in jobs:
                pending[c["id"]] = pending.get(c["id"], 0) + 1
            futs = {ex.submit(job, client, build_messages(c, *context(c))): c["id"] for c, client in jobs}
            new = {}
            for f in as_completed(futs):
                cid, v = futs[f], f.result()
                pending[cid] -= 1
                if v is not None:   # None: not asked, the run is pausing
                    new.setdefault(cid, []).append(v)
                    if "error" in v:
                        failed.add((cid, v.get("model")))
                if pending[cid] == 0 and cid in new:
                    _keep(existing, in_file, dirty, out_path, cid, new.pop(cid), names); voted.add(cid)
            for cid, votes in new.items():   # cut short by a pause: keep what came back
                _keep(existing, in_file, dirty, out_path, cid, votes, names); voted.add(cid)
    if dirty:  # rewrite the file with the records that got more votes, in place
        rows = [existing[r["id"]] if r["id"] in dirty else r for r in io.read_jsonl(out_path)]
        tmp = out_path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        io.append_jsonl(tmp, rows)
        os.replace(tmp, out_path)
    recs = [existing[cid] for cid in voted]
    return {"verified": len(voted), "passed": sum(r["pass"] for r in recs), "skipped": settled_before,
            "unvoted": sum(r["unvoted"] for r in recs), "paused": stop.is_set()}


def _keep(existing, in_file, dirty, out_path, cid, votes, names):
    """Tally a task's new votes into its record: appended when the file does not have it yet, else marked for the
    rewrite at the end of the run."""
    rec = existing.get(cid) or {"id": cid, "votes": []}
    existing[cid] = rec = tally({**rec, "votes": rec["votes"] + votes}, names)
    if cid in in_file:
        dirty.add(cid)
    else:
        io.append_jsonl(out_path, [rec])
        in_file.add(cid)
