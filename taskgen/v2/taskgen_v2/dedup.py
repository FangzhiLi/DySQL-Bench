# taskgen/v2/taskgen_v2/dedup.py
"""Diversity caps (spec §5): at most `per_person` tasks per anchor row, `per_template` per template, `per_db` per
database. Rare templates are taken first so the long tail survives the per-db cap."""
from collections import Counter


def select(records, rng, per_person=2, per_template=15, per_db=600):
    freq = Counter(r["template"] for r in records)
    order = list(records)
    rng.shuffle(order)
    order.sort(key=lambda r: freq[r["template"]])          # stable: ties keep the shuffled order
    seen_person, seen_template, out = Counter(), Counter(), []
    for r in order:
        person = (r["anchor_table"], str(r["key_value"]))
        if seen_person[person] >= per_person or seen_template[r["template"]] >= per_template:
            continue
        seen_person[person] += 1; seen_template[r["template"]] += 1
        out.append(r)
        if len(out) >= per_db:
            break
    return out
