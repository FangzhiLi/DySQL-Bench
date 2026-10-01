# taskgen/v2/taskgen_v2/verify.py
"""LLM verification by majority vote. DySQL's verify prompt (verify_qa_voting_request.py) judged the gold SQL as an
agent transcript against the agent policy, so a 27B verifier failed every pilot task for missing confirmation turns;
this prompt judges only whether the SQL implements the request, and whether the request is complete and solvable."""
import json, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from taskgen_v2 import io

VERIFY_TEMPERATURE, VERIFY_MAX_TOKENS = 1.2, 16384
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


def build_messages(cand, ddl_text):
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(user_requirements=cand["instruction"],
                                                    action_outputs=json.dumps(cand["actions"], ensure_ascii=False, indent=1),
                                                    ddl=ddl_text)}]


def parse_verdict(text):
    text = text or ""
    if FINAL in text:
        tail = text.split(FINAL)[-1]
    elif "Verification:" in text:            # the model sometimes drops the question: "Verification: Yes"
        tail = text.split("Verification:")[-1]
    else:
        return "unparsed"
    tail = re.sub(r"[*_`\s]", "", tail).lower()
    if tail.startswith("yes"):
        return "yes"
    if tail.startswith("no"):
        return "no"
    return "unparsed"


def _vote(client, msgs):
    r = client.chat(msgs, temperature=VERIFY_TEMPERATURE, max_tokens=VERIFY_MAX_TOKENS)
    return {"verdict": parse_verdict(r["content"]), "content": r["content"], "reasoning_chars": len(r.get("reasoning") or ""),
            "usage": r.get("usage")}


def _finish(rec, model):
    votes = _real(rec["votes"])
    rec["yes"] = sum(v["verdict"] == "yes" for v in votes)
    rec["no"] = len(votes) - rec["yes"]           # unparsed counts as no
    rec["pass"] = rec["yes"] > rec["no"]
    rec["verify_model"] = model
    return rec


def _vote_safe(client, msgs):
    try:
        return _vote(client, msgs)
    except Exception as e:  # an API failure is not a vote: kept for the record, ignored by counts, retried on resume
        return {"verdict": "error", "error": f"{type(e).__name__}: {e}", "content": "", "reasoning_chars": 0, "usage": None}


def _real(votes):
    return [v for v in votes if "error" not in v]


def run(cands, client, out_path, votes=3, workers=4, ddl_text=""):
    """Every vote goes to one thread pool; a new candidate's record is appended as soon as its last vote returns,
    so an interrupted run keeps all finished candidates. Top-ups of existing records are rewritten at the end."""
    existing = {r["id"]: r for r in io.read_jsonl(out_path)}
    todo = [(c, votes - len(_real(existing.get(c["id"], {}).get("votes", [])))) for c in cands]
    todo = [(c, n) for c, n in todo if n > 0]
    model = getattr(client, "model", None)
    pending = {c["id"]: n for c, n in todo}
    new_votes, updated, passed = {}, {}, 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(_vote_safe, client, build_messages(c, ddl_text)): c["id"] for c, n in todo for _ in range(n)}
        for f in as_completed(futs):
            cid = futs[f]
            new_votes.setdefault(cid, []).append(f.result())
            pending[cid] -= 1
            if pending[cid]:
                continue
            rec = existing.get(cid) or {"id": cid, "votes": []}
            rec = _finish({**rec, "votes": rec["votes"] + new_votes.pop(cid)}, model)
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
    return {"verified": len(todo), "passed": passed, "skipped": len(cands) - len(todo)}
