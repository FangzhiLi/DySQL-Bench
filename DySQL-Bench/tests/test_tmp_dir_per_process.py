import os, glob, importlib, shutil

ENVS = sorted(os.path.basename(os.path.dirname(os.path.dirname(p)))
              for p in glob.glob(os.path.join(os.path.dirname(__file__), "..", "dysql_bench", "envs", "*", "data", "__init__.py")))


def test_all_13_envs_have_loader():
    assert len(ENVS) == 13


def test_tmp_folder_includes_pid():
    """Two run.py processes may share a threading.get_ident() value; the sqlite scratch dir must be keyed by pid too."""
    for env in ENVS:
        mod = importlib.import_module(f"dysql_bench.envs.{env}.data")
        conn, cur, folder = mod.load_sql_data(4242)
        try:
            assert os.path.basename(folder) == f"thread_{os.getpid()}_4242", (env, folder)
        finally:
            conn.close()
            shutil.rmtree(folder)
