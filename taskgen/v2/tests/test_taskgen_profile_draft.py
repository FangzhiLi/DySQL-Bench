# tests/test_taskgen_profile_draft.py
import glob, json, sqlite3
import pytest
from taskgen_common.paths import DYSQL_ENVS
from taskgen_common.testing import make_db
from v2_fixtures import SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE
from taskgen_v2 import db_profile, profile_draft

REC = {"source": "test", "db": "school", "anchors": [], "fks": SCHOOL_FKS, "fks_composite": SCHOOL_COMPOSITE}
HINTS = {"roots": ["Student List"], "notes": ["dept names are codes."]}


class FakeClient:
    def __init__(self, answers): self.answers, self.seen = list(answers), []
    def chat(self, messages, **kw):
        self.seen.append(messages)
        return {"content": self.answers.pop(0), "model": "fake"}


def answer(profile):
    return "<thought>t</thought><answer>" + json.dumps(profile) + "</answer>"


@pytest.fixture
def school(tmp_path):
    path = make_db(tmp_path, "school", SCHOOL)
    return sqlite3.connect(path), path


def test_compact_schema_shows_keys_references_and_rows(school):
    conn, _ = school
    text = profile_draft.compact_schema(conn, SCHOOL_FKS, SCHOOL_COMPOSITE)
    assert "TABLE Student List -- 10 rows; key sid (INTEGER; a new row may leave it out)" in text
    assert "TABLE section -- 3 rows; key (course, sec)" in text and "TABLE dept -- 2 rows; key dept_name (TEXT)" in text
    assert "  references: sid -> Student List.sid; (course, sec) -> section.(course, sec)" in text
    assert "  references: t_id -> teacher.tid" in text
    assert '  row: {"sid": 0, "name": "s0", "dept": "d0"}' in text
    assert "row:" not in profile_draft.compact_schema(conn, SCHOOL_FKS, SCHOOL_COMPOSITE, samples=0)


def test_messages_carry_examples_hints_and_schema(school):
    conn, path = school
    msgs = profile_draft.messages("test:school", conn, REC, path, HINTS, profile_draft.load_examples())
    assert "### chinook (DySQL)" in msgs[0]["content"] and "### entertainment (DySQL)" in msgs[0]["content"]
    u = msgs[1]["content"]
    assert "# Database test:school\n\n## Hints from the person who will review the profile\nRoots: Student List\n- dept names are codes." in u
    assert "TABLE takes -- 16 rows; no primary key" in u


def test_examples_are_valid_profiles_of_their_dysql_databases():
    for x in profile_draft.load_examples():
        path = glob.glob(f"{DYSQL_ENVS}/{x['env']}/data/*.sqlite")[0]
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        fks = profile_draft.pragma_fks(conn)
        assert db_profile.validate(x["profile"], conn, fks) == [] and x["profile"]["confirmed"] is False
        assert x["schema"] == profile_draft.compact_schema(conn, fks, (), None, samples=0)


def test_draft_repairs_until_valid(school):
    conn, path = school
    first = {**SCHOOL_PROFILE, "public": ["section"]}                         # dept loses its role
    client = FakeClient([answer(first), answer(SCHOOL_PROFILE)])
    p = profile_draft.draft(client, "test:school", conn, REC, path, HINTS, profile_draft.load_examples())
    assert p["draft"] == {"model": "fake", "rounds": 2, "errors": []} and p["confirmed"] is False and p["notes"] == []
    assert {k: p[k] for k in ("roots", "events", "public")} == {k: SCHOOL_PROFILE[k] for k in ("roots", "events", "public")}
    repair = client.seen[1][-1]["content"]
    assert repair.startswith("The profile has these problems:\n- ") and "dept hangs under Student List but is not public" in repair


def test_draft_keeps_the_hinted_roots_and_gives_up_after_the_repairs(school):
    conn, path = school
    wrong = {**SCHOOL_PROFILE, "roots": SCHOOL_PROFILE["roots"] + [{"table": "teacher", "label": "teacher", "parents": []}]}
    client = FakeClient([answer(wrong), "no json here", answer(wrong)])
    p = profile_draft.draft(client, "test:school", conn, REC, path, HINTS, profile_draft.load_examples())
    assert p["draft"]["rounds"] == 3 and p["draft"]["errors"] == ["roots: must be exactly Student List, as the hints say"]
    assert "no profile JSON in the answer" in client.seen[2][-1]["content"]
