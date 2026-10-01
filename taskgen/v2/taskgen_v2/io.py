# taskgen/v2/taskgen_v2/io.py
"""JSONL records, resume bookkeeping, .env loading, and the anchors JSON (db_rec) for the task-generation pipeline."""
import json, os, re
from taskgen_common import paths

V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))                     # taskgen/v2/
REPO = paths.REPO                                                                     # repo root (.env)
DATA = os.path.join(V2, "data")                                                       # db_descriptions.json
RESULTS = os.path.join(V2, "results")                                                 # step files per database, not in git
OUTPUT = os.path.join(V2, "output")                                                   # final tasks + manifest, not in git
ANCHORS_JSON = paths.ANCHORS_JSON                                                     # shared step-0 output (taskgen/common)
DATA_ROOT = os.path.expanduser(os.environ.get("TEXT2SQL_BENCH", "~/Documents/Isa/text2sql_bench"))


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, records):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def done_ids(path):
    return {r["id"] for r in read_jsonl(path) if "id" in r}


def load_dotenv(path=os.path.join(REPO, ".env")):
    """KEY=VALUE lines into os.environ (existing variables win). No python-dotenv dependency."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def resolve_db_path(p):
    """Absolute sqlite path: as given if absolute, else relative to TEXT2SQL_BENCH."""
    return p if os.path.isabs(p) else os.path.join(DATA_ROOT, p)


def load_db_recs(path=ANCHORS_JSON):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def json_candidates(text):
    """Strings that may hold the JSON object of a model answer, most likely first: the <answer> body, then {...} spans."""
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
