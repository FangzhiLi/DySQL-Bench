# tests/test_taskgen_db_profile.py
import copy, sqlite3
import pytest
from taskgen_common.testing import make_db
from v2_fixtures import SHOP2, FKS, SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE
from taskgen_v2 import db_profile, schema


@pytest.fixture
def shop(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "shop2", SHOP2))


@pytest.fixture
def school(tmp_path):
    return sqlite3.connect(make_db(tmp_path, "school", SCHOOL))


def test_edges_parse_single_composite_and_spaced_names():
    e = db_profile.parse_edge("Sales Orders._CustomerID -> Customers.CustomerID")
    assert e == db_profile.Edge("Sales Orders", ("_CustomerID",), "Customers", ("CustomerID",))
    e = db_profile.parse_edge("takes.(course, sec) -> section.(course, sec)")
    assert e.cols == ("course", "sec") and e.parent == "section"
    assert db_profile.edge_text(e) == "takes.(course, sec) -> section.(course, sec)"
    assert db_profile.parse_edge("historical-terms.bioguide -> historical.bioguide_id").child == "historical-terms"
    for bad in ["orders.customer_id", "a.b -> c.d -> e.f", "t.(a, b) -> u.x", "orders -> customers.id", None]:
        with pytest.raises(ValueError):
            db_profile.parse_edge(bad)


def test_valid_profiles_have_no_problems(shop, school):
    assert db_profile.validate(SHOP_PROFILE, shop, FKS) == []
    # the advisor edge is in no foreign key list: its values decide (TEXT '3' finds INTEGER 3)
    assert db_profile.validate(SCHOOL_PROFILE, school, SCHOOL_FKS, SCHOOL_COMPOSITE) == []


def test_validate_names_every_problem(shop):
    p = copy.deepcopy(SHOP_PROFILE)
    p["persons"]["customers"]["name_cols"] = ["first_name", "surname"]
    p["events"][0]["parents"][0]["via"] = "orders.product_id -> customers.customer_id"
    p["events"][1]["path"] = ["order_items.order_id -> orders.order_id"]
    p["public"] = ["products", "staff"]
    errs = "\n".join(db_profile.validate(p, shop, FKS))
    assert "persons.customers: no column customers.surname" in errs
    assert "events[0].parents[0].via: ends at customers, expected products" in errs
    assert "events[1].path[0]: orders is not a root" in errs
    assert "public: staff hold people" in errs
    p = copy.deepcopy(SHOP_PROFILE)
    p["public"], p["events"][0]["parents"] = [], []
    p["events"].append({"table": "order_items", "label": "x", "path": ["order_items.note -> customers.first_name"], "parents": []})
    errs = "\n".join(db_profile.validate(p, shop, FKS))
    assert "tables without a role (list them in public or exclude): products" in errs
    assert "events[2].path[0]: only 0% of order_items rows find a customers row; not a foreign key" in errs
    assert db_profile.validate({**SHOP_PROFILE, "exclude": ["orders"]}, shop, FKS) == ["exclude: orders also have a role"]
    assert db_profile.validate({**SHOP_PROFILE, "events": [{**SHOP_PROFILE["events"][0], "path": "orders.customer_id -> customers.customer_id"}]},
                               shop, FKS) == ["events[0].path: wrong JSON type (see the field list)"]
    assert db_profile.validate({"roots": []}, shop, FKS)[0].startswith("missing fields: persons")
    assert db_profile.validate({**SHOP_PROFILE, "persons": {"customers": "customer_id"}}, shop, FKS)[0].startswith("malformed profile")


def test_scope_edges_version_and_root_anchor():
    assert db_profile.scope_tables(SCHOOL_PROFILE) == {"Student List", "teacher", "takes", "advisor", "section", "dept", "flags"}
    p = {**SHOP_PROFILE, "persons": {**SHOP_PROFILE["persons"],
                                     "staff": {"key": "staff_id", "name_cols": ["name"], "same_as": ["orders.qty"]}}}
    assert db_profile.Edge("orders", ("qty",), "staff", ("staff_id",)) in db_profile.edges(p)
    v = db_profile.version(SHOP_PROFILE)
    assert v == db_profile.version({**SHOP_PROFILE, "confirmed": False, "notes": ["x"]}) != db_profile.version(p)
    assert db_profile.root_anchor(SCHOOL_PROFILE, "Student List") == {"table": "Student List", "key": "sid", "names": ["name"]}
    with pytest.raises(ValueError):
        db_profile.root_anchor(SCHOOL_PROFILE, "teacher")


def test_load_save_and_get_only_confirmed(tmp_path):
    path = str(tmp_path / "p.json")
    db_profile.save({"test:shop2": SHOP_PROFILE, "test:draft": {**SHOP_PROFILE, "confirmed": False}}, path)
    assert db_profile.load(path)["test:shop2"] == SHOP_PROFILE
    assert db_profile.get("test:shop2", path) == SHOP_PROFILE
    with pytest.raises(ValueError, match="not confirmed"):
        db_profile.get("test:draft", path)
    with pytest.raises(ValueError, match="no profile"):
        db_profile.get("test:none", path)
    assert db_profile.load(str(tmp_path / "missing.json")) == {}


def test_render_shows_roles_parents_keys_and_problems(school):
    bad = {**SCHOOL_PROFILE, "confirmed": False, "notes": ["Claude: moved dept to public"]}
    text = db_profile.render_md([{"key": "test:school", "profile": SCHOOL_PROFILE, "errors": [], "pk": schema.pk_info(school)},
                                 {"key": "test:bad", "profile": bad, "errors": ["persons.x: no table 'x'"], "pk": {}}])
    assert "## test:school　已确认　校验通过" in text and "## test:bad　未确认　1 个问题" in text
    assert "| 公共表 | dept, section |" in text and "| 排除 | calendar |" in text and "| 属性表 | flags → Student List |" in text
    assert "- takes（enrolments）\n  - section ← takes.(course, sec)" in text
    assert "- 根 Student List\n  - dept ← Student List.dept" in text
    assert "主键：可省 ID：Student List, flags, teacher；非整数或复合主键：calendar(day), dept(dept_name), section(course, sec)；无主键：advisor, takes" in text
    assert "- Claude: moved dept to public" in text and "- persons.x: no table 'x'" in text
