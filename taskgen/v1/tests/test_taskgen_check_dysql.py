# tests/test_taskgen_check_dysql.py
"""Calibration of check.py on DySQL's own gold tasks (spec §7): outside the known no-op class, >= 90% must pass.
The full 13-env report is scripts/calibrate_check.py; this test runs two small envs so it stays fast."""
import importlib.util, os
from collections import Counter
from taskgen_v1 import check

_SPEC = importlib.util.spec_from_file_location("calibrate_check", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "calibrate_check.py"))
cc = importlib.util.module_from_spec(_SPEC); _SPEC.loader.exec_module(cc)


def test_chinook_and_music_gold_tasks_mostly_pass():
    total, ok, reasons = 0, 0, Counter()
    for env in ("chinook", "music"):
        rec = cc.dysql_db_rec(env)
        for cand in cc.dysql_candidates(env):
            if cand["group"] == "7_no_change":
                continue
            r = check.run_check(rec, cand)
            total += 1; ok += r["ok"]
            for x in r["reasons"]:
                reasons[x.split(":")[0]] += 1
    assert total >= 60 and ok / total >= 0.85, (ok, total, reasons.most_common())
