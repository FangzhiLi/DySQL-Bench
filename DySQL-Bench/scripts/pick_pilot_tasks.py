#!/usr/bin/env python3
"""Pick 3 short + 2 long tasks for the pilot. Prints space-separated task ids."""
import argparse, importlib
from dysql_bench.analysis import classify_task

p = argparse.ArgumentParser()
p.add_argument("--env", default="pagila")
p.add_argument("--short", type=int, default=3)
p.add_argument("--long", type=int, default=2)
a = p.parse_args()
tasks = importlib.import_module(f"dysql_bench.envs.{a.env}.tasks_test").TASKS_TEST
short = [i for i, t in enumerate(tasks) if classify_task(t)["length"] == "short"]
long_ = [i for i, t in enumerate(tasks) if classify_task(t)["length"] == "long"]
print(" ".join(map(str, short[: a.short] + long_[: a.long])))
