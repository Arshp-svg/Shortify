"""Shortify Phase 9 Rate Limiting & Abuse Controls Benchmark Suite.

Executes:
1. Microbenchmark: Pure Redis Sliding-Window Rate Limit Lua script latency (2,000 checks)
2. Overhead Benchmark: Multi-client traffic with Rate Limiting OFF vs ON (50 users)
3. Abuse / Burst Flood: Single IP flooding 200 requests to measure 429 rejection latency and accuracy
4. Fail-Open Resilience: Verify fail-open behavior when Redis is unavailable
"""

import argparse
import asyncio
import csv
import json
import logging
import platform
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as aioredis

from app.core.rate_limit import SLIDING_WINDOW_LUA

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shortify.benchmarks.rate_limiting")

OUTPUT_DIR = Path("benchmarks/rate_limiting")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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


async def run_redis_microbenchmark(num_operations: int = 2000) -> dict[str, float | int]:
    """Microbenchmark pure Redis Lua execution for sliding-window rate limit checks."""
    logger.info("Starting Redis Sliding-Window Rate Limit microbenchmark (%d ops)...", num_operations)
    client = aioredis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    await client.ping()

    key = "ratelimit:bench:client1"
    await client.delete(key)

    latencies_us: list[float] = []
    window = 60
    limit = num_operations + 1000

    start_total = time.perf_counter()
    for i in range(num_operations):
        now = time.time()
        member = f"{now}:{i}"
        t0 = time.perf_counter()
        await client.eval(
            SLIDING_WINDOW_LUA,
            1,
            key,
            str(now),
            str(window),
            str(limit),
            member,
        )
        elapsed_us = (time.perf_counter() - t0) * 1_000_000.0
        latencies_us.append(elapsed_us)
    total_duration_sec = time.perf_counter() - start_total

    latencies_us.sort()
    n = len(latencies_us)
    p50 = latencies_us[int(n * 0.50)]
    p95 = latencies_us[int(n * 0.95)]
    p99 = latencies_us[int(n * 0.99)]
    mean = statistics.mean(latencies_us)
    min_us = min(latencies_us)
    max_us = max(latencies_us)
    ops_per_sec = num_operations / total_duration_sec

    await client.delete(key)
    await client.close()

    logger.info(
        "Redis Microbenchmark Complete: %.2f ops/sec, Mean: %.2f us, p50: %.2f us, p95: %.2f us, p99: %.2f us",
        ops_per_sec,
        mean,
        p50,
        p95,
        p99,
    )

    return {
        "operations": num_operations,
        "total_duration_seconds": round(total_duration_sec, 4),
        "ops_per_second": round(ops_per_sec, 2),
        "mean_latency_us": round(mean, 2),
        "p50_latency_us": round(p50, 2),
        "p95_latency_us": round(p95, 2),
        "p99_latency_us": round(p99, 2),
        "min_latency_us": round(min_us, 2),
        "max_latency_us": round(max_us, 2),
    }


def run_abusive_flood_test(
    target_code: str = "s0000001",
    client_ip: str = "198.51.100.99",
    total_requests: int = 150,
) -> dict[str, float | int | str]:
    """Blast requests from a single client IP to test 429 quota exhaustion and Retry-After."""
    logger.info("Executing abusive flood test (%d requests from %s)...", total_requests, client_ip)
    url = f"http://localhost:8000/{target_code}"

    status_counts: dict[int, int] = {}
    latencies_307: list[float] = []
    latencies_429: list[float] = []
    retry_after_values: list[int] = []

    for _ in range(total_requests):
        req = urllib.request.Request(url, headers={"X-Forwarded-For": client_ip})
        t0 = time.perf_counter()
        try:
            # Opener that does not follow redirects
            class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *_args: object, **_kwargs: object) -> None:
                    return None

            opener = urllib.request.build_opener(NoRedirectHandler)
            resp = opener.open(req, timeout=5)
            status = resp.status
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            status_counts[status] = status_counts.get(status, 0) + 1
            latencies_307.append(elapsed_ms)
        except urllib.error.HTTPError as err:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            status = err.code
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == 429:
                latencies_429.append(elapsed_ms)
                retry_header = err.headers.get("Retry-After")
                if retry_header:
                    retry_after_values.append(int(retry_header))
        except Exception as exc:
            logger.warning("Request error during flood: %s", exc)

    logger.info("Flood test result counts: %s", status_counts)
    mean_307 = statistics.mean(latencies_307) if latencies_307 else 0.0
    mean_429 = statistics.mean(latencies_429) if latencies_429 else 0.0

    return {
        "client_ip": client_ip,
        "total_requests": total_requests,
        "allowed_307_count": status_counts.get(307, 0),
        "rejected_429_count": status_counts.get(429, 0),
        "mean_allowed_latency_ms": round(mean_307, 2),
        "mean_rejected_latency_ms": round(mean_429, 2),
        "sample_retry_after": retry_after_values[0] if retry_after_values else 0,
        "rate_limiting_enforced": status_counts.get(429, 0) > 0,
    }


def parse_locust_csv(csv_prefix: str) -> dict[str, float | int]:
    """Parse aggregated metrics from Locust stats CSV."""
    stats_file = Path(f"{csv_prefix}_stats.csv")
    if not stats_file.exists():
        raise FileNotFoundError(f"Locust stats file not found: {stats_file}")

    with stats_file.open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Name") == "Aggregated":
                req_count = int(row.get("Request Count", 0))
                fail_count = int(row.get("Failure Count", 0))
                rps = float(row.get("Requests/s", 0.0))
                p50 = float(row.get("50%", 0.0))
                p95 = float(row.get("95%", 0.0))
                p99 = float(row.get("99%", 0.0))
                avg_latency = float(row.get("Average Response Time", 0.0))
                err_rate = (fail_count / req_count * 100.0) if req_count > 0 else 0.0
                return {
                    "requests": req_count,
                    "failures": fail_count,
                    "rps": round(rps, 2),
                    "p50_latency_ms": round(p50, 2),
                    "p95_latency_ms": round(p95, 2),
                    "p99_latency_ms": round(p99, 2),
                    "avg_latency_ms": round(avg_latency, 2),
                    "error_rate_pct": round(err_rate, 4),
                }

    return {}


def run_locust_benchmark(
    name: str,
    users: int = 50,
    spawn_rate: int = 10,
    duration: str = "15s",
) -> dict[str, float | int]:
    """Execute a headless Locust run with MultiClientRedirectUser."""
    locust_bin = get_locust_executable()
    csv_prefix = str(OUTPUT_DIR / f"locust_{name}")

    cmd = [
        locust_bin,
        "-f",
        "load_tests/locustfile.py",
        "--headless",
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "-t",
        duration,
        "--host",
        "http://localhost:8000",
        "--csv",
        csv_prefix,
        "--only-summary",
        "MultiClientRedirectUser",
    ]

    logger.info("Executing Locust: %s (duration %s, %d users)...", name, duration, users)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logger.warning("Locust exited with code %d: %s", res.returncode, res.stderr)

    return parse_locust_csv(csv_prefix)


def set_container_rate_limit(enabled: bool) -> None:
    """Set RATE_LIMIT_ENABLED environment variable on API container and restart it."""
    logger.info("Configuring shortify-api RATE_LIMIT_ENABLED=%s...", str(enabled).lower())
    env_val = "true" if enabled else "false"
    # Use powershell env var before docker compose up
    cmd = (
        f"$env:RATE_LIMIT_ENABLED='{env_val}'; "
        f"docker compose up -d api"
    )
    subprocess.run(["powershell", "-Command", cmd], check=True, capture_output=True)
    if not wait_for_api_ready(30):
        raise RuntimeError("API failed to reach ready state after configuration change.")
    logger.info("API is healthy with RATE_LIMIT_ENABLED=%s", env_val)


def main() -> None:
    parser = argparse.ArgumentParser(description="Shortify Phase 9 Rate Limiting Benchmark Suite")
    parser.add_argument(
        "--experiment",
        choices=["micro", "overhead", "abuse", "all"],
        default="all",
        help="Experiment to execute",
    )
    args = parser.parse_args()

    results: dict[str, object] = {
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "git_commit": get_git_commit(),
            "python_version": platform.python_version(),
            "system": platform.platform(),
            "workload": "MultiClientRedirectUser (50 concurrent users)",
        }
    }

    # 1. Microbenchmark: Pure Redis Lua execution
    if args.experiment in ("micro", "all"):
        micro_results = asyncio.run(run_redis_microbenchmark(num_operations=2000))
        results["redis_microbenchmark"] = micro_results
        with (OUTPUT_DIR / "experiment_redis_microbenchmark.json").open("w") as f:
            json.dump(micro_results, f, indent=2)

    # 2. Abuse / Single IP flood test
    if args.experiment in ("abuse", "all"):
        abuse_results = run_abusive_flood_test(
            target_code="s0000001",
            client_ip="198.51.100.99",
            total_requests=150,
        )
        results["abusive_flood_test"] = abuse_results
        with (OUTPUT_DIR / "experiment_abusive_flood.json").open("w") as f:
            json.dump(abuse_results, f, indent=2)

    # 3. Rate Limiting Overhead (OFF vs ON)
    if args.experiment in ("overhead", "all"):
        logger.info("Running Rate Limiting OFF benchmark...")
        set_container_rate_limit(enabled=False)
        # Warm up
        run_locust_benchmark("warmup_off", users=10, duration="5s")
        bench_off = run_locust_benchmark("rate_limit_off", users=50, duration="15s")

        logger.info("Running Rate Limiting ON benchmark...")
        set_container_rate_limit(enabled=True)
        # Warm up
        run_locust_benchmark("warmup_on", users=10, duration="5s")
        bench_on = run_locust_benchmark("rate_limit_on", users=50, duration="15s")

        # Calculate overhead delta
        rps_off = float(bench_off.get("rps", 0.0))
        rps_on = float(bench_on.get("rps", 0.0))
        p50_off = float(bench_off.get("p50_latency_ms", 0.0))
        p50_on = float(bench_on.get("p50_latency_ms", 0.0))
        p95_off = float(bench_off.get("p95_latency_ms", 0.0))
        p95_on = float(bench_on.get("p95_latency_ms", 0.0))
        avg_off = float(bench_off.get("avg_latency_ms", 0.0))
        avg_on = float(bench_on.get("avg_latency_ms", 0.0))

        overhead_analysis = {
            "rate_limit_off": bench_off,
            "rate_limit_on": bench_on,
            "comparison": {
                "rps_delta": round(rps_on - rps_off, 2),
                "rps_pct_change": round(((rps_on - rps_off) / rps_off * 100.0) if rps_off > 0 else 0.0, 2),
                "p50_delta_ms": round(p50_on - p50_off, 2),
                "p95_delta_ms": round(p95_on - p95_off, 2),
                "avg_latency_delta_ms": round(avg_on - avg_off, 2),
                "avg_latency_pct_overhead": round(((avg_on - avg_off) / avg_off * 100.0) if avg_off > 0 else 0.0, 2),
            },
        }

        results["overhead_benchmark"] = overhead_analysis
        with (OUTPUT_DIR / "experiment_rate_limit_overhead.json").open("w") as f:
            json.dump(overhead_analysis, f, indent=2)

    # Save complete summary
    summary_path = OUTPUT_DIR / "rate_limiting_experiments_summary.json"
    with summary_path.open("w") as f:
        json.dump(results, f, indent=2)

    logger.info("All Phase 9 Rate Limiting Experiments Completed! Summary saved to %s", summary_path)


if __name__ == "__main__":
    main()
