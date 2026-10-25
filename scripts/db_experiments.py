"""Shortify Database Performance Engineering Experiments Harness (Phase 7).

Implements:
- Experiment A: Dataset Size Scaling (10k, 100k, 1M) with EXPLAIN (ANALYZE, BUFFERS)
- Experiment B: Indexing vs Non-Indexing Deep Dive (Index Scan vs Seq Scan, buffer hits, write penalty)
- Experiment C: Connection Pool Size Tuning (5, 20, 50, 100) under concurrent load
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def run_psql_command(query: str) -> str:
    """Execute a SQL command inside the PostgreSQL container and return raw stdout."""
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        "shortify",
        "-t",
        "-A",
        "-c",
        query,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def run_explain_analyze(query: str, enable_index: bool = True) -> tuple[float, str]:
    """Execute EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) and return (execution_time_ms, raw_plan)."""
    prefix = "" if enable_index else "SET enable_indexscan = off; SET enable_bitmapscan = off; "
    sql = f"{prefix}EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query};"
    output = run_psql_command(sql)

    # Parse JSON output from psql
    # Output may contain SET notices if prefix was used
    json_start = output.find("[")
    if json_start == -1:
        raise ValueError(f"Could not find JSON in EXPLAIN output: {output}")

    json_str = output[json_start:]
    plan_data = json.loads(json_str)
    exec_time = float(plan_data[0]["Execution Time"])
    return exec_time, json.dumps(plan_data, indent=2)


def get_relation_sizes(table_name: str = "urls") -> dict[str, str]:
    """Query table, indexes, and total sizes for a given table."""
    sql = f"""
    SELECT
        pg_size_pretty(pg_relation_size('{table_name}')) AS table_size,
        pg_size_pretty(pg_indexes_size('{table_name}')) AS indexes_size,
        pg_size_pretty(pg_total_relation_size('{table_name}')) AS total_size,
        count(*) AS row_count
    FROM {table_name};
    """
    output = run_psql_command(sql)
    return {"raw_output": output}


def run_experiment_b(output_dir: Path) -> dict[str, object]:
    """Experiment B: Detailed Indexing vs Non-Indexing Analysis."""
    print("\n" + "=" * 70)
    print("[*] Starting Experiment B: Indexing vs Non-Indexing Analysis")
    print("=" * 70)

    target_code = "s0042424"
    test_query = f"SELECT * FROM urls WHERE short_code = '{target_code}'"

    # 1. With Index Scan
    idx_time, idx_plan = run_explain_analyze(test_query, enable_index=True)
    print(f"[OK] Indexed Lookup (B-Tree): {idx_time:.4f} ms")

    # 2. Sequential Scan (Without Index)
    seq_time, seq_plan = run_explain_analyze(test_query, enable_index=False)
    print(f"[OK] Non-Indexed Lookup (Seq Scan): {seq_time:.4f} ms")

    speedup = seq_time / idx_time if idx_time > 0 else 0.0
    print(f"[OK] Index Scan Speedup: {speedup:.2f}x faster")

    # 3. Update query analysis
    update_query = "UPDATE urls SET click_count = click_count + 1 WHERE id = 42424"
    upd_time, upd_plan = run_explain_analyze(update_query, enable_index=True)
    print(f"[OK] Atomic Click Update: {upd_time:.4f} ms")

    results = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "experiment": "Experiment B: Indexing vs Non-Indexing",
        "target_code": target_code,
        "indexed_execution_time_ms": round(idx_time, 4),
        "sequential_execution_time_ms": round(seq_time, 4),
        "speedup_factor": round(speedup, 2),
        "update_execution_time_ms": round(upd_time, 4),
        "plans": {
            "indexed_plan": json.loads(idx_plan),
            "sequential_plan": json.loads(seq_plan),
            "update_plan": json.loads(upd_plan),
        },
    }

    out_file = output_dir / "experiment_b_indexing_deep_dive.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"[OK] Experiment B artifacts saved to: {out_file}")
    return results


def run_experiment_a(output_dir: Path) -> dict[str, object]:
    """Experiment A: Dataset Size Scaling (10k, 100k, 1M)."""
    print("\n" + "=" * 70)
    print("[*] Starting Experiment A: Dataset Size Scaling (10k, 100k, 1M)")
    print("=" * 70)

    scaling_results = []

    # --- Scale 1: 10,000 rows ---
    print("\n[*] Evaluating dataset scale: 10,000 URLs...")
    run_psql_command("DROP TABLE IF EXISTS urls_10k CASCADE;")
    run_psql_command("CREATE TABLE urls_10k AS SELECT * FROM urls LIMIT 10000;")
    run_psql_command("CREATE UNIQUE INDEX ix_urls_10k_short_code ON urls_10k (short_code);")
    run_psql_command("ANALYZE urls_10k;")

    size_10k = run_psql_command("""
    SELECT
        pg_size_pretty(pg_relation_size('urls_10k')) AS table_size,
        pg_size_pretty(pg_indexes_size('urls_10k')) AS indexes_size,
        pg_size_pretty(pg_total_relation_size('urls_10k')) AS total_size;
    """)
    print(f"    10k Storage Footprint:\n{size_10k}")

    query_10k = "SELECT * FROM urls_10k WHERE short_code = 's0005000'"
    idx_10k, _ = run_explain_analyze(query_10k, enable_index=True)
    seq_10k, _ = run_explain_analyze(query_10k, enable_index=False)
    print(f"    [10k Scale] Index Scan: {idx_10k:.4f} ms | Seq Scan: {seq_10k:.4f} ms")
    scaling_results.append(
        {
            "scale_rows": 10_000,
            "table_name": "urls_10k",
            "index_scan_ms": round(idx_10k, 4),
            "seq_scan_ms": round(seq_10k, 4),
            "speedup": round(seq_10k / idx_10k, 2) if idx_10k > 0 else 0.0,
            "size_metrics": size_10k,
        }
    )
    run_psql_command("DROP TABLE urls_10k;")

    # --- Scale 2: 100,000 rows ---
    print("\n[*] Evaluating dataset scale: 100,000 URLs...")
    run_psql_command("ANALYZE urls;")
    size_100k = run_psql_command("""
    SELECT
        pg_size_pretty(pg_relation_size('urls')) AS table_size,
        pg_size_pretty(pg_indexes_size('urls')) AS indexes_size,
        pg_size_pretty(pg_total_relation_size('urls')) AS total_size;
    """)
    print(f"    100k Storage Footprint:\n{size_100k}")
    query_100k = "SELECT * FROM urls WHERE short_code = 's0050000'"
    idx_100k, _ = run_explain_analyze(query_100k, enable_index=True)
    seq_100k, _ = run_explain_analyze(query_100k, enable_index=False)
    print(f"    [100k Scale] Index Scan: {idx_100k:.4f} ms | Seq Scan: {seq_100k:.4f} ms")
    scaling_results.append(
        {
            "scale_rows": 100_000,
            "table_name": "urls",
            "index_scan_ms": round(idx_100k, 4),
            "seq_scan_ms": round(seq_100k, 4),
            "speedup": round(seq_100k / idx_100k, 2) if idx_100k > 0 else 0.0,
            "size_metrics": size_100k,
        }
    )

    # --- Scale 3: 1,000,000 rows ---
    print("\n[*] Evaluating dataset scale: 1,000,000 URLs...")
    count_out = run_psql_command("SELECT count(*) FROM urls;")
    curr_count = int(count_out.splitlines()[-1].strip())
    print(f"    Current table row count: {curr_count:,}")

    if curr_count < 1_000_000:
        print("    Seeding dataset to 1,000,000 URLs (batch size: 25,000)...")
        seed_cmd = [
            sys.executable,
            "scripts/seed_urls.py",
            "--count",
            "1000000",
            "--batch-size",
            "25000",
        ]
        subprocess.run(seed_cmd, check=True)

    run_psql_command("ANALYZE urls;")
    size_1m = run_psql_command("""
    SELECT
        pg_size_pretty(pg_relation_size('urls')) AS table_size,
        pg_size_pretty(pg_indexes_size('urls')) AS indexes_size,
        pg_size_pretty(pg_total_relation_size('urls')) AS total_size;
    """)
    print(f"    1M Storage Footprint:\n{size_1m}")
    query_1m = "SELECT * FROM urls WHERE short_code = 's0500000'"
    idx_1m, _ = run_explain_analyze(query_1m, enable_index=True)
    seq_1m, _ = run_explain_analyze(query_1m, enable_index=False)
    print(f"    [1M Scale] Index Scan: {idx_1m:.4f} ms | Seq Scan: {seq_1m:.4f} ms")
    scaling_results.append(
        {
            "scale_rows": 1_000_000,
            "table_name": "urls",
            "index_scan_ms": round(idx_1m, 4),
            "seq_scan_ms": round(seq_1m, 4),
            "speedup": round(seq_1m / idx_1m, 2) if idx_1m > 0 else 0.0,
            "size_metrics": size_1m,
        }
    )

    record: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "experiment": "Experiment A: Dataset Size Scaling",
        "scales_evaluated": scaling_results,
    }

    out_file = output_dir / "experiment_a_dataset_scaling.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    print(f"\n[OK] Experiment A completed. Results saved to: {out_file}")
    return record


def run_experiment_c(output_dir: Path) -> dict[str, object]:
    """Experiment C: Connection Pool Size Tuning (5, 20, 50, 100)."""
    print("\n" + "=" * 70)
    print("[*] Starting Experiment C: Connection Pool Size Tuning")
    print("=" * 70)

    pool_configs = [
        {"pool_size": 5, "overflow": 0, "label": "Pool-5 (Constrained)"},
        {"pool_size": 20, "overflow": 10, "label": "Pool-20 (Baseline)"},
        {"pool_size": 50, "overflow": 10, "label": "Pool-50 (Right-Sized)"},
        {"pool_size": 100, "overflow": 20, "label": "Pool-100 (Oversized)"},
    ]

    results = []

    for cfg in pool_configs:
        p_size = cfg["pool_size"]
        ovf = cfg["overflow"]
        label = cfg["label"]

        print(
            f"\n[*] Applying Connection Pool Configuration: {label} (Size: {p_size}, Overflow: {ovf})"
        )

        # Set environment and recreate API container
        env = os.environ.copy()
        env["POSTGRES_POOL_SIZE"] = str(p_size)
        env["POSTGRES_MAX_OVERFLOW"] = str(ovf)

        up_cmd = ["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", "api"]
        subprocess.run(up_cmd, env=env, check=True)
        print("    Waiting for API container readiness probe...")
        ready = False
        import urllib.request

        for _ in range(30):
            try:
                with urllib.request.urlopen("http://localhost:8000/ready", timeout=2) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(1)
        if not ready:
            print("    [!] Warning: API container not ready after 30s")

        # Run Locust Redirect-Heavy Benchmark for 15s with 50 users
        csv_prefix = output_dir / f"locust_pool_{p_size}"
        locust_script = Path(sys.executable).parent / (
            "locust.exe" if platform.system() == "Windows" else "locust"
        )

        locust_cmd = [
            str(locust_script),
            "-f",
            "load_tests/locustfile.py",
            "--headless",
            "--host",
            "http://localhost:8000",
            "-u",
            "50",
            "-r",
            "10",
            "--run-time",
            "15s",
            "--csv",
            str(csv_prefix),
            "--only-summary",
            "RedirectHeavyUser",
        ]

        print("    Executing 15s load test with 50 concurrent users...")
        start_time = time.perf_counter()
        subprocess.run(locust_cmd, capture_output=True, text=True)
        time.perf_counter() - start_time

        # Parse results CSV
        import csv

        stats_csv = output_dir / f"locust_pool_{p_size}_stats.csv"
        metrics: dict[str, float] = {}
        if stats_csv.exists():
            with open(stats_csv, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Name") == "Aggregated":
                        reqs = float(row.get("Request Count", 0) or 0)
                        fails = float(row.get("Failure Count", 0) or 0)
                        metrics = {
                            "total_requests": reqs,
                            "failed_requests": fails,
                            "rps": round(float(row.get("Requests/s", 0) or 0), 2),
                            "p50_ms": float(row.get("50%", 0) or 0),
                            "p95_ms": float(row.get("95%", 0) or 0),
                            "p99_ms": float(row.get("99%", 0) or 0),
                            "avg_latency_ms": round(
                                float(row.get("Average Response Time", 0) or 0), 2
                            ),
                            "error_rate_pct": round((fails / reqs * 100) if reqs > 0 else 0.0, 4),
                        }

        print(
            f"    [OK] Pool-{p_size} -> RPS: {metrics.get('rps')} | p50: {metrics.get('p50_ms')}ms | p95: {metrics.get('p95_ms')}ms | p99: {metrics.get('p99_ms')}ms | Errors: {metrics.get('error_rate_pct')}%"
        )

        results.append(
            {
                "configuration": cfg,
                "metrics": metrics,
            }
        )
        time.sleep(2)

    # Restore default pool config
    os.environ.pop("POSTGRES_POOL_SIZE", None)
    os.environ.pop("POSTGRES_MAX_OVERFLOW", None)
    subprocess.run(
        ["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", "api"], check=True
    )

    summary = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "experiment": "Experiment C: Connection Pool Tuning",
        "concurrency": 50,
        "duration_seconds": 15,
        "results": results,
    }

    out_file = output_dir / "experiment_c_connection_pool.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[OK] Experiment C completed. Results saved to: {out_file}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Shortify Database Performance Engineering Harness"
    )
    parser.add_argument(
        "--experiment",
        choices=["all", "a", "b", "c"],
        default="all",
        help="Experiment to run: a (dataset scaling), b (indexing analysis), c (pool tuning), all",
    )
    args = parser.parse_args()

    base_dir = Path("benchmarks/database")
    dir_a = base_dir / "dataset_size"
    dir_b = base_dir / "indexing"
    dir_c = base_dir / "connection_pool"

    dir_a.mkdir(parents=True, exist_ok=True)
    dir_b.mkdir(parents=True, exist_ok=True)
    dir_c.mkdir(parents=True, exist_ok=True)

    if args.experiment in ["b", "all"]:
        run_experiment_b(dir_b)

    if args.experiment in ["a", "all"]:
        run_experiment_a(dir_a)

    if args.experiment in ["c", "all"]:
        run_experiment_c(dir_c)

    print("\n[OK] All requested database performance engineering experiments finished!")


if __name__ == "__main__":
    main()
