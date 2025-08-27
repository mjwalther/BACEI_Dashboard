"""
Tiny runner for CI: sets DASHBOARD_BUILD=1 and imports app.py.
Your app.py (with the patch I provided) will detect this env var,
precompute data, write to docs/data_build, then exit.
"""
import os
os.environ.setdefault("DASHBOARD_BUILD", "1")

# If your app expects env vars (like BLS_API_KEY), ensure they are set in repo secrets
# and exported in the workflow before this import runs.

import app  # noqa: F401
print("✅ build_artifacts.py finished (app.py ran in build mode).")
