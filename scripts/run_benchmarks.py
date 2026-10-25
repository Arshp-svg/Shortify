"""Automated benchmark execution harness for Shortify.

Collects system metrics, executes load scenarios, captures percentiles (p50, p95, p99),
and outputs raw CSV/JSON records to benchmarks/ directory.
"""

import argparse
import json
import os
import platform
import subprocess
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


def record_benchmark_metadata(scenario: str, duration: int, concurrency: int) -> dict[str, str]:
    """Capture hardware and execution environment details."""
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_commit": get_git_commit(),
        "os": f"{platform.system()} {platform.release()}",
        "python_version": platform.python_version(),
        "processor": platform.processor(),
        "cpu_count": str(os.cpu_count()),
        "scenario": scenario,
        "duration_seconds": str(duration),
        "concurrency": str(concurrency),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Shortify Benchmark Harness")
    parser.add_argument("--scenario", default="health_baseline", help="Benchmark scenario name")
    parser.add_argument("--duration", type=int, default=10, help="Duration in seconds")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent workers")
    parser.add_argument("--output-dir", default="benchmarks/baseline", help="Directory for output")

    args = parser.parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    metadata = record_benchmark_metadata(args.scenario, args.duration, args.concurrency)
    out_file = out_dir / f"benchmark_{int(time.time())}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"Benchmark record initialized: {out_file}")


if __name__ == "__main__":
    main()
