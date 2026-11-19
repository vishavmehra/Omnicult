"""Runs the reference-data seeds in order. This is the command of the omnicult-seed Cloud Run job (ops/deploy/migrate.ps1).

Each seed is idempotent. A seed module that is not part of this image is reported and skipped, so the job works on any
build; a seed that exists and fails stops the job with its exit code.
    python -m scripts.seed_all
"""

import importlib.util
import subprocess
import sys

SEEDS = ("scripts.seed_reference_data", "scripts.seed_demo_claims", "scripts.seed_state_facts")  # demo claims need the reference regions first

for module in SEEDS:
    if importlib.util.find_spec(module) is None:
        print(f"{module}: not in this image, skipped", file=sys.stderr)
        continue
    print(f"running {module}", flush=True)
    subprocess.run([sys.executable, "-m", module], check=True)
