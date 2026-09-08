"""
GridPulse Data Lakehouse Compaction Engine (Phase 5)
Coalesces high-frequency streaming micro-batch Parquet files into
consolidated columnar files to eliminate the small-file problem.
"""

import argparse
import os
import sys
import time
from typing import Dict, Any, List
import pyarrow as pa
import pyarrow.parquet as pq

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_LAKE_PATH = os.path.join(PROJECT_ROOT, "data", "lake", "raw_telemetry")


def compact_partition_dir(partition_dir: str) -> Dict[str, Any]:
    """
    Compacts multiple Parquet files within a single partition directory
    into a single consolidated Snappy Parquet file.
    """
    parquet_files = [
        os.path.join(partition_dir, f)
        for f in os.listdir(partition_dir)
        if f.endswith(".parquet") and not f.startswith("compacted_")
    ]

    # If there's 0 or only 1 non-compacted file, no compaction needed
    if len(parquet_files) <= 1:
        # Check if already compacted
        all_parquet = [f for f in os.listdir(partition_dir) if f.endswith(".parquet")]
        return {
            "partition": os.path.basename(partition_dir),
            "status": "SKIPPED",
            "files_before": len(all_parquet),
            "files_after": len(all_parquet),
            "bytes_before": sum(os.path.getsize(os.path.join(partition_dir, f)) for f in all_parquet),
            "bytes_after": sum(os.path.getsize(os.path.join(partition_dir, f)) for f in all_parquet),
        }

    bytes_before = sum(os.path.getsize(f) for f in parquet_files)
    files_before = len(parquet_files)

    # Read all files in partition
    tables = [pq.read_table(f) for f in parquet_files]
    combined_table = pa.concat_tables(tables)

    temp_compacted_path = os.path.join(partition_dir, "temp_compacted.parquet")
    final_compacted_path = os.path.join(partition_dir, f"compacted_part_{int(time.time())}.snappy.parquet")

    # Write combined table
    pq.write_table(
        combined_table,
        temp_compacted_path,
        compression="snappy",
        use_dictionary=True,
    )

    # Safe removal of fragmented part files
    for old_file in parquet_files:
        try:
            os.remove(old_file)
        except Exception as e:
            print(f"[COMPACTION WARNING] Could not remove old file {old_file}: {e}")

    # Rename temp to final
    if os.path.exists(final_compacted_path):
        os.remove(final_compacted_path)
    os.rename(temp_compacted_path, final_compacted_path)

    bytes_after = os.path.getsize(final_compacted_path)

    return {
        "partition": os.path.basename(partition_dir),
        "status": "COMPACTED",
        "files_before": files_before,
        "files_after": 1,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
        "saved_bytes": bytes_before - bytes_after,
    }


def run_compaction(lake_path: str = DEFAULT_LAKE_PATH, min_files: int = 2) -> Dict[str, Any]:
    """
    Scans all leaf partition directories in the data lake and triggers compaction.
    Returns overall compaction report.
    """
    if not os.path.exists(lake_path):
        return {"status": "ERROR", "message": f"Lake path does not exist: {lake_path}"}

    t0 = time.time()
    results = []
    partitions_checked = 0
    partitions_compacted = 0
    total_files_before = 0
    total_files_after = 0
    total_bytes_saved = 0

    # Walk through directory tree to find leaf directories with parquet files
    for root, dirs, files in os.walk(lake_path):
        parquet_files = [f for f in files if f.endswith(".parquet")]
        if parquet_files:
            partitions_checked += 1
            if len(parquet_files) >= min_files:
                res = compact_partition_dir(root)
                results.append(res)
                if res["status"] == "COMPACTED":
                    partitions_compacted += 1
                    total_files_before += res["files_before"]
                    total_files_after += res["files_after"]
                    total_bytes_saved += res.get("saved_bytes", 0)

    elapsed_ms = round((time.time() - t0) * 1000, 2)
    return {
        "status": "SUCCESS",
        "partitions_checked": partitions_checked,
        "partitions_compacted": partitions_compacted,
        "total_files_before": total_files_before,
        "total_files_after": total_files_after,
        "total_bytes_saved": total_bytes_saved,
        "elapsed_ms": elapsed_ms,
        "details": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GridPulse Phase 5: Parquet Micro-Batch Compaction Engine")
    parser.add_argument("--lake-path", type=str, default=DEFAULT_LAKE_PATH, help="Root path of the data lake")
    parser.add_argument("--min-files", type=int, default=2, help="Minimum files in partition to trigger compaction")

    args = parser.parse_args()

    print(f"\n[LAKE COMPACTOR] Starting compaction on: '{args.lake_path}' ...")
    summary = run_compaction(lake_path=args.lake_path, min_files=args.min_files)
    print(f"[LAKE COMPACTOR] Finished in {summary['elapsed_ms']} ms.")
    print(f"  * Partitions checked: {summary['partitions_checked']}")
    print(f"  * Partitions compacted: {summary['partitions_compacted']}")
    print(f"  * Files reduced: {summary['total_files_before']} -> {summary['total_files_after']}")
    if summary["details"]:
        print("  * Results per partition:")
        for r in summary["details"]:
            print(f"    - {r['partition']}: {r['status']} ({r.get('files_before', 0)} files -> {r.get('files_after', 0)})")
