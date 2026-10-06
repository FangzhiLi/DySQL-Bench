# tests/test_taskgen_fixes.py -- fixes for the tasks the 2026-10-06 audit found bad
from taskgen_v2 import fixes


def test_next_id_follows_every_candidate_of_the_tree():
    ids = ["bird:movie:actor:913:0", "bird:movie:actor:913:1", "bird:movie:actor:91:0"]
    assert fixes.next_id("bird:movie:actor:913:0", ids) == "bird:movie:actor:913:2"
    assert fixes.next_id("bird:movie:actor:91:0", ids) == "bird:movie:actor:91:1"


def test_substitute_replaces_whole_tokens_only():
    sql = "INSERT INTO characters (MovieID, ActorID) VALUES (742, 1321); -- not 17420"
    assert fixes.substitute(sql, {"742": "635"}) == "INSERT INTO characters (MovieID, ActorID) VALUES (635, 1321); -- not 17420"
    assert fixes.substitute("ticket '0005432461099' and 0005432461099.", {"0005432461099": "0005435999874"}) == \
        "ticket '0005435999874' and 0005435999874."


def test_listed_order_is_the_order_of_first_mention():
    assert fixes.listed_order("copy 105699, 105700, 102458 and later 105699 again", ["102458", "105699", "105700"]) == \
        ["105699", "105700", "102458"]
    assert fixes.listed_order("copy all of them", ["2", "1"]) == ["2", "1"]
