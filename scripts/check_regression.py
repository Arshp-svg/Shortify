"""Phase 13: Automated Performance Regression Detection Engine.

Compares benchmark results against a reference baseline and flags performance regressions:
- Fails or warns if p95 latency regressed by more than threshold (default: >15%).
- Fails or warns if p99 latency regressed by more than threshold (default: >20%).
- Fails if error rate exceeds threshold (default: >0.5%).
- Fails if throughput (RPS) dropped by more than threshold (default: >20%).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_summary(path: Path) -> dict[str, dict[str, Any]]:
    """Load benchmark summary JSON and index records by scenario name."""
    if not path.exists():
        raise FileNotFoundError(f"Benchmark summary file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    indexed: dict[str, dict[str, Any]] = {}
    for item in data:
        scenario = item.get("scenario")
        if scenario:
            indexed[scenario] = item
    return indexed


def evaluate_regression(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    max_p95_pct: float = 15.0,
    max_p99_pct: float = 20.0,
    max_rps_drop_pct: float = 20.0,
    max_error_rate_pct: float = 0.5,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    """Compare current benchmark metrics against baseline metrics.

    Returns:
        passed: True if zero regression violations occurred.
        deltas: List of per-scenario metric comparisons.
        violations: List of specific threshold breach explanations.
    """
    violations: list[str] = []
    deltas: list[dict[str, Any]] = []

    for scenario, base_item in baseline.items():
        if scenario not in current:
            violations.append(f"Missing scenario in current benchmark: '{scenario}'")
            continue

        curr_item = current[scenario]
        base_res = base_item.get("results", {})
        curr_res = curr_item.get("results", {})

        base_p95 = float(base_res.get("p95_ms", 0.0))
        curr_p95 = float(curr_res.get("p95_ms", 0.0))
        base_p99 = float(base_res.get("p99_ms", 0.0))
        curr_p99 = float(curr_res.get("p99_ms", 0.0))
        base_rps = float(base_res.get("rps", 0.0))
        curr_rps = float(curr_res.get("rps", 0.0))
        curr_err = float(curr_res.get("error_rate_pct", 0.0))

        # Calculate percentage deltas (+ means slower latency, - means lower throughput)
        p95_delta_pct = ((curr_p95 - base_p95) / base_p95 * 100.0) if base_p95 > 0 else 0.0
        p99_delta_pct = ((curr_p99 - base_p99) / base_p99 * 100.0) if base_p99 > 0 else 0.0
        rps_drop_pct = ((base_rps - curr_rps) / base_rps * 100.0) if base_rps > 0 else 0.0

        scenario_passed = True
        scenario_notes: list[str] = []

        if p95_delta_pct > max_p95_pct:
            scenario_passed = False
            scenario_notes.append(
                f"p95 latency regressed by +{p95_delta_pct:.1f}% (threshold: +{max_p95_pct}%)"
            )
            violations.append(
                f"[{scenario}] p95 regression: {base_p95}ms -> {curr_p95}ms (+{p95_delta_pct:.1f}%)"
            )

        if p99_delta_pct > max_p99_pct:
            scenario_passed = False
            scenario_notes.append(
                f"p99 latency regressed by +{p99_delta_pct:.1f}% (threshold: +{max_p99_pct}%)"
            )
            violations.append(
                f"[{scenario}] p99 regression: {base_p99}ms -> {curr_p99}ms (+{p99_delta_pct:.1f}%)"
            )

        if rps_drop_pct > max_rps_drop_pct:
            scenario_passed = False
            scenario_notes.append(
                f"throughput dropped by -{rps_drop_pct:.1f}% (threshold: -{max_rps_drop_pct}%)"
            )
            violations.append(
                f"[{scenario}] RPS drop: {base_rps} -> {curr_rps} (-{rps_drop_pct:.1f}%)"
            )

        if curr_err > max_error_rate_pct:
            scenario_passed = False
            scenario_notes.append(
                f"error rate {curr_err:.2f}% exceeds threshold {max_error_rate_pct}%"
            )
            violations.append(f"[{scenario}] High error rate: {curr_err:.2f}%")

        deltas.append(
            {
                "scenario": scenario,
                "passed": scenario_passed,
                "base_rps": base_rps,
                "curr_rps": curr_rps,
                "rps_change_pct": round(-rps_drop_pct, 2),
                "base_p95_ms": base_p95,
                "curr_p95_ms": curr_p95,
                "p95_delta_pct": round(p95_delta_pct, 2),
                "base_p99_ms": base_p99,
                "curr_p99_ms": curr_p99,
                "p99_delta_pct": round(p99_delta_pct, 2),
                "error_rate_pct": curr_err,
                "notes": scenario_notes,
            }
        )

    overall_passed = len(violations) == 0
    return overall_passed, deltas, violations


def generate_markdown_report(
    deltas: list[dict[str, Any]],
    violations: list[str],
    baseline_commit: str,
    current_commit: str,
) -> str:
    """Format evaluation into a GitHub Flavored Markdown report."""
    status = "**PASSED (NO REGRESSION)**" if not violations else "**FAILED (PERFORMANCE REGRESSION DETECTED)**"

    lines = [
        "# Shortify — Performance Regression Comparison Report",
        "",
        f"**Status:** {status}  ",
        f"**Baseline Commit:** `{baseline_commit}` | **Current Commit:** `{current_commit}`  ",
        "",
        "| Scenario | Status | Baseline RPS | Current RPS | RPS Delta | Baseline p95 | Current p95 | p95 Delta | Baseline p99 | Current p99 | p99 Delta | Errors |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for d in deltas:
        badge = "PASSED" if d["passed"] else "REGRESSED"
        rps_sign = "+" if d["rps_change_pct"] > 0 else ""
        p95_sign = "+" if d["p95_delta_pct"] > 0 else ""
        p99_sign = "+" if d["p99_delta_pct"] > 0 else ""

        lines.append(
            f"| `{d['scenario']}` | **{badge}** | {d['base_rps']:.1f} | {d['curr_rps']:.1f} | {rps_sign}{d['rps_change_pct']}% | {d['base_p95_ms']:.1f}ms | {d['curr_p95_ms']:.1f}ms | {p95_sign}{d['p95_delta_pct']}% | {d['base_p99_ms']:.1f}ms | {d['curr_p99_ms']:.1f}ms | {p99_sign}{d['p99_delta_pct']}% | {d['error_rate_pct']:.2f}% |"
        )

    lines.append("")
    if violations:
        lines.append("### Regression Violations:")
        for v in violations:
            lines.append(f"- [FAIL] {v}")
    else:
        lines.append("All scenarios meet performance criteria: p95 within +15%, p99 within +20%, error rate <0.5%.")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Shortify Performance Regression Checker")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("benchmarks/baseline/latest_benchmark_summary.json"),
        help="Path to baseline benchmark summary JSON",
    )
    parser.add_argument(
        "--current",
        type=Path,
        required=True,
        help="Path to current benchmark summary JSON to evaluate",
    )
    parser.add_argument(
        "--max-p95-regression",
        type=float,
        default=15.0,
        help="Maximum allowed percentage increase in p95 latency (default: 15.0)",
    )
    parser.add_argument(
        "--max-p99-regression",
        type=float,
        default=20.0,
        help="Maximum allowed percentage increase in p99 latency (default: 20.0)",
    )
    parser.add_argument(
        "--max-rps-drop",
        type=float,
        default=20.0,
        help="Maximum allowed percentage drop in throughput RPS (default: 20.0)",
    )
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.5,
        help="Maximum allowed error rate percentage (default: 0.5)",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("benchmarks/regression_report.md"),
        help="Path to output markdown report",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        default=True,
        help="Exit with code 1 if any regression is detected",
    )

    args = parser.parse_args()

    baseline_data = load_summary(args.baseline)
    current_data = load_summary(args.current)

    # Extract commit info
    base_commit = next(iter(baseline_data.values())).get("git_commit", "unknown") if baseline_data else "unknown"
    curr_commit = next(iter(current_data.values())).get("git_commit", "unknown") if current_data else "unknown"

    passed, deltas, violations = evaluate_regression(
        baseline=baseline_data,
        current=current_data,
        max_p95_pct=args.max_p95_regression,
        max_p99_pct=args.max_p99_regression,
        max_rps_drop_pct=args.max_rps_drop,
        max_error_rate_pct=args.max_error_rate,
    )

    report_md = generate_markdown_report(deltas, violations, base_commit, curr_commit)
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.report_out, "w", encoding="utf-8") as f:
        f.write(report_md)

    print("\n" + "=" * 70)
    print("SHORTIFY PERFORMANCE REGRESSION AUDIT")
    print("=" * 70)
    for d in deltas:
        mark = "[PASS]" if d["passed"] else "[FAIL]"
        print(
            f"{mark} {d['scenario'].ljust(10)} | RPS: {d['curr_rps']} ({d['rps_change_pct']}%) | p95: {d['curr_p95_ms']}ms ({d['p95_delta_pct']}%) | p99: {d['curr_p99_ms']}ms ({d['p99_delta_pct']}%) | Errors: {d['error_rate_pct']}%"
        )

    if violations:
        print("\n[!] REGRESSION DETECTED:")
        for v in violations:
            print(f"    - {v}")
    else:
        print("\n[OK] Clean performance check. Zero regressions detected.")

    print(f"\nDetailed report written to: {args.report_out}")
    print("=" * 70 + "\n")

    if not passed and args.fail_on_regression:
        sys.exit(1)


if __name__ == "__main__":
    main()

