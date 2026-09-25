# tests/_sqlite_fixtures.py
import sqlite3


def make_db(tmp_path, name, script):
    p = tmp_path / f"{name}.sqlite"
    c = sqlite3.connect(p); c.executescript("BEGIN;" + script + "COMMIT;"); c.close()
    return str(p)


def rows(table, n, fmt):
    return "".join(f"INSERT INTO {table} VALUES ({fmt(i)});" for i in range(n))


SHOP = """
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT);
CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT, price REAL);
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id),
                     product_id INTEGER REFERENCES products(product_id), qty INTEGER);
""" + rows("customers", 60, lambda i: f"{i},'a{i}','b{i}'") \
    + rows("products", 60, lambda i: f"{i},'p{i}',1.0") \
    + rows("orders", 100, lambda i: f"{i},{i%60},{i%60},1")
