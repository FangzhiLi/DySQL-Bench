# taskgen/v2/conftest.py -- the tests import taskgen_v2 (this folder) and taskgen_common (../common) without installing them
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "common")]
