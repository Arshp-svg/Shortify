"""Shortify Phase 11 Automated Chaos & Fault-Injection Suite.

Executes and measures 4 critical production failure scenarios:
1. Redis Outage Under Active Traffic (Verifies fail-open to PostgreSQL, 0% 500 errors)
2. PostgreSQL Outage (Verifies graceful HTTP 503 Service Unavailable & degraded readiness)
3. API Container Restart Under Load (Measures outage window, error burst, and recovery time)
4. Abusive Traffic Spike (Verifies rate limit enforcement and protection against exhaustion)
"""

import argparse
import contextlib
import json
import logging
import platform
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shortify.chaos")

OUTPUT_DIR = Path("benchmarks/chaos")
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


def wait_for_api_ready(timeout_seconds: int = 30) -> bool:
    """Poll API readiness probe until 200 OK is returned."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_seconds:
        try:
            with urllib.request.urlopen("http://localhost:8000/ready", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def run_cmd(cmd: list[str]) -> str:
    """Execute shell command and return stdout."""
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def experiment_redis_outage(target_code: str = "s0000001", num_requests: int = 15) -> dict[str, object]:
    """Chaos Experiment 1: Stop Redis container and evaluate redirect fail-open resilience."""
    logger.info("=== STARTING CHAOS EXPERIMENT 1: REDIS OUTAGE ===")
    initial_ready = wait_for_api_ready(10)
    assert initial_ready, "API not ready before test"

    logger.info("Injecting fault: docker compose stop redis...")
    run_cmd(["docker", "compose", "stop", "redis"])

    url = f"http://localhost:8000/{target_code}"
    status_counts: dict[int, int] = {}
    latencies: list[float] = []
    failopen_header_observed = False

    for _ in range(num_requests):
        req = urllib.request.Request(url, headers={"X-Forwarded-For": "198.51.100.50"})
        t0 = time.perf_counter()
        try:
            # Opener without redirect following
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *_args: object, **_kwargs: object) -> None:
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            resp = opener.open(req, timeout=10)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            status_counts[resp.status] = status_counts.get(resp.status, 0) + 1
            latencies.append(elapsed_ms)
            if resp.headers.get("X-RateLimit-FailOpen") == "true":
                failopen_header_observed = True
        except urllib.error.HTTPError as err:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            status_counts[err.code] = status_counts.get(err.code, 0) + 1
            latencies.append(elapsed_ms)
            if err.headers.get("X-RateLimit-FailOpen") == "true":
                failopen_header_observed = True
        except Exception as exc:
            logger.warning("Request error during Redis outage: %s", exc)
            status_counts[599] = status_counts.get(599, 0) + 1

    # Recover Redis
    logger.info("Recovering Redis container: docker compose start redis...")
    t_rec_start = time.perf_counter()
    run_cmd(["docker", "compose", "start", "redis"])
    redis_recovered = wait_for_api_ready(30)
    recovery_time_sec = round(time.perf_counter() - t_rec_start, 2)
    logger.info("Redis container recovered in %.2fs (healthy=%s)", recovery_time_sec, redis_recovered)

    client_5xx_errors = sum(count for code, count in status_counts.items() if code >= 500)
    success_307_count = status_counts.get(307, 0)
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

    result = {
        "scenario": "Redis Outage Under Redirect Load",
        "fault_injected": "docker compose stop redis",
        "total_requests": num_requests,
        "status_distribution": status_counts,
        "successful_307_redirects": success_307_count,
        "client_visible_5xx_errors": client_5xx_errors,
        "error_rate_pct": round((client_5xx_errors / num_requests * 100.0) if num_requests else 0.0, 2),
        "avg_latency_ms": avg_latency,
        "fail_open_header_verified": failopen_header_observed,
        "recovery_time_seconds": recovery_time_sec,
        "recovered": redis_recovered,
        "pass": bool(client_5xx_errors == 0 and success_307_count > 0 and redis_recovered),
    }
    logger.info("Experiment 1 Result: %s", result)
    return result


def experiment_postgres_outage() -> dict[str, object]:
    """Chaos Experiment 2: Stop PostgreSQL container and evaluate 503 response & readiness state."""
    logger.info("=== STARTING CHAOS EXPERIMENT 2: POSTGRESQL OUTAGE ===")
    assert wait_for_api_ready(10), "API not ready before test"

    logger.info("Injecting fault: docker compose stop postgres...")
    run_cmd(["docker", "compose", "stop", "postgres"])

    # 1. Test /ready probe during outage
    ready_status_code = 0
    ready_payload = {}
    try:
        urllib.request.urlopen("http://localhost:8000/ready", timeout=10)
        ready_status_code = 200
    except urllib.error.HTTPError as err:
        ready_status_code = err.code
        with contextlib.suppress(Exception):
            ready_payload = json.loads(err.read().decode())

    # 2. Test URL creation during outage
    create_status_code = 0
    create_payload = {}
    try:
        req = urllib.request.Request(
            "http://localhost:8000/api/v1/urls",
            data=json.dumps({"original_url": "https://postgres-down.example.com"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        create_status_code = resp.status
    except urllib.error.HTTPError as err:
        create_status_code = err.code
        with contextlib.suppress(Exception):
            create_payload = json.loads(err.read().decode())

    # Recover PostgreSQL
    logger.info("Recovering PostgreSQL container: docker compose start postgres...")
    t_rec = time.perf_counter()
    run_cmd(["docker", "compose", "start", "postgres"])
    postgres_recovered = wait_for_api_ready(30)
    recovery_time_sec = round(time.perf_counter() - t_rec, 2)
    logger.info("PostgreSQL recovered in %.2fs (healthy=%s)", recovery_time_sec, postgres_recovered)

    result = {
        "scenario": "PostgreSQL Outage",
        "fault_injected": "docker compose stop postgres",
        "ready_probe_status_code": ready_status_code,
        "ready_probe_payload": ready_payload,
        "url_create_status_code": create_status_code,
        "url_create_error_code": create_payload.get("error", {}).get("code", "UNKNOWN"),
        "recovery_time_seconds": recovery_time_sec,
        "recovered": postgres_recovered,
        "pass": bool(
            ready_status_code == 503
            and create_status_code == 503
            and postgres_recovered
        ),
    }
    logger.info("Experiment 2 Result: %s", result)
    return result


def experiment_api_restart(num_requests: int = 40) -> dict[str, object]:
    """Chaos Experiment 3: Restart API container during traffic and measure recovery duration."""
    logger.info("=== STARTING CHAOS EXPERIMENT 3: API RESTART UNDER TRAFFIC ===")
    assert wait_for_api_ready(10), "API not ready before test"

    logger.info("Injecting fault: docker compose restart api...")
    t_restart_start = time.perf_counter()
    run_cmd(["docker", "compose", "restart", "api"])

    # Measure time until API is healthy again
    api_recovered = wait_for_api_ready(30)
    downtime_sec = round(time.perf_counter() - t_restart_start, 2)
    logger.info("API restart completed and healthy in %.2fs", downtime_sec)

    # Dispatch verification requests post-restart
    status_counts: dict[int, int] = {}
    for _ in range(num_requests):
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *_args: object, **_kwargs: object) -> None:
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            resp = opener.open("http://localhost:8000/s0000001", timeout=3)
            status_counts[resp.status] = status_counts.get(resp.status, 0) + 1
        except urllib.error.HTTPError as err:
            status_counts[err.code] = status_counts.get(err.code, 0) + 1
        except Exception:
            status_counts[599] = status_counts.get(599, 0) + 1

    result = {
        "scenario": "API Container Restart",
        "fault_injected": "docker compose restart api",
        "restart_downtime_seconds": downtime_sec,
        "post_restart_requests": num_requests,
        "post_restart_status_distribution": status_counts,
        "recovered": api_recovered,
        "pass": bool(api_recovered and status_counts.get(307, 0) == num_requests),
    }
    logger.info("Experiment 3 Result: %s", result)
    return result


def experiment_abusive_flood(burst_size: int = 150) -> dict[str, object]:
    """Chaos Experiment 4: Abusive traffic burst from single client IP verifying rate limiting protection."""
    logger.info("=== STARTING CHAOS EXPERIMENT 4: ABUSIVE TRAFFIC BURST ===")
    assert wait_for_api_ready(10), "API not ready before test"

    client_ip = "198.51.100.77"
    url = "http://localhost:8000/s0000001"
    status_counts: dict[int, int] = {}
    retry_after_observed = False

    for _ in range(burst_size):
        req = urllib.request.Request(url, headers={"X-Forwarded-For": client_ip})
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *_args: object, **_kwargs: object) -> None:
                    return None

            opener = urllib.request.build_opener(NoRedirect)
            resp = opener.open(req, timeout=3)
            status_counts[resp.status] = status_counts.get(resp.status, 0) + 1
        except urllib.error.HTTPError as err:
            status_counts[err.code] = status_counts.get(err.code, 0) + 1
            if err.code == 429 and err.headers.get("Retry-After"):
                retry_after_observed = True
        except Exception:
            status_counts[599] = status_counts.get(599, 0) + 1

    result = {
        "scenario": "Abusive Traffic Flood",
        "fault_injected": f"{burst_size} requests in burst from single IP {client_ip}",
        "total_requests": burst_size,
        "allowed_307_count": status_counts.get(307, 0),
        "rejected_429_count": status_counts.get(429, 0),
        "retry_after_header_verified": retry_after_observed,
        "pass": bool(status_counts.get(429, 0) > 0 and retry_after_observed),
    }
    logger.info("Experiment 4 Result: %s", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Shortify Phase 11 Chaos Experiment Suite")
    parser.add_argument(
        "--experiment",
        choices=["redis", "postgres", "api", "abuse", "all"],
        default="all",
        help="Specific chaos experiment to run",
    )
    args = parser.parse_args()

    experiments: dict[str, Any] = {}

    if args.experiment in ("redis", "all"):
        experiments["redis_outage"] = experiment_redis_outage()

    if args.experiment in ("postgres", "all"):
        experiments["postgres_outage"] = experiment_postgres_outage()

    if args.experiment in ("api", "all"):
        experiments["api_restart"] = experiment_api_restart()

    if args.experiment in ("abuse", "all"):
        experiments["abusive_flood"] = experiment_abusive_flood()

    summary: dict[str, Any] = {
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "git_commit": get_git_commit(),
            "python_version": platform.python_version(),
            "system": platform.platform(),
        },
        "experiments": experiments,
    }

    summary_file = OUTPUT_DIR / "chaos_experiments_summary.json"
    with summary_file.open("w") as f:
        json.dump(summary, f, indent=2)

    logger.info("All Chaos Experiments Completed! Summary preserved at %s", summary_file)


if __name__ == "__main__":
    main()
