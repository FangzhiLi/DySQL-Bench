# tests/test_taskgen_db_profile.py
import copy, sqlite3
import pytest
from taskgen_common.testing import make_db, rows
from v2_fixtures import SHOP2, FKS, SHOP_PROFILE, SCHOOL, SCHOOL_FKS, SCHOOL_COMPOSITE, SCHOOL_PROFILE
from taskgen_v2 import db_profile, owners, schema


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


def test_an_edge_must_lead_to_one_parent_row(shop):
    # written from the wrong side: an order has many items, so "orders -> order_items" picks one of them at random
    p = copy.deepcopy(SHOP_PROFILE)
    p["events"][0]["parents"] = [{"table": "products", "via": "orders.product_id -> products.product_id", "parents": []},
                                 {"table": "order_items", "via": "orders.order_id -> order_items.order_id", "parents": []}]
    assert db_profile.validate(p, shop, FKS) == [
        "events[0].parents[1].via: order_items.order_id repeats values, so the edge leads to several rows; "
        "write it from the table that holds the reference"]


def test_a_persons_own_rows_cannot_be_public(shop, school):
    # tracing stops at public tables, so an event, attribute or path table listed there would turn own rows public
    for t in ("takes", "flags"):
        p = {**SCHOOL_PROFILE, "public": SCHOOL_PROFILE["public"] + [t]}
        assert db_profile.validate(p, school, SCHOOL_FKS, SCHOOL_COMPOSITE) == [
            f"public: {t} holds a person's own rows (event, path or attribute table), so it cannot be public"]
    p = {**SHOP_PROFILE, "events": SHOP_PROFILE["events"][1:], "public": ["products", "orders"]}   # orders: only on a path
    assert db_profile.validate(p, shop, FKS) == [
        "public: orders holds a person's own rows (event, path or attribute table), so it cannot be public"]


def test_a_path_must_reach_its_root_within_the_tracing_hops(tmp_path):
    # ownership tracing follows at most MAX_PATH edges, so a longer path would label the person's own events public
    chain = ["p", "a", "b", "c", "d"]
    db = make_db(tmp_path, "chain", "CREATE TABLE p (id INTEGER PRIMARY KEY, name TEXT);"
                 + "".join(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY, up INTEGER);" for t in chain[1:])
                 + rows("p", 3, lambda i: f"{i},'p{i}'") + "".join(rows(t, 3, lambda i: f"{i},{i}") for t in chain[1:]))
    path = [f"{t}.up -> {u}.id" for u, t in zip(chain, chain[1:])]
    p = {"roots": [{"table": "p", "label": "person", "parents": []}],
         "persons": {"p": {"key": "id", "name_cols": ["name"], "same_as": []}},
         "events": [{"table": "d", "label": "d rows", "path": path, "parents": []}], "attributes": [], "public": [],
         "exclude": [], "no_insert": [], "quirks": [], "description": "A chain.", "confirmed": False}
    conn = sqlite3.connect(db)
    assert db_profile.validate(p, conn) == [
        f"events[0]: path has 4 edges, but ownership tracing follows at most {db_profile.MAX_PATH}; its rows would not reach the person"]
    p = {**p, "events": [{"table": "c", "label": "c rows", "path": path[:3], "parents": []}], "public": ["d"]}
    assert db_profile.validate(p, conn) == [] and owners.MAX_HOPS == db_profile.MAX_PATH == 3


def test_same_as_must_hold_the_persons_keys(shop):
    # same_as says "this column holds the same person's key"; a column that seldom matches would mislabel rows
    p = copy.deepcopy(SHOP_PROFILE)
    p["persons"]["staff"]["same_as"] = ["order_items.note"]
    assert db_profile.validate(p, shop, FKS) == ["persons.staff.same_as: only 0% of order_items.note values are staff keys"]
    p["persons"]["staff"]["same_as"], p["persons"]["customers"]["same_as"] = [], ["orders.customer_id"]
    assert db_profile.validate(p, shop, FKS) == []


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


def test_an_edit_after_confirming_undoes_the_confirmation(tmp_path):
    path = str(tmp_path / "p.json")
    p = db_profile.confirm({**SHOP_PROFILE, "confirmed": False})
    assert p["confirmed"] is True and p["confirmed_version"] == db_profile.version(SHOP_PROFILE)
    db_profile.save({"a": {**p, "notes": ["User: fine"]}, "b": {**p, "quirks": ["qty is never 0."]}}, path)
    assert db_profile.get("a", path)["notes"] == ["User: fine"]   # review fields are not content
    with pytest.raises(ValueError, match="changed after it was confirmed"):
        db_profile.get("b", path)
    assert [db_profile.status(x) for x in (p, {**p, "quirks": ["x"]}, {**p, "confirmed": False})] == [
        "confirmed", "changed since confirmed", "not confirmed"]


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
