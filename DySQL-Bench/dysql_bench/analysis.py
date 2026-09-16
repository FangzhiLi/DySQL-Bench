# dysql_bench/analysis.py
"""Pure helpers used for logging / post-hoc analysis. No evaluation semantics live here."""
import re
from typing import Dict, List, Optional
import sqlparse
from dysql_bench.types import Task, SQL_ACTION_NAME

SHORT_MAX_ACTIONS = 2  # paper: fewer than three actions = Short

def classify_task(task: Task) -> dict:
    sqls = [a.kwargs["sql"] for a in task.actions if a.name == SQL_ACTION_NAME]
    types = set()
    for s in sqls:
        for stmt in sqlparse.split(s):
            stmt = stmt.strip()
            if stmt:
                types.add(sqlparse.parse(stmt)[0].get_type().upper())
    return {"n_gold_actions": len(sqls),
            "length": "short" if len(sqls) <= SHORT_MAX_ACTIONS else "long",
            "crud_types": sorted(types)}

def count_fabricated_results(traj: List[dict]) -> int:
    return sum(1 for m in traj if m.get("role") == "assistant" and "<result>" in (m.get("content") or ""))

def diff_table_hashes(a: Dict[str, str], b: Dict[str, str]) -> List[str]:
    return sorted(t for t in set(a) | set(b) if a.get(t) != b.get(t))

def count_sql_errors(traj: List[dict]) -> int:
    return sum(1 for m in traj
               if m.get("role") == "user" and m.get("name") == "sql"
               and (m.get("content") or "").lstrip().startswith("<result>Error:"))

_SQL_BLOCK = re.compile(r"```sql(.*?)```|<sql>(.*?)</sql>", re.DOTALL)
_CONFIRM = re.compile(r"\b(yes|confirm|confirmed|proceed|go ahead)\b", re.IGNORECASE)

def _first_sql(content: str) -> Optional[str]:
    m = _SQL_BLOCK.search(content or "")
    return (m.group(1) or m.group(2)).strip() if m else None

def confirmed_before_write(traj: List[dict]) -> Optional[bool]:
    """Rule-based: was there a user 'yes/confirm/proceed' before the agent's first non-SELECT SQL?
    Returns None when the trajectory has no write. Analysis only, not part of evaluation."""
    seen_confirm = False
    for m in traj:
        if m.get("role") == "user" and m.get("name") != "sql":
            if _CONFIRM.search(m.get("content") or ""):
                seen_confirm = True
        elif m.get("role") == "assistant":
            sql = _first_sql(m.get("content"))
            if sql and sqlparse.parse(sql) and sqlparse.parse(sql)[0].get_type().upper() not in ("SELECT", "UNKNOWN"):
                return seen_confirm
    return None
