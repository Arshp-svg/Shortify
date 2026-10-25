# Shortify — Service-Level Targets (SLT) & Boundary Definitions

**Authoritative Specification:** `Shortify_Project_1_Engineering_Roadmap.pdf` (Phase 6)  
**Governing Principle:** *Define performance targets before optimization; never claim improvements without baseline measurement.*

---

## 1. Context & Objective

Phase 6 of the Shortify Engineering Roadmap poses the foundational performance engineering question:
> *"At what load does latency or error rate become unacceptable? Define a service-level target for your project and use it consistently."*

This document defines the strict quantitative boundaries separating acceptable service delivery from degraded performance. All subsequent benchmarking across Phases 7 (Database Optimization), 8 (Redis Caching), 9 (Rate Limiting), and 12 (Horizontal Scaling) will be evaluated against these precise targets.

---

## 2. Service-Level Targets (SLTs)

| Dimension | Metric | Acceptable Target (Green) | Degraded / Alert (Yellow) | Unacceptable / Failure (Red) |
| :--- | :--- | :--- | :--- | :--- |
| **Redirect Latency** | `p50` | $\le$ 15 ms | 15 ms – 30 ms | > 30 ms |
| | `p95` | $\le$ 40 ms | 40 ms – 100 ms | > 100 ms |
| | `p99` | $\le$ 80 ms | 80 ms – 200 ms | > 200 ms |
| **Creation Latency** | `p50` | $\le$ 25 ms | 25 ms – 50 ms | > 50 ms |
| | `p95` | $\le$ 60 ms | 60 ms – 150 ms | > 150 ms |
| | `p99` | $\le$ 120 ms | 120 ms – 300 ms | > 300 ms |
| **Reliability** | Error Rate | < 0.1% | 0.1% – 1.0% | $\ge$ 1.0% |
| **Throughput** | Baseline RPS | $\ge$ 200 req/s | 100 – 199 req/s | < 100 req/s |
| **Database Pool** | Pool Exhaustion | 0 timeouts | Queued requests | Connection Pool Timeout (500/503) |

---

## 3. Boundary Definition: When Does Load Become Unacceptable?

A load level is classified as **Unacceptable (Capacity Exceeded)** if any of the following conditions persist for more than 5 seconds:
1. **Latency Saturation:** `p95` latency exceeds **200 ms** on redirection lookups.
2. **Error Breach:** Client-visible 5xx server errors or connection dropouts exceed **1.0%** of total requests.
3. **Queueing Collapse:** Database connection acquisition wait times exceed the 30-second pool timeout (`asyncpg.exceptions.PoolTimeoutError`).
4. **Load Generator Saturated:** Load generator CPU utilization reaches 100%, indicating the benchmark harness itself is throttling measurements.

---

## 4. Benchmark Workload Profiles

All Phase 6 benchmarks follow a standardized 4-workload evaluation protocol:
1. **Workload A (Redirect-Heavy):** 100% `GET /{short_code}` queries randomly distributed across a 100,000-row pre-seeded database table.
2. **Workload B (Creation-Heavy):** 100% `POST /api/v1/urls` requests creating distinct short links with unique destinations.
3. **Workload C (Mixed Production Profile):** 90% `GET /{short_code}` redirects, 10% `POST /api/v1/urls` creates.
4. **Workload D (404/Invalid Traffic):** 100% queries targeting non-existent short codes to measure negative lookup and error-handling cost.
