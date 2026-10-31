"""Unit tests for Phase 13 performance regression detector."""

from scripts.check_regression import evaluate_regression, generate_markdown_report


def test_evaluate_regression_clean_pass() -> None:
    """Verify that improved or slightly changed metrics pass cleanly."""
    baseline = {
        "redirect": {
            "scenario": "redirect",
            "results": {"rps": 400.0, "p50_ms": 50.0, "p95_ms": 100.0, "p99_ms": 150.0, "error_rate_pct": 0.0},
        }
    }
    # 5% latency increase, 2% higher RPS (within 15% tolerance)
    current = {
        "redirect": {
            "scenario": "redirect",
            "results": {"rps": 410.0, "p50_ms": 52.0, "p95_ms": 105.0, "p99_ms": 155.0, "error_rate_pct": 0.0},
        }
    }

    passed, deltas, violations = evaluate_regression(baseline, current, max_p95_pct=15.0)
    assert passed is True
    assert len(violations) == 0
    assert len(deltas) == 1
    assert deltas[0]["passed"] is True
    assert deltas[0]["p95_delta_pct"] == 5.0


def test_evaluate_regression_p95_violation() -> None:
    """Verify that >15% p95 increase is detected and flagged as a failure."""
    baseline = {
        "redirect": {
            "scenario": "redirect",
            "results": {"rps": 400.0, "p95_ms": 100.0, "p99_ms": 150.0, "error_rate_pct": 0.0},
        }
    }
    # 25% p95 latency increase (violates 15% threshold)
    current = {
        "redirect": {
            "scenario": "redirect",
            "results": {"rps": 390.0, "p95_ms": 125.0, "p99_ms": 160.0, "error_rate_pct": 0.0},
        }
    }

    passed, deltas, violations = evaluate_regression(baseline, current, max_p95_pct=15.0)
    assert passed is False
    assert len(violations) == 1
    assert "p95 regression" in violations[0]
    assert deltas[0]["passed"] is False


def test_evaluate_regression_p99_violation() -> None:
    """Verify that >20% p99 increase is flagged."""
    baseline = {
        "redirect": {
            "scenario": "redirect",
            "results": {"rps": 400.0, "p95_ms": 100.0, "p99_ms": 150.0, "error_rate_pct": 0.0},
        }
    }
    # 33% p99 latency increase (violates 20% threshold)
    current = {
        "redirect": {
            "scenario": "redirect",
            "results": {"rps": 400.0, "p95_ms": 105.0, "p99_ms": 200.0, "error_rate_pct": 0.0},
        }
    }

    passed, deltas, violations = evaluate_regression(baseline, current, max_p99_pct=20.0)
    assert passed is False
    assert len(violations) == 1
    assert "p99 regression" in violations[0]


def test_evaluate_regression_rps_drop() -> None:
    """Verify that severe throughput drop is flagged."""
    baseline = {
        "create": {
            "scenario": "create",
            "results": {"rps": 500.0, "p95_ms": 80.0, "p99_ms": 120.0, "error_rate_pct": 0.0},
        }
    }
    # 30% RPS throughput drop
    current = {
        "create": {
            "scenario": "create",
            "results": {"rps": 350.0, "p95_ms": 82.0, "p99_ms": 122.0, "error_rate_pct": 0.0},
        }
    }

    passed, deltas, violations = evaluate_regression(baseline, current, max_rps_drop_pct=20.0)
    assert passed is False
    assert any("RPS drop" in v for v in violations)


def test_evaluate_regression_error_rate() -> None:
    """Verify error rate exceeding 0.5% triggers regression violation."""
    baseline = {
        "mixed": {
            "scenario": "mixed",
            "results": {"rps": 300.0, "p95_ms": 100.0, "p99_ms": 140.0, "error_rate_pct": 0.0},
        }
    }
    current = {
        "mixed": {
            "scenario": "mixed",
            "results": {"rps": 300.0, "p95_ms": 100.0, "p99_ms": 140.0, "error_rate_pct": 1.5},
        }
    }

    passed, deltas, violations = evaluate_regression(baseline, current, max_error_rate_pct=0.5)
    assert passed is False
    assert any("High error rate" in v for v in violations)


def test_missing_scenario_detection() -> None:
    """Verify that missing scenarios in current run are reported as violations."""
    baseline = {
        "redirect": {"scenario": "redirect", "results": {}},
        "missing_scenario": {"scenario": "missing_scenario", "results": {}},
    }
    current = {
        "redirect": {"scenario": "redirect", "results": {"p95_ms": 10.0, "rps": 100.0}},
    }

    passed, deltas, violations = evaluate_regression(baseline, current)
    assert passed is False
    assert any("Missing scenario" in v for v in violations)


def test_markdown_report_formatting() -> None:
    """Verify generated markdown contains proper structure and tables."""
    deltas = [
        {
            "scenario": "redirect",
            "passed": True,
            "base_rps": 400.0,
            "curr_rps": 420.0,
            "rps_change_pct": 5.0,
            "base_p95_ms": 100.0,
            "curr_p95_ms": 95.0,
            "p95_delta_pct": -5.0,
            "base_p99_ms": 150.0,
            "curr_p99_ms": 145.0,
            "p99_delta_pct": -3.3,
            "error_rate_pct": 0.0,
        }
    ]
    report = generate_markdown_report(deltas, violations=[], baseline_commit="abc1234", current_commit="def5678")
    assert "# Shortify — Performance Regression Comparison Report" in report
    assert "`redirect`" in report
    assert "PASSED (NO REGRESSION)" in report

