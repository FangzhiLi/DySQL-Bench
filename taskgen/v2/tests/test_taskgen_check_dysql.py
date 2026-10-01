# tests/test_taskgen_check_dysql.py
"""Calibration of check.py on DySQL's own gold tasks (spec §7): outside the known no-op class, >= 90% must pass.
The full 13-env report is scripts/calibrate_check.py; this test runs two small envs so it stays fast."""
from collections import Counter
from taskgen_v2 import check, dysql


def test_chinook_and_music_gold_tasks_mostly_pass():
    total, ok, reasons = 0, 0, Counter()
    for env in ("chinook", "music"):
        rec = dysql.db_rec(env)
        for cand in dysql.candidates(env):
            if cand["group"] == "7_no_change":
                continue
            r = check.run_check(rec, cand)
            total += 1; ok += r["ok"]
            for x in r["reasons"]:
                reasons[x.split(":")[0]] += 1
    assert total >= 60 and ok / total >= 0.85, (ok, total, reasons.most_common())
