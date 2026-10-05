# taskgen/v2/taskgen_v2/generate.py
"""Call the generation model once per (tree, plan) and write candidate tasks. Parse failures and API failures are
recorded as candidates with instruction=None so the batch never stops and the failure rate is visible."""
import json, os, sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from taskgen_v2 import db_profile, io, llm, prompt, schema

GEN_TEMPERATURE, GEN_TOP_P, GEN_MAX_TOKENS = 1.0, 0.95, 16384


class ParseError(ValueError):
    pass


def context(db_rec, profile):
    """What every prompt of a database shares (design §4.3): the profile's description and quirks, the DDL and column
    notes of the tables in scope and a key note per table; and for plan sampling the key and foreign-key columns of
    each table ("fixed", never the target of a change) and the tables an archive may copy rows into ("copyable")."""
    path = io.resolve_db_path(db_rec["path"])
    scope = db_profile.scope_tables(profile)

    def cols_by_table(edges):
        out = {}
        for e in edges:
            out.setdefault(e.child, set()).update(e.cols)
        return out
    single = [(f, db_profile.Edge(f["table"], (f["col"],), f["ref_table"], (f["ref_col"],))) for f in db_rec.get("fks", ())]
    composite = [db_profile.Edge(f["table"], tuple(f["cols"]), f["ref_table"], tuple(f["ref_cols"])) for f in db_rec.get("fks_composite", ())]
    sure = db_profile.edges(profile) + composite + [e for f, e in single if f.get("source") == "declared"]
    fks, all_fks = cols_by_table(sure), cols_by_table(sure + [e for _, e in single])   # name-guessed keys only for targets
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        keys = schema.key_notes(conn, sorted(scope), set(profile["no_insert"]), fks)
        pk = {t: v for t, v in schema.pk_info(conn).items() if t in scope}
        unique = {t for t in pk if schema.unique_columns(conn, t)}
    finally:
        conn.close()
    fixed = {t: set(v["cols"]) | all_fks.get(t, set()) for t, v in pk.items()}
    # an archive copies rows into the same table, so a copy differs from its original only by a key SQLite fills in.
    # Without one a later write by any condition hits the copy too (olympics person_region); a key that is a foreign
    # key (beer_factory location) or a UNIQUE column would make the copy an orphan or a collision
    copyable = {t for t, v in pk.items() if v["omittable"] and not set(v["cols"]) & fks.get(t, set())
                and t not in unique and t not in profile["no_insert"]}
    return {"description": profile["description"], "quirks": profile["quirks"], "schema": schema.schema_block(path, scope),
            "keys": keys, "no_insert": set(profile["no_insert"]), "fixed": fixed, "copyable": copyable,
            "pk": {t: v["cols"] for t, v in pk.items()},
            "speaker_roles": profile.get("speaker_roles") or [], "new_lookup": profile.get("new_lookup") or []}


def parse_answer(text):
    last = None
    for cand in io.json_candidates(text or ""):
        try:
            obj = json.loads(cand, strict=False)   # a raw tab or newline inside a string is fine
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
        return {"instruction": ins, "actions": norm}
    raise ParseError(f"no JSON object with instruction/actions: {last}")


def make_candidate(db_rec, anchor, tree, plan, idx, resp, parsed, error):
    return {"id": f"{db_rec['source']}:{db_rec['db']}:{anchor['table']}:{tree['key_value']}:{idx}",
            "db": db_rec["db"], "source": db_rec["source"], "anchor_table": anchor["table"], "anchor_key": anchor["key"],
            "key_value": tree["key_value"], "anchor_name": tree["anchor_name"], "profile_version": tree.get("profile_version"),
            "plan": plan,
            "instruction": parsed["instruction"] if parsed else None, "actions": parsed["actions"] if parsed else None,
            "gen_model": (resp or {}).get("model"), "usage": (resp or {}).get("usage"),
            "raw": (resp or {}).get("content"), "error": error}


RETRYABLE = ("LLMError", "RuntimeError", "ConnectionError", "EmptyAnswer", "Truncated")


def _drop_api_failures(out_path):
    """Remove records whose model call failed (HTTP/network) or came back without an answer, so they are generated
    again. Parse failures stay: the model answered, and asking again would just resample."""
    rows = io.read_jsonl(out_path)
    keep = [r for r in rows if not (r.get("instruction") is None and (r.get("error") or "").startswith(RETRYABLE))]
    if len(keep) != len(rows):
        tmp = out_path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        io.append_jsonl(tmp, keep)
        os.replace(tmp, out_path)
    return {r["id"] for r in rows} - {r["id"] for r in keep}


def run(db_rec, anchor, trees_list, client, out_path, rng, workers=8, per_tree=1, cfg=prompt.CFG,
        materials=None, retry_errors=False):
    """materials: context() of this database."""
    materials = materials or {}
    if retry_errors:
        _drop_api_failures(out_path)
    done = io.done_ids(out_path)
    jobs = []
    for tree in trees_list:
        for idx in range(per_tree):
            cid = f"{db_rec['source']}:{db_rec['db']}:{anchor['table']}:{tree['key_value']}:{idx}"
            if cid in done:
                continue
            plan = prompt.sample_plan(rng, tree, anchor, cfg, materials)
            jobs.append((tree, idx, plan))

    def one(job):
        tree, idx, plan = job
        msgs = prompt.build_messages(db_rec, anchor, tree, plan, materials, cfg)
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
            elif not (resp.get("content") or "").strip():   # GLM once spent all 16384 tokens thinking
                error = f"EmptyAnswer: no answer after {(resp.get('usage') or {}).get('completion_tokens')} completion tokens"
            else:
                try:
                    parsed = parse_answer(resp["content"])
                except ParseError as e:
                    error = f"ParseError: {e}"
                    if resp.get("finish_reason") == "length":   # the answer was cut off at max_tokens: ask again
                        error = f"Truncated: answer cut off after {(resp.get('usage') or {}).get('completion_tokens')} completion tokens"
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
            stats["errors"] += bool(error)
            io.append_jsonl(out_path, [make_candidate(db_rec, anchor, tree, plan, idx, resp, parsed, error)])
            stats["written"] += 1
    return stats
