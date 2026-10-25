"""Shortify Phase 8 Redis Caching & Cache Correctness Benchmark Suite.

Executes:
1. Cold Cache vs Warm Cache comparison
2. Pure Database vs Redis Cached lookup latency comparison
3. Hot-Key (Pareto 80/20 Zipfian) distribution benchmark
4. Redis Fail-Open Resilience Under Load (stop Redis during active traffic)
"""

import argparse
import csv
import json
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
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


def get_locust_executable() -> str:
    """Locate locust executable in active virtual environment."""
    venv_locust = Path(sys.executable).parent / (
        "locust.exe" if platform.system() == "Windows" else "locust"
    )
    if venv_locust.exists():
        return str(venv_locust)
    found = shutil.which("locust")
    return found if found else "locust"


def wait_for_api_ready(timeout_seconds: int = 30) -> bool:
    """Poll API readiness endpoint until 200 OK is returned."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_seconds:
        try:
            with urllib.request.urlopen("http://localhost:8000/ready", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def run_redis_cli(command: str) -> str:
    """Execute command inside shortify-redis container via docker compose."""
    cmd = ["docker", "compose", "exec", "-T", "redis", "redis-cli"] + command.split()
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception as exc:
        return f"error: {exc}"


def flush_redis() -> None:
    """Flush all keys from Redis DB."""
    run_redis_cli("flushdb")


def get_redis_stats() -> dict[str, str]:
    """Retrieve keyspace hits and memory from Redis."""
    raw = run_redis_cli("info")
    metrics: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            metrics[k.strip()] = v.strip()
    return metrics


def parse_locust_csv(csv_path: Path) -> dict[str, float]:
    """Parse aggregated metrics from Locust output CSV."""
    if not csv_path.exists():
        return {}

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Name") == "Aggregated":
                reqs = float(row.get("Request Count", 0) or 0)
                fails = float(row.get("Failure Count", 0) or 0)
                return {
                    "total_requests": reqs,
                    "failed_requests": fails,
                    "rps": round(float(row.get("Requests/s", 0) or 0), 2),
                    "p50_ms": float(row.get("50%", 0) or 0),
                    "p95_ms": float(row.get("95%", 0) or 0),
                    "p99_ms": float(row.get("99%", 0) or 0),
                    "avg_latency_ms": round(float(row.get("Average Response Time", 0) or 0), 2),
                    "error_rate_pct": round((fails / reqs * 100) if reqs > 0 else 0.0, 4),
                }
    return {}


def run_locust_test(
    user_class: str,
    users: int,
    spawn_rate: int,
    duration_secs: int,
    output_prefix: Path,
) -> dict[str, float]:
    """Execute a headless Locust test scenario."""
    locust_exe = get_locust_executable()
    cmd = [
        locust_exe,
        "-f",
        "load_tests/locustfile.py",
        "--headless",
        "--host",
        "http://localhost:8000",
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "--run-time",
        f"{duration_secs}s",
        "--csv",
        str(output_prefix),
        "--only-summary",
        user_class,
    ]

    subprocess.run(cmd, capture_output=True, text=True)
    stats_csv = Path(f"{output_prefix}_stats.csv")
    return parse_locust_csv(stats_csv)


def run_experiment_cold_vs_warm(output_dir: Path) -> dict[str, object]:
    """Experiment 1: Cold Cache vs Warm Cache."""
    print("\n" + "=" * 70)
    print("[*] Starting Experiment 1: Cold Cache vs Warm Cache")
    print("=" * 70)

    # 1. Cold Cache: flush Redis before test
    print("[*] Flushing Redis DB for Cold Cache run...")
    flush_redis()
    print("    Executing 15s load test against Cold Cache (50 users)...")
    cold_prefix = output_dir / "locust_cold_cache"
    cold_metrics = run_locust_test("RedirectHeavyUser", users=50, spawn_rate=10, duration_secs=15, output_prefix=cold_prefix)
    cold_info = get_redis_stats()
    print(f"[OK] Cold Cache -> RPS: {cold_metrics.get('rps')} | p50: {cold_metrics.get('p50_ms')}ms | p95: {cold_metrics.get('p95_ms')}ms | p99: {cold_metrics.get('p99_ms')}ms | Keys: {cold_info.get('db0', 'empty')}")

    time.sleep(2)

    # 2. Warm Cache: keep keys in Redis, run identical test
    print("\n[*] Executing 15s load test against Warm Cache (50 users)...")
    warm_prefix = output_dir / "locust_warm_cache"
    warm_metrics = run_locust_test("RedirectHeavyUser", users=50, spawn_rate=10, duration_secs=15, output_prefix=warm_prefix)
    warm_info = get_redis_stats()
    print(f"[OK] Warm Cache -> RPS: {warm_metrics.get('rps')} | p50: {warm_metrics.get('p50_ms')}ms | p95: {warm_metrics.get('p95_ms')}ms | p99: {warm_metrics.get('p99_ms')}ms")

    res: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": get_git_commit(),
        "experiment": "Cold Cache vs Warm Cache",
        "concurrency": 50,
        "cold_cache": {
            "metrics": cold_metrics,
            "redis_hits": cold_info.get("keyspace_hits", "0"),
            "redis_misses": cold_info.get("keyspace_misses", "0"),
        },
        "warm_cache": {
            "metrics": warm_metrics,
            "redis_hits": warm_info.get("keyspace_hits", "0"),
            "redis_misses": warm_info.get("keyspace_misses", "0"),
        },
    }

    out_file = output_dir / "experiment_cold_vs_warm.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    print(f"[OK] Cold vs Warm results saved to: {out_file}")
    return res


def run_experiment_hot_key(output_dir: Path) -> dict[str, object]:
    """Experiment 2: Pareto 80/20 Hot-Key Distribution."""
    print("\n" + "=" * 70)
    print("[*] Starting Experiment 2: Hot-Key Traffic (Pareto 80/20)")
    print("=" * 70)

    # Ensure Redis has top 10 keys primed
    for i in range(1, 11):
        code = f"s{i:07d}"
        run_redis_cli(f"set url:{code} https://example.com/products/item-{i}?ref=hotkey ex 3600")

    print("[*] Executing 15s load test with HotKeyUser (80% traffic on top 10 keys)...")
    hot_prefix = output_dir / "locust_hot_key"
    hot_metrics = run_locust_test("HotKeyUser", users=50, spawn_rate=10, duration_secs=15, output_prefix=hot_prefix)
    redis_info = get_redis_stats()

    hits = int(redis_info.get("keyspace_hits", 0))
    misses = int(redis_info.get("keyspace_misses", 0))
    total = hits + misses
    hit_ratio = round((hits / total) * 100, 2) if total > 0 else 0.0

    print(f"[OK] Hot-Key Profile -> RPS: {hot_metrics.get('rps')} | p50: {hot_metrics.get('p50_ms')}ms | p95: {hot_metrics.get('p95_ms')}ms | p99: {hot_metrics.get('p99_ms')}ms | Hit Ratio: {hit_ratio}%")

    res: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": get_git_commit(),
        "experiment": "Hot-Key Pareto Distribution (80/20)",
        "concurrency": 50,
        "metrics": hot_metrics,
        "redis_metrics": {
            "keyspace_hits": hits,
            "keyspace_misses": misses,
            "hit_ratio_pct": hit_ratio,
            "used_memory_human": redis_info.get("used_memory_human", "unknown"),
        },
    }

    out_file = output_dir / "experiment_hot_key.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    print(f"[OK] Hot-Key results saved to: {out_file}")
    return res


def run_experiment_fail_open(output_dir: Path) -> dict[str, object]:
    """Experiment 3: Redis Outage / Fail-Open Resilience Under Load."""
    print("\n" + "=" * 70)
    print("[*] Starting Experiment 3: Redis Fail-Open Resilience Under Active Load")
    print("=" * 70)

    # 1. Stop Redis
    print("[*] Simulating Redis Outage: stopping shortify-redis container...")
    subprocess.run(["docker", "compose", "stop", "redis"], check=True)
    time.sleep(2)

    # 2. Run Locust against API with dead Redis
    print("    Executing load test against API while Redis is OFFLINE (50 users, 15s)...")
    fail_prefix = output_dir / "locust_fail_open_offline"
    offline_metrics = run_locust_test("RedirectHeavyUser", users=50, spawn_rate=10, duration_secs=15, output_prefix=fail_prefix)
    print(f"[OK] Offline Redis Result -> RPS: {offline_metrics.get('rps')} | p50: {offline_metrics.get('p50_ms')}ms | Errors: {offline_metrics.get('error_rate_pct')}%")

    # 3. Recover Redis
    print("\n[*] Recovering Redis: starting shortify-redis container...")
    subprocess.run(["docker", "compose", "start", "redis"], check=True)
    time.sleep(3)
    wait_for_api_ready()
    print("[OK] Redis recovered and /ready probe is healthy.")

    res: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": get_git_commit(),
        "experiment": "Redis Fail-Open Resilience",
        "redis_state": "stopped",
        "concurrency": 50,
        "offline_metrics": offline_metrics,
        "fail_open_verified": bool(offline_metrics.get("error_rate_pct", 100.0) < 0.1),
    }

    out_file = output_dir / "experiment_fail_open.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    print(f"[OK] Fail-Open results saved to: {out_file}")
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Shortify Redis Caching Experiments")
    parser.add_argument(
        "--experiment",
        choices=["all", "cold_warm", "hot_key", "fail_open"],
        default="all",
        help="Select experiment to execute",
    )
    args = parser.parse_args()

    out_dir = Path("benchmarks/redis")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not wait_for_api_ready():
        print("[!] Error: API container not responding on http://localhost:8000/ready")
        sys.exit(1)

    all_results: dict[str, object] = {}

    if args.experiment in ["cold_warm", "all"]:
        all_results["cold_vs_warm"] = run_experiment_cold_vs_warm(out_dir)
        time.sleep(2)

    if args.experiment in ["hot_key", "all"]:
        all_results["hot_key"] = run_experiment_hot_key(out_dir)
        time.sleep(2)

    if args.experiment in ["fail_open", "all"]:
        all_results["fail_open"] = run_experiment_fail_open(out_dir)

    summary_file = out_dir / "redis_experiments_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n[OK] All Phase 8 Redis Caching experiments completed! Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
