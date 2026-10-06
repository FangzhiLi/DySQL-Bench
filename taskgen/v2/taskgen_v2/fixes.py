# taskgen/v2/taskgen_v2/fixes.py
"""Fixes for the tasks the 2026-10-06 audit found bad (docs/2026-10-06-task-audit.md). A fix is a new candidate
<tree>:<next index> that goes through check and verify like any other; scripts/fix_audit_tasks.py drives it."""
import re
from taskgen_v2 import audit, check

SYSTEM = """You edit training tasks for a database customer-service agent. A task is one user's request and the SQL that carries it out. A reviewer found a problem with this task; the SQL below is now correct. Rewrite the request so that it asks for exactly what the SQL does and fixes the problem the note describes.

1. Change only what the note asks for. Keep the speaker, their tone, the first sentence's identification and every other request as they are.
2. Keep every value the SQL uses that the request already gives, and give every value the SQL uses that the request does not.
3. First person, only asks for changes, no questions; about the same length as before.

Think inside <thought></thought>, then answer inside <answer></answer> as strict JSON: {"instruction": "..."}"""

USER = """# Database
{description}

## Request
{instruction}

## SQL (correct)
{sql}

## Problem to fix
{note}

Rewrite the request now."""


def tree_of(cid):
    return cid.rsplit(":", 1)[0]


def next_id(cid, ids):
    """The next free <tree>:<index> after every candidate of cid's tree."""
    tree = tree_of(cid)
    return f"{tree}:{max(int(i.rsplit(':', 1)[1]) for i in ids if tree_of(i) == tree) + 1}"


def substitute(text, mapping):
    """Each old value replaced by its new one wherever it stands as a whole token ('742' in "movie 742" and in
    "(742, 1321", not in '17420')."""
    for old, new in mapping.items():
        text = re.sub(r"(?<![\w.])" + re.escape(old) + r"(?![\w])", new, text)
    return text


def listed_order(instruction, keys):
    """The keys in the order the instruction first mentions them (keys it does not mention last, as given)."""
    text = check.text_forms(instruction)
    pos = {k: audit.find_pos(text, check.norm_literal(k)) for k in keys}
    return sorted(keys, key=lambda k: (pos[k] is None, pos[k] or 0))


def messages(cand, stmts, note, materials):
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(description=materials.get("description", ""), instruction=cand["instruction"],
                                                    sql="\n".join(stmts), note=note)}]
