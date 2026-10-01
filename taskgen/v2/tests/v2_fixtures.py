# tests/v2_fixtures.py -- fixtures shared by the v2 tests (no tests here). The shop tables and anchors moved here from
# test_taskgen_trees.py, which re-exports them for the older test modules.
from taskgen_common.testing import SHOP, rows
from taskgen_v2.db_profile import version

SHOP2 = SHOP + """
CREATE TABLE order_items (item_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id), note TEXT);
CREATE TABLE staff (staff_id INTEGER PRIMARY KEY, name TEXT);
""" + rows("order_items", 300, lambda i: f"{i},{i%100},'n{i}'") + rows("staff", 5, lambda i: f"{i},'s{i}'")

FKS = [{"table": "orders", "col": "customer_id", "ref_table": "customers", "ref_col": "customer_id", "hit": 1.0, "source": "declared"},
       {"table": "orders", "col": "product_id", "ref_table": "products", "ref_col": "product_id", "hit": 1.0, "source": "declared"},
       {"table": "order_items", "col": "order_id", "ref_table": "orders", "ref_col": "order_id", "hit": 1.0, "source": "declared"}]
CUSTOMER = {"table": "customers", "key": "customer_id", "kind": "person_named", "rows": 60,
            "names": ["first_name", "last_name"], "down": ["orders", "order_items"], "up": ["products"],
            "update_targets": ["customers", "orders", "order_items", "products"]}
STAFF = {"table": "staff", "key": "staff_id", "kind": "person_named", "rows": 5, "names": ["name"],
         "down": [], "up": [], "update_targets": ["staff"]}

SHOP_PROFILE = {
    "roots": [{"table": "customers", "label": "customer", "parents": []}],
    "persons": {"customers": {"key": "customer_id", "name_cols": ["first_name", "last_name"], "same_as": []},
                "staff": {"key": "staff_id", "name_cols": ["name"], "same_as": []}},
    "events": [{"table": "orders", "label": "orders", "path": ["orders.customer_id -> customers.customer_id"],
                "parents": [{"table": "products", "via": "orders.product_id -> products.product_id", "parents": []}]},
               {"table": "order_items", "label": "order items",
                "path": ["orders.customer_id -> customers.customer_id", "order_items.order_id -> orders.order_id"], "parents": []}],
    "attributes": [], "public": ["products"], "exclude": [], "no_insert": [], "quirks": [],
    "description": "A small shop.", "confirmed": True}
SHOP_PROFILE["confirmed_version"] = version(SHOP_PROFILE)   # confirmed for exactly this content

# a table name with a space, a composite foreign key, an edge only the profile knows (advisor.s_id is TEXT and holds
# "Student List".sid), another person under an event, a 1:1 attribute, a root parent, an excluded helper table
SCHOOL = """
CREATE TABLE dept (dept_name TEXT PRIMARY KEY, building TEXT);
CREATE TABLE "Student List" (sid INTEGER PRIMARY KEY, name TEXT, dept TEXT REFERENCES dept(dept_name));
CREATE TABLE teacher (tid INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE section (course TEXT, sec INTEGER, title TEXT, PRIMARY KEY (course, sec));
CREATE TABLE takes (sid INTEGER REFERENCES "Student List"(sid), course TEXT, sec INTEGER, grade TEXT,
                    FOREIGN KEY (course, sec) REFERENCES section(course, sec));
CREATE TABLE advisor (s_id TEXT, t_id INTEGER REFERENCES teacher(tid));
CREATE TABLE flags (sid INTEGER PRIMARY KEY REFERENCES "Student List"(sid), honors INTEGER);
CREATE TABLE calendar (day TEXT PRIMARY KEY);
INSERT INTO dept VALUES ('d0', 'B0'), ('d1', 'B1');
INSERT INTO section VALUES ('c1', 1, 'Algebra'), ('c1', 2, 'Algebra'), ('c2', 1, 'Biology');
INSERT INTO calendar VALUES ('2024-01-01'), ('2024-01-02');
""" + rows('"Student List"', 10, lambda i: f"{i},'s{i}','d{i % 2}'") + rows("teacher", 3, lambda i: f"{i},'t{i}'") \
    + rows("takes", 8, lambda i: f"{i},'c1',{1 + i % 2},'A'") + rows("takes", 8, lambda i: f"{i},'c2',1,'B'") \
    + rows("advisor", 9, lambda i: f"'{i}',{i % 3}") + rows("flags", 5, lambda i: f"{i},{i % 2}")
SCHOOL_FKS = [{"table": "Student List", "col": "dept", "ref_table": "dept", "ref_col": "dept_name", "hit": 1.0, "source": "declared"},
              {"table": "takes", "col": "sid", "ref_table": "Student List", "ref_col": "sid", "hit": 1.0, "source": "declared"},
              {"table": "advisor", "col": "t_id", "ref_table": "teacher", "ref_col": "tid", "hit": 1.0, "source": "declared"},
              {"table": "flags", "col": "sid", "ref_table": "Student List", "ref_col": "sid", "hit": 1.0, "source": "declared"}]
SCHOOL_COMPOSITE = [{"table": "takes", "cols": ["course", "sec"], "ref_table": "section", "ref_cols": ["course", "sec"], "hit": 1.0, "source": "declared"}]
SCHOOL_PROFILE = {
    "roots": [{"table": "Student List", "label": "student",
               "parents": [{"table": "dept", "via": "Student List.dept -> dept.dept_name", "parents": []}]}],
    "persons": {"Student List": {"key": "sid", "name_cols": ["name"], "same_as": []},
                "teacher": {"key": "tid", "name_cols": ["name"], "same_as": []}},
    "events": [{"table": "takes", "label": "enrolments", "path": ["takes.sid -> Student List.sid"],
                "parents": [{"table": "section", "via": "takes.(course, sec) -> section.(course, sec)", "parents": []}]},
               {"table": "advisor", "label": "advisors", "path": ["advisor.s_id -> Student List.sid"],
                "parents": [{"table": "teacher", "via": "advisor.t_id -> teacher.tid", "parents": []}]}],
    "attributes": [{"table": "flags", "of": "Student List", "via": "flags.sid -> Student List.sid"}],
    "public": ["dept", "section"], "exclude": ["calendar"], "no_insert": ["section"],
    "quirks": ["dept names are codes such as d0."], "description": "A small school.", "confirmed": True}
SCHOOL_PROFILE["confirmed_version"] = version(SCHOOL_PROFILE)
