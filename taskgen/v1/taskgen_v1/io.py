# taskgen/v1/taskgen_v1/io.py
"""JSONL records, resume bookkeeping, .env loading, and the anchors JSON (db_rec) for the task-generation pipeline."""
import json, os
from taskgen_common import paths

V1 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))                     # taskgen/v1/
REPO = paths.REPO                                                                     # repo root (.env)
DATA = os.path.join(V1, "data")                                                       # db_descriptions.json
RESULTS = os.path.join(V1, "results")                                                 # step files per database, not in git
OUTPUT = os.path.join(V1, "output")                                                   # final tasks + manifest, not in git
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


def person_anchors(db_rec):
    return [a for a in db_rec["anchors"] if a["kind"] == "person_named"]
