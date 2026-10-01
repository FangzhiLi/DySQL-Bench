# taskgen/v2/taskgen_v2/dedup.py
"""Diversity caps (spec §5): at most `per_person` tasks per anchor row, `per_template` per template, `per_db` per
database. Rare templates are taken first so the long tail survives the per-db cap. The same caps, looser and without
the per-person one, pick what the verifier sees (design §4.6: check -> pre-cap -> verify -> final cap)."""
from collections import Counter


def select(records, rng, per_person=2, per_template=15, per_db=600):
    freq = Counter(r["template"] for r in records)
    order = list(records)
    rng.shuffle(order)
    order.sort(key=lambda r: freq[r["template"]])          # stable: ties keep the shuffled order
    seen_person, seen_template, out = Counter(), Counter(), []
    for r in order:
        person = (r["anchor_table"], str(r["key_value"]))
        if (per_person is not None and seen_person[person] >= per_person) or seen_template[r["template"]] >= per_template:
            continue
        seen_person[person] += 1; seen_template[r["template"]] += 1
        out.append(r)
        if len(out) >= per_db:
            break
    return out


def precap(cands, checks, rng, per_template=25, per_db=900):
    """The candidates that passed the check, at most per_template per template and per_db in all: the verifier's
    calls are not spent on tasks the final cap (2/15/600) would drop anyway."""
    ok = {c["id"]: c for c in checks if c["ok"]}
    recs = [{**c, "template": ok[c["id"]]["template"]} for c in cands if c["id"] in ok]
    keep = {r["id"] for r in select(recs, rng, per_person=None, per_template=per_template, per_db=per_db)}
    return [c for c in cands if c["id"] in keep]
