# taskgen/v2/taskgen_v2/verify.py
"""LLM verification by majority vote. DySQL's verify prompt (verify_qa_voting_request.py) judged the gold SQL as an
agent transcript against the agent policy, so a 27B verifier failed every pilot task for missing confirmation turns;
this prompt judges only whether the SQL implements the request, and whether the request is complete and solvable.
Several models may vote (design §4.6, D4): each passes a task when its Yes votes outnumber its No votes, and a task
passes when every model passes it."""
import json, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from taskgen_v2 import io, llm

VERIFY_TEMPERATURE, VERIFY_MAX_TOKENS = 1.2, 16384
DEFAULT_VOTES = 2   # with two votes both must say Yes (design §4.6)
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
    spec = spec or os.environ.get("TASKGEN_VERIFY_MODELS") or f"{os.environ.get('TASKGEN_VERIFY_MODEL', '')}:{DEFAULT_VOTES}"
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


def tally(rec, names):
    """Per model Yes/No counts and pass (Yes strictly more than No; unparsed counts as No); the task passes when
    every model passes it."""
    rec["models"] = {}
    for name in names:
        votes = _real(rec["votes"], name)
        yes = sum(v["verdict"] == "yes" for v in votes)
        rec["models"][name] = {"yes": yes, "no": len(votes) - yes, "pass": yes > len(votes) - yes}
    rec["pass"] = all(m["pass"] for m in rec["models"].values())
    rec["verify_model"] = ",".join(names)
    return rec


def run(cands, models, out_path, workers=3, context=lambda cand: ("", ())):
    """models: [(client, votes)]; context(cand) -> (ddl_text, notes). Every vote goes to one thread pool; a new
    candidate's record is appended as soon as its last vote returns, so an interrupted run keeps all finished
    candidates. Records that were topped up are rewritten in place at the end."""
    names = [getattr(c, "model", None) for c, _ in models]
    existing = {r["id"]: r for r in io.read_jsonl(out_path)}
    jobs = [(c, client) for c in cands for client, n in models
            for _ in range(n - len(_real(existing.get(c["id"], {}).get("votes", []), getattr(client, "model", None))))]
    pending = {}
    for c, _ in jobs:
        pending[c["id"]] = pending.get(c["id"], 0) + 1
    new_votes, updated, passed = {}, {}, 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(_vote_safe, client, build_messages(c, *context(c))): c["id"] for c, client in jobs}
        for f in as_completed(futs):
            cid = futs[f]
            new_votes.setdefault(cid, []).append(f.result())
            pending[cid] -= 1
            if pending[cid]:
                continue
            rec = existing.get(cid) or {"id": cid, "votes": []}
            rec = tally({**rec, "votes": rec["votes"] + new_votes.pop(cid)}, names)
            passed += rec["pass"]
            if cid in existing:
                updated[cid] = rec
            else:
                io.append_jsonl(out_path, [rec])
    if updated:  # rewrite the file with the topped-up records in place
        rows = [updated.get(r["id"], r) for r in io.read_jsonl(out_path)]
        tmp = out_path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        io.append_jsonl(tmp, rows)
        os.replace(tmp, out_path)
    return {"verified": len(pending), "passed": passed, "skipped": len(cands) - len(pending)}
