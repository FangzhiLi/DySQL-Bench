# tests/test_dysql_acceptance.py
"""DySQL-Bench's own 13 DBs define what 'usable' means: every table their gold SQL writes must sit in some
anchor's scope, every UPDATE target must be an update target, and cars/cookbook are the only entity-only DBs.
Size rules are not asserted (human_resources has 37 rows)."""
import ast, glob, os, re
from collections import Counter
import pytest
from taskgen_common.db_select import profile_db, evaluate
from taskgen_common.paths import DYSQL_ENVS as ENVS

DBS = sorted(glob.glob(f"{ENVS}/*/data/*.sqlite"))
CFG = dict(tables=(1, 50), max_cols=10_000, rows=(0, 10**9), max_mb=10_000, min_fks=0, fk_min_hit=0.3,
           anchor_min_rows=5, long_text_avg_len=200, min_component_share=0.0,
           leak_names=set(), overlap=0.6, leak_ref={})
ENTITY_ONLY = {"cars", "cookbook"}
WRITE = re.compile(r'(?is)^\s*(insert(?:\s+or\s+\w+)?\s+into|update(?:\s+or\s+\w+)?|delete\s+from|replace\s+into)'
                   r'\s+["`\[]?([\w ]+?)["`\]]?[\s(]')

def gold_writes(tasks_file):
    """(op, table) for every write statement in the gold actions, read with ast (no import of the env)."""
    for node in ast.walk(ast.parse(open(tasks_file, encoding="utf-8").read())):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "sql" and isinstance(v, ast.Constant):
                    for st in v.value.split(";"):
                        m = WRITE.match(st + " ")
                        if m:
                            yield m.group(1).split()[0].upper(), m.group(2).strip()

@pytest.mark.skipif(not DBS, reason="DySQL env DBs not present")
@pytest.mark.parametrize("path", DBS, ids=[os.path.basename(p)[:-7] for p in DBS])
def test_dysql_anchors_cover_every_gold_write(path):
    p = profile_db(path)
    r = evaluate(p, CFG)
    lower = {t["name"].lower(): t["name"] for t in p["tables"]}
    scope = {x for a in r["anchors"] for x in [a["table"], *a["down"], *a["up"]]}
    miss = Counter()
    for op, tb in gold_writes(os.path.join(os.path.dirname(os.path.dirname(path)), "tasks_test.py")):
        name = lower.get(tb.lower())
        if name is None:
            continue  # 2 gold statements write tables that do not exist (agentnotes, corrections)
        if name not in scope or (op == "UPDATE" and name not in r["update_targets"]):
            miss[(op, name)] += 1
    assert not miss, dict(miss)
    if r["db"] in ENTITY_ONLY:
        assert r["anchor_kinds"] == ["entity"], r["anchors"]
    else:
        assert r["has_person_named"], r["person_anchors"]
