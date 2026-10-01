# taskgen/common/conftest.py -- the tests import taskgen_common from this folder without installing it
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
