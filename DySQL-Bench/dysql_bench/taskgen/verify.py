# dysql_bench/taskgen/verify.py
"""LLM verification by majority vote. The prompt is DySQL's verify_qa_voting_request.py with two added principles
(parameter completeness, solvability without seeing the SQL) and the DDL of the database in the user message."""
import json, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dysql_bench.taskgen import io

VERIFY_TEMPERATURE, VERIFY_MAX_TOKENS = 1.2, 16384
WIKI = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_wiki.md"), encoding="utf-8").read()
FINAL = "Verification: Is the answer correct (Yes/No)?"

SYSTEM = """Please help me to verify whether the assistant has solved the user's problem based on the provided user and assistant interactions.
The user has outlined specific requirements, and the assistant's response should address all of these needs.
The output should indicate whether the assistant has fully addressed the user's request, with a detailed check of the Agent Policy and assistant's sql call validity, correctness of invocation.

{domain_rules}

You have six principles to do this.
1. [Verification] The output should thoroughly verify whether the assistant's responses and tool calls have correctly addressed all of the user's requests step by step.
2. [SQL Call Accuracy] The output should check whether the assistant used the appropriate sql calls, with correct invocation and parameters, to solve the user's task.
3. [Consistency Check] The output should ensure that the data provided by the user is consistent throughout the interaction, without any discrepancies or hallucinations.
4. [Correctness] The verification should confirm if all of the user's requirements have been fully addressed and that no crucial aspect of the problem was overlooked.
5. [Completeness of parameters] Every value the SQL uses (ids, names, amounts, dates, new values) must be stated in the user's requirements, except values that identify the user's own record, which the assistant can look up after authentication.
6. [Solvability] A person who can only read the user's requirements and query the database, without seeing these SQL calls, must be able to arrive at exactly the same database changes.

## Response format
The response should include reasoning process step by step, and ending with: "Verification: Is the answer correct (Yes/No)?" followed by "Yes" or "No".
"""

USER = """Here is the user's requirements:
{user_requirements}

Here is the assistant's response (the SQL calls, in order):
{action_outputs}

Here is the database schema (DDL):
{ddl}
"""


def build_messages(cand, ddl_text):
    return [{"role": "system", "content": SYSTEM.format(domain_rules=WIKI)},
            {"role": "user", "content": USER.format(user_requirements=cand["instruction"],
                                                    action_outputs=json.dumps(cand["actions"], ensure_ascii=False, indent=1),
                                                    ddl=ddl_text)}]


def parse_verdict(text):
    if FINAL not in (text or ""):
        return "unparsed"
    tail = re.sub(r"[*_`\s]", "", text.split(FINAL)[-1]).lower()
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
    rec["yes"] = sum(v["verdict"] == "yes" for v in rec["votes"])
    rec["no"] = len(rec["votes"]) - rec["yes"]           # unparsed counts as no
    rec["pass"] = rec["yes"] > rec["no"]
    rec["verify_model"] = model
    return rec


def _vote_safe(client, msgs):
    try:
        return _vote(client, msgs)
    except Exception as e:  # an API failure is a lost vote, recorded as unparsed (counts as no)
        return {"verdict": "unparsed", "content": f"{type(e).__name__}: {e}", "reasoning_chars": 0, "usage": None}


def run(cands, client, out_path, votes=3, workers=4, ddl_text=""):
    """Every vote goes to one thread pool; a new candidate's record is appended as soon as its last vote returns,
    so an interrupted run keeps all finished candidates. Top-ups of existing records are rewritten at the end."""
    existing = {r["id"]: r for r in io.read_jsonl(out_path)}
    todo = [(c, votes - len(existing.get(c["id"], {}).get("votes", []))) for c in cands]
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
