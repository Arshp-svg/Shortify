"""Automated benchmark execution and metrics harvesting harness for Shortify.

Executes headless Locust scenarios, captures raw statistics (RPS, p50, p95, p99, max latency,
error rates), records system resource usage and PostgreSQL connection counts, and writes
both raw CSVs and structured JSON benchmark records.
"""

import argparse
import csv
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def get_git_commit() -> str:
    """Retrieve current Git commit SHA."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def get_postgres_active_connections() -> int:
    """Query active connections from PostgreSQL via docker compose."""
    try:
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
            "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return int(res.stdout.strip())
    except Exception:
        return -1


def parse_locust_stats_csv(csv_path: Path) -> dict[str, float]:
    """Parse aggregated statistics from Locust generated CSV."""
    if not csv_path.exists():
        return {}

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Name") == "Aggregated":
                req_count = float(row.get("Request Count", 0) or 0)
                fail_count = float(row.get("Failure Count", 0) or 0)
                rps = float(row.get("Requests/s", 0) or 0)
                p50 = float(row.get("50%", 0) or 0)
                p95 = float(row.get("95%", 0) or 0)
                p99 = float(row.get("99%", 0) or 0)
                avg_latency = float(row.get("Average Response Time", 0) or 0)
                error_rate = (fail_count / req_count * 100) if req_count > 0 else 0.0

                return {
                    "total_requests": req_count,
                    "failed_requests": fail_count,
                    "rps": round(rps, 2),
                    "p50_ms": p50,
                    "p95_ms": p95,
                    "p99_ms": p99,
                    "avg_latency_ms": round(avg_latency, 2),
                    "error_rate_pct": round(error_rate, 4),
                }
    return {}


def get_locust_executable() -> str:
    """Find locust executable inside active Python venv or system PATH."""
    venv_locust = Path(sys.executable).parent / (
        "locust.exe" if platform.system() == "Windows" else "locust"
    )
    if venv_locust.exists():
        return str(venv_locust)
    found = shutil.which("locust")
    return found if found else "locust"


def run_benchmark(
    scenario: str,
    user_class: str,
    users: int,
    spawn_rate: int,
    duration_secs: int,
    output_dir: Path,
    host: str = "http://localhost:8000",
) -> dict[str, object]:
    """Execute a single load testing scenario and produce a benchmark record."""
    timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    benchmark_id = f"BM_{scenario.upper()}_{timestamp_str}"
    csv_prefix = output_dir / f"locust_{scenario}_{timestamp_str}"

    print(f"\n{'=' * 70}")
    print(f"[*] Starting Benchmark: {benchmark_id}")
    print(f"    Scenario: {scenario} ({user_class}) | Users: {users} | Duration: {duration_secs}s")
    print(f"{'=' * 70}")

    locust_exe = get_locust_executable()
    locust_cmd = [
        locust_exe,
        "-f",
        "load_tests/locustfile.py",
        "--headless",
        "--host",
        host,
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "--run-time",
        f"{duration_secs}s",
        "--csv",
        str(csv_prefix),
        "--only-summary",
        user_class,
    ]

    start_conns = get_postgres_active_connections()
    start_time = time.perf_counter()

    proc = subprocess.run(locust_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"[!] Warning: Locust exited with code {proc.returncode}")
        print(proc.stderr[:500])

    elapsed = time.perf_counter() - start_time
    end_conns = get_postgres_active_connections()

    # Parse statistics from Locust CSV output
    stats_csv = output_dir / f"locust_{scenario}_{timestamp_str}_stats.csv"
    metrics = parse_locust_stats_csv(stats_csv)

    record: dict[str, object] = {
        "benchmark_id": benchmark_id,
        "git_commit": get_git_commit(),
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "scenario": scenario,
        "user_class": user_class,
        "concurrent_users": users,
        "spawn_rate": spawn_rate,
        "duration_seconds": duration_secs,
        "actual_elapsed_seconds": round(elapsed, 2),
        "host": host,
        "environment": {
            "os": f"{platform.system()} {platform.release()}",
            "processor": platform.processor(),
            "cpu_cores": os.cpu_count(),
            "python_version": platform.python_version(),
        },
        "database_metrics": {
            "start_active_connections": start_conns,
            "end_active_connections": end_conns,
        },
        "results": metrics,
    }

    record_path = output_dir / f"{benchmark_id}.json"
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    print(
        f"[OK] Completed {scenario} | RPS: {metrics.get('rps')} | p50: {metrics.get('p50_ms')}ms | p95: {metrics.get('p95_ms')}ms | p99: {metrics.get('p99_ms')}ms | Errors: {metrics.get('error_rate_pct')}%"
    )
    print(f"     Artifact saved to: {record_path}")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Shortify Benchmark Harness")
    parser.add_argument(
        "--scenario",
        choices=["all", "redirect", "create", "mixed", "invalid"],
        default="all",
        help="Benchmark scenario to run",
    )
    parser.add_argument("--users", type=int, default=50, help="Concurrent users")
    parser.add_argument("--spawn-rate", type=int, default=10, help="Spawn rate (users/sec)")
    parser.add_argument("--duration", type=int, default=20, help="Duration in seconds per run")
    parser.add_argument("--warmup", type=int, default=5, help="Warmup duration in seconds")
    parser.add_argument("--host", default="http://localhost:8000", help="Target API host")
    parser.add_argument("--output-dir", default="benchmarks/baseline", help="Output directory")

    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scenarios = {
        "redirect": "RedirectHeavyUser",
        "create": "CreationHeavyUser",
        "mixed": "MixedWorkloadUser",
        "invalid": "InvalidTrafficUser",
    }

    # Execute Warmup run
    if args.warmup > 0:
        print(f"[*] Executing {args.warmup}s warmup phase to prime connections...")
        run_benchmark(
            scenario="warmup",
            user_class="RedirectHeavyUser",
            users=10,
            spawn_rate=10,
            duration_secs=args.warmup,
            output_dir=out_dir,
            host=args.host,
        )

    targets = (
        ["redirect", "create", "mixed", "invalid"] if args.scenario == "all" else [args.scenario]
    )

    all_results = []
    for scn in targets:
        user_cls = scenarios[scn]
        res = run_benchmark(
            scenario=scn,
            user_class=user_cls,
            users=args.users,
            spawn_rate=args.spawn_rate,
            duration_secs=args.duration,
            output_dir=out_dir,
            host=args.host,
        )
        all_results.append(res)
        time.sleep(2)  # Cooldown between workloads

    summary_file = out_dir / "latest_benchmark_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n[OK] All benchmark scenarios completed. Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
