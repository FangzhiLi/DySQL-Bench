# taskgen/v2/taskgen_v2/generate.py
"""Call the generation model once per (tree, plan) and write candidate tasks. Parse failures and API failures are
recorded as candidates with instruction=None so the batch never stops and the failure rate is visible."""
import json, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from taskgen_v2 import io, llm, prompt

GEN_TEMPERATURE, GEN_TOP_P, GEN_MAX_TOKENS = 1.0, 0.95, 16384


class ParseError(ValueError):
    pass


def _json_candidates(text):
    m = re.search(r"<answer>(.*?)(</answer>|$)", text, re.S)
    body = m.group(1) if m else text
    body = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", body.strip(), flags=re.S)
    yield body
    for mm in reversed(list(re.finditer(r"\{.*\}", text, re.S))):   # greedy last {...}
        yield mm.group(0)
    depth, start = 0, None                                             # balanced scan for the last object
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:i + 1]


def parse_answer(text):
    last = None
    for cand in _json_candidates(text or ""):
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError as e:
            last = e; continue
        if not isinstance(obj, dict):
            continue
        ins, acts = obj.get("instruction"), obj.get("actions")
        if not isinstance(ins, str) or not ins.strip() or not isinstance(acts, list) or not acts:
            last = "missing/empty instruction or actions"   # e.g. a {"sql": ...} quoted in the thought: keep looking
            continue
        ins = ins.strip()
        norm = []
        for a in acts:
            sql = a.get("sql") if isinstance(a, dict) else a
            if not isinstance(sql, str) or not sql.strip():
                raise ParseError("action without sql")
            norm.append({"sql": sql.strip()})
        return {"instruction": ins, "actions": norm, "outputs": obj.get("outputs") or []}
    raise ParseError(f"no JSON object with instruction/actions: {last}")


def make_candidate(db_rec, anchor, tree, plan, idx, resp, parsed, error):
    return {"id": f"{db_rec['source']}:{db_rec['db']}:{anchor['table']}:{tree['key_value']}:{idx}",
            "db": db_rec["db"], "source": db_rec["source"], "anchor_table": anchor["table"], "anchor_key": anchor["key"],
            "key_value": tree["key_value"], "anchor_name": tree["anchor_name"], "profile_version": tree.get("profile_version"),
            "plan": plan,
            "instruction": parsed["instruction"] if parsed else None, "actions": parsed["actions"] if parsed else None,
            "outputs": parsed["outputs"] if parsed else None,
            "gen_model": (resp or {}).get("model"), "usage": (resp or {}).get("usage"),
            "raw": (resp or {}).get("content"), "error": error}


def _drop_api_failures(out_path):
    """Remove records whose model call failed (HTTP/network), so they are generated again. Parse failures stay:
    the model answered, and asking again would just resample."""
    rows = io.read_jsonl(out_path)
    keep = [r for r in rows if not (r.get("instruction") is None and (r.get("error") or "").startswith(("LLMError", "RuntimeError", "ConnectionError")))]
    if len(keep) != len(rows):
        tmp = out_path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        io.append_jsonl(tmp, keep)
        os.replace(tmp, out_path)
    return {r["id"] for r in rows} - {r["id"] for r in keep}


def run(db_rec, anchor, trees_list, client, out_path, rng, workers=8, per_tree=1, cfg=prompt.CFG,
        db_description="", schema_text="", retry_errors=False, next_ids=None):
    if retry_errors:
        _drop_api_failures(out_path)
    done = io.done_ids(out_path)
    jobs = []
    for tree in trees_list:
        for idx in range(per_tree):
            cid = f"{db_rec['source']}:{db_rec['db']}:{anchor['table']}:{tree['key_value']}:{idx}"
            if cid in done:
                continue
            plan = prompt.sample_plan(rng, tree, anchor, cfg)
            jobs.append((tree, idx, plan))

    def one(job):
        tree, idx, plan = job
        msgs = prompt.build_messages(db_rec, anchor, tree, plan, db_description, schema_text, cfg, next_ids=next_ids)
        return client.chat(msgs, temperature=GEN_TEMPERATURE, max_tokens=GEN_MAX_TOKENS, top_p=GEN_TOP_P)

    def safe(job):
        try:
            return one(job)
        except Exception as e:
            return e

    stats = {"written": 0, "errors": 0, "skipped": len(trees_list) * per_tree - len(jobs)}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:   # each result is appended as soon as it returns
        futs = {ex.submit(safe, job): job for job in jobs}
        for f in as_completed(futs):
            tree, idx, plan = futs[f]
            resp, parsed, error = f.result(), None, None
            if isinstance(resp, Exception):
                error, resp = f"{type(resp).__name__}: {resp}", None
            else:
                try:
                    parsed = parse_answer(resp["content"])
                except ParseError as e:
                    error = f"ParseError: {e}"
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
            stats["errors"] += bool(error)
            io.append_jsonl(out_path, [make_candidate(db_rec, anchor, tree, plan, idx, resp, parsed, error)])
            stats["written"] += 1
    return stats
