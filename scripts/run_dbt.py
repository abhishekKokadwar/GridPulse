"""
GridPulse Medallion Lakehouse Runner (dbt + DuckDB)
Executes automated ELT transformations across Bronze, Silver, and Gold layers
with full data contract test enforcement.
"""

import argparse
import os
import sys
import time
from typing import Dict, Any, List

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DBT_PROJECT_DIR = os.path.join(PROJECT_ROOT, "dbt_lakehouse")
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "lakehouse", "gridpulse_medallion.duckdb")
RAW_LAKE_PATH = os.path.join(PROJECT_ROOT, "data", "lake", "raw_telemetry")


def ensure_directories():
    """Ensure lakehouse output directories exist."""
    os.makedirs(os.path.dirname(DEFAULT_DB_PATH), exist_ok=True)


def invoke_dbt(command_args: List[str], project_dir: str = DBT_PROJECT_DIR) -> bool:
    """
    Invokes dbt commands programmatically using dbtRunner.
    """
    from dbt.cli.main import dbtRunner, dbtRunnerResult

    # Normalize paths for Windows/DuckDB
    db_path_norm = DEFAULT_DB_PATH.replace("\\", "/")
    os.environ["DUCKDB_DATABASE_PATH"] = db_path_norm

    raw_glob = os.path.join(RAW_LAKE_PATH, "**", "*.parquet").replace("\\", "/")

    cli_args = [
        *command_args,
        "--project-dir", project_dir,
        "--profiles-dir", project_dir,
        "--vars", f'{{"raw_telemetry_glob": "{raw_glob}"}}',
    ]

    print(f"\n[DBT RUNNER] Executing: dbt {' '.join(command_args)}")
    runner = dbtRunner()
    res: dbtRunnerResult = runner.invoke(cli_args)

    # Release DuckDB file locks held by the adapter
    try:
        from dbt.adapters.factory import reset_adapters
        reset_adapters()
    except Exception:
        pass

    if not res.success:
        print(f"[DBT RUNNER ERROR] Command failed: {' '.join(command_args)}")
        if res.exception:
            print(f"[EXCEPTION] {res.exception}")
        return False
    return True


def run_pipeline(
    do_seed: bool = True,
    do_run: bool = True,
    do_test: bool = True,
    do_docs: bool = False,
    project_dir: str = DBT_PROJECT_DIR,
) -> Dict[str, Any]:
    """
    Runs the full Medallion Lakehouse ELT workflow.
    """
    ensure_directories()
    t0 = time.time()
    results = {
        "seed": None,
        "run": None,
        "test": None,
        "docs": None,
        "success": True,
        "duration_sec": 0.0,
    }

    if do_seed:
        ok = invoke_dbt(["seed"], project_dir)
        results["seed"] = ok
        if not ok:
            results["success"] = False
            return results

    if do_run:
        ok = invoke_dbt(["run"], project_dir)
        results["run"] = ok
        if not ok:
            results["success"] = False
            return results

    if do_test:
        ok = invoke_dbt(["test"], project_dir)
        results["test"] = ok
        if not ok:
            results["success"] = False
            return results

    if do_docs:
        ok = invoke_dbt(["docs", "generate"], project_dir)
        results["docs"] = ok

    results["duration_sec"] = round(time.time() - t0, 2)
    print(f"\n[DBT RUNNER SUCCESS] Pipeline completed in {results['duration_sec']}s (Success: {results['success']})")
    return results


def main():
    parser = argparse.ArgumentParser(description="GridPulse dbt-duckdb Medallion Lakehouse Runner")
    parser.add_argument("--seed", action="store_true", help="Execute dbt seed")
    parser.add_argument("--run", action="store_true", help="Execute dbt run")
    parser.add_argument("--test", action="store_true", help="Execute dbt test")
    parser.add_argument("--docs", action="store_true", help="Execute dbt docs generate")
    parser.add_argument("--all", action="store_true", help="Execute seed + run + test")

    args = parser.parse_args()

    # If no flags passed or --all specified, execute full seed + run + test pipeline
    if args.all or not (args.seed or args.run or args.test or args.docs):
        res = run_pipeline(do_seed=True, do_run=True, do_test=True, do_docs=args.docs)
    else:
        res = run_pipeline(
            do_seed=args.seed,
            do_run=args.run,
            do_test=args.test,
            do_docs=args.docs,
        )

    sys.exit(0 if res["success"] else 1)


if __name__ == "__main__":
    main()
