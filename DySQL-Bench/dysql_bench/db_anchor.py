"""Anchors and update targets: the structure a DySQL-style task needs.
A task is anchored on a row (a person, or an entity such as a car or a recipe) and writes rows in the anchor's
scope: the anchor, the tables below it (<= 2 FK hops) and their parent tables.
Evidence: docs/data_gen/dysql_task_types.md. This module must not import db_select (db_select imports it)."""
import re

PERSON = re.compile(r"customer|client|employee|staff|member|player|user|student|patient|person|people|"
                    r"author|driver|agent|bowler|entertainer|actor|athlete|teacher|faculty|professor|"
                    r"instructor|doctor|physician|nurse|cyclist|voter|owner|guest|visitor|passenger|"
                    r"seller|buyer|investor|pilot|legislator|contact|coach|manager|artist|singer|"
                    r"wrestler|reviewer|donor|officer|swimmer|gymnast|scientist|musician|editor|journalist|candidate")
NAME_COLS = {"firstname", "lastname", "fname", "lname", "fullname", "first", "last",
             "surname", "givenname", "familyname", "forename"}
GUID = re.compile(r"guid|uuid", re.I)
