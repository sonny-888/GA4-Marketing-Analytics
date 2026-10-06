"""Rebuild everything from the downloaded GA4 data, in order, stopping at the first failure.

    python python/scripts/run_all.py                 # everything
    python python/scripts/run_all.py --skip-r        # Python side only (no R installed)
    python python/scripts/run_all.py --skip-notebooks

Downloading the raw data is a separate step because it needs a Google sign-in:
see notebooks/01_ga4_extract.ipynb.

The marketing mix model reuses its cached fit (data/mmm/); set MMM_REFIT=1 to retrain (about 50 minutes).
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def rscript() -> str:
    found = os.environ.get("RSCRIPT") or shutil.which("Rscript")
    if not found:
        found = next(iter(sorted(glob.glob(r"C:\Program Files\R\R-*\bin\Rscript.exe"), reverse=True)), None)
    if not found:
        sys.exit("Rscript not found. Install R, set RSCRIPT, or run with --skip-r.")
    return found


def run(label: str, args: list[str], cwd: Path = ROOT) -> None:
    print(f"\n==> {label}", flush=True)
    start = time.time()
    subprocess.run(args, cwd=cwd, check=True)  # list arguments, no shell
    print(f"    done in {time.time() - start:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-r", action="store_true", help="skip the R analyses and R tests")
    ap.add_argument("--skip-notebooks", action="store_true", help="skip re-running the Python notebooks")
    args = ap.parse_args()

    if not list((ROOT / "data" / "raw" / "ga4").glob("*/events.parquet")):
        sys.exit("No GA4 data in data/raw/ga4/. Download it first with notebooks/01_ga4_extract.ipynb.")

    run("Python unit tests", [PY, "-m", "pytest", "-q"])
    dbt = shutil.which("dbt", path=str(Path(PY).parent)) or sys.exit("dbt not found next to this Python.")
    run("dbt: build models and run data tests", [dbt, "build", "--profiles-dir", "."], cwd=ROOT / "sql")
    run("Export tables for Power BI", [PY, "python/scripts/export_powerbi.py"])
    run("Generate and validate the Power BI projects", [PY, "dashboard/build_pbip.py", "--validate"])

    if not args.skip_notebooks:
        for nb in ("02_attribution.ipynb", "03_customers.ipynb", "04_eda.ipynb"):
            run(f"Notebook {nb}", [PY, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace", nb],
                cwd=ROOT / "notebooks")

    if not args.skip_r:
        r = rscript()
        run("R unit tests", [r, "-e", "testthat::test_dir('r/tests', stop_on_failure = TRUE)"])
        for script in ("trends.R", "ab_test.R", "forecast.R", "mmm.R"):
            run(f"R: {script}", [r, f"r/{script}"])

    run("Headline numbers", [PY, "python/scripts/headline_facts.py"])
    print("\nAll steps finished.")


if __name__ == "__main__":
    main()
