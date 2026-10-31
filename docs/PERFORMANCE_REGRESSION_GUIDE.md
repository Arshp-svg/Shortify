# Shortify — Performance Regression Detection & Benchmark Automation Guide

**Authoritative Specification:** `Shortify_Project_1_Engineering_Roadmap.pdf` (Phase 13)  
**Governing Standard:** `AGENTS.md`  
**Last Updated:** 2026-10-31  

---

## 1. Executive Summary & Philosophy

In high-throughput distributed systems, functional tests only prove correctness; they cannot detect silent performance degradation (e.g., an accidental missing database index, synchronous blocking calls in an `async` route, increased lock contention on atomic counters, or cache invalidation misses).

Phase 13 establishes **automated continuous performance regression detection**, splitting testing into:
1. **Pull Request Fast Gates:** Static analysis, linting, unit tests, and PostgreSQL integration tests (<2 minutes).
2. **Scheduled Nightly Benchmark Suite:** Full multi-workload load testing (Locust) comparing live measurements against the committed reference baseline and failing if degradation exceeds statistical thresholds.

---

## 2. CI Architecture & Workflow Split

```
Pull Request / Feature Branch
   │
   ├──► Ruff Lint & Format
   ├──► Mypy Strict Type Check
   ├──► Bandit Security Scan
   ├──► Pytest Unit & Integration Tests (PostgreSQL + Redis)
   └──► Docker Compose Configuration Validation
   (Duration: ~90 seconds | Fast Feedback Loop)

Nightly Schedule (02:00 UTC) / Workflow Dispatch
   │
   ├──► PostgreSQL & Redis Services Launch
   ├──► Alembic Migrations (`alembic upgrade head`)
   ├──► Deterministic Dataset Seeding (10,000 URLs)
   ├──► Shortify API Server Launch
   ├──► Warmup Run (5s)
   ├──► Headless Locust Execution (Redirect, Create, Mixed, Invalid)
   ├──► Regression Analysis (`scripts/check_regression.py`)
   │      ├── p95 Latency Delta vs Baseline (< +15%)
   │      ├── p99 Latency Delta vs Baseline (< +20%)
   │      ├── Throughput Drop vs Baseline (< -20%)
   │      └── Error Rate (< 0.5%)
   └──► Artifact Archival (CSVs, JSON summaries, Markdown report)
```

---

## 3. Statistical Rationale for Regression Thresholds

Standard continuous integration environments (e.g., GitHub Actions Ubuntu runners) execute on virtualized shared hypervisors subject to **noisy neighbor jitter**. Defining overly strict thresholds (e.g., $\le 3\%$) produces false positive build failures.

Shortify adopts scientifically calibrated thresholds:

| Metric | Threshold | Rationale |
| :--- | :---: | :--- |
| **p95 Latency Regression** | **$\le +15\%$** | Typical CI hypervisor scheduling noise ranges from $4\%$ to $7\%$. A $15\%$ increase reliably isolates genuine algorithmic or database query degradation while avoiding false alerts. |
| **p99 Latency Regression** | **$\le +20\%$** | Tail latency is sensitive to garbage collection cycles and connection pool handoffs. A $20\%$ allowance permits minor virtualization tail variance while catching lock starvation. |
| **Throughput (RPS) Drop** | **$\le -20\%$** | Throughput reflects aggregate capacity; drops exceeding $20\%$ signal event-loop blocking or database pool exhaustion. |
| **Error Rate** | **$< 0.5\%$** | Production-grade APIs should experience zero errors under normal load. Any error rate above $0.5\%$ fails the build immediately. |

---

## 4. Developer Execution Runbook

### A. Run Benchmark Suite Locally
```powershell
# Run all workloads (redirect, create, mixed, invalid) with 50 concurrent users
.venv\Scripts\python scripts/run_benchmarks.py --users 50 --duration 15 --output-dir benchmarks/local_run
```

### B. Evaluate Regression Against Baseline
```powershell
# Compare local run against official baseline
.venv\Scripts\python scripts/check_regression.py `
  --baseline benchmarks/baseline/latest_benchmark_summary.json `
  --current benchmarks/local_run/latest_benchmark_summary.json `
  --max-p95-regression 15.0 `
  --max-p99-regression 20.0 `
  --max-rps-drop 20.0 `
  --max-error-rate 0.5 `
  --report-out benchmarks/local_run/regression_report.md
```

### C. Updating the Reference Baseline
When an architectural optimization intentionally shifts the baseline (e.g., introducing Redis cache-aside in Phase 8):
1. Run the official benchmark suite under standard conditions (warmup: 5s, users: 50, duration: 15s).
2. Inspect results and verify 0.0% errors.
3. Copy `benchmarks/local_run/latest_benchmark_summary.json` to `benchmarks/baseline/latest_benchmark_summary.json`.
4. Commit with descriptive message: `chore(benchmarks): update reference baseline for <feature>`.

---

## 5. Diagnostic Runbook for Regression Failures

When `scripts/check_regression.py` exits with code `1`:

1. **Inspect Markdown Report:** Open `benchmarks/nightly/regression_report.md` to identify which scenario failed (e.g., `redirect` vs `create`).
2. **If `create` regressed:**
   - Inspect database query execution plan via `EXPLAIN ANALYZE INSERT INTO urls ...`.
   - Check if table indexes grew large or table bloat occurred.
3. **If `redirect` regressed:**
   - Check Redis cache hit ratio from Prometheus `/metrics` (`shortify_cache_hits_total` vs `shortify_cache_misses_total`).
   - Check Redis round-trip latency.
   - Verify that database connection pool was not starved.
4. **If error rate $>0.5\%$:**
   - Search logs for HTTP 500 exceptions: `grep -i "500" logs/app.log`.
   - Verify PostgreSQL connection limit (`SHOW max_connections;`).

