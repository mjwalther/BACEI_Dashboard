"""
Tiny runner for CI: sets DASHBOARD_BUILD=1 and imports app.py.
app.py will detect this env var, precompute data, write to docs/data_build, then exit.
"""
import sys, os
os.environ.setdefault("DASHBOARD_BUILD", "1")
sys.path.append(os.path.dirname(os.path.dirname(__file__)))  # add repo root to path

import app  # noqa: F401
print("build_artifacts.py finished (app.py ran in build mode).")
