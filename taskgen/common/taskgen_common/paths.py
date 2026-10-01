"""Where the shared data-gen files and the DySQL-Bench package live in this checkout."""
import os

COMMON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # taskgen/common/
REPO = os.path.dirname(os.path.dirname(COMMON))                        # repo root (.env lives here)
DATA = os.path.join(COMMON, "data")                                    # candidate lists, anchors JSON, hand notes
RESULTS = os.path.join(COMMON, "results")                              # selector output, not in git
ANCHORS_JSON = os.path.join(DATA, "candidate_anchors.json")            # input of every version's tree builder
DYSQL_ENVS = os.path.join(REPO, "DySQL-Bench", "dysql_bench", "envs")  # the 13 DySQL envs: databases and gold tasks
