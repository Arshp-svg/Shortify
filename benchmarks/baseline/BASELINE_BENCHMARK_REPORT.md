# Shortify — Phase 6: Baseline Benchmark Report

**Document Version:** 1.0.0  
**Execution Date:** 2026-10-25T07:50:52Z  
**Authoritative Roadmap Phase:** Phase 6 (Baseline Deployment & Benchmarking)  
**Governing Rule:** *Establish a reproducible baseline before major optimizations. Build → Test → Measure → Observe → Identify the Bottleneck.*  
**Git Commit SHA:** `a303895`

---

## 1. Executive Summary

This report documents the baseline performance profile of **Shortify** prior to introducing caching (Redis), rate-limiting, or horizontal scaling. In this baseline configuration, every redirect request executes an atomic database lookup and an atomic SQL update (`UPDATE urls SET click_count = click_count + 1 WHERE id = :id`) against PostgreSQL 16 over a pooled connection (`pool_size=20`, `max_overflow=10`).

Across all four benchmark workloads with **50 concurrent users** and a pre-seeded dataset of **100,000 URLs**, the system delivered **zero errors (0.0% failure rate)** across **24,181 total requests**, sustaining **363 to 520 RPS**. 

The bottleneck in this baseline is conclusively identified as **relational database connection queueing and synchronous write locks on `click_count` updates**, providing the empirical justification for the database tuning in Phase 7 and Redis caching in Phase 8.

---

## 2. Test Environment & Hardware Specifications

| Component | Specification |
| :--- | :--- |
| **Host Operating System** | Windows 11 Pro (Build 26100) |
| **Processor** | Intel64 Family 6 Model 186 Stepping 2, GenuineIntel (16 vCPUs) |
| **Host Memory** | 32 GB RAM |
| **Python Runtime** | Python 3.12.10 |
| **Container Engine** | Docker Desktop (WSL2 backend, Docker Engine 27.x) |
| **FastAPI / Uvicorn** | 1 instance (`uvicorn app.main:api --workers 1`) |
| **Database** | PostgreSQL 16 Alpine (`shortify-postgres`, connection pool: 20 base, 10 overflow) |
| **Cache (Disabled)** | Redis 7 Alpine (`shortify-redis`, idling, caching bypassed for baseline) |
| **Load Generator** | Locust 2.32.8 (FastHttpUser, headless execution via `scripts/run_benchmarks.py`) |
| **Pre-seeded Dataset** | 100,000 deterministic Base62 records (`s0000000` – `s0099999`) |

---

## 3. Workload Results & Service-Level Target (SLT) Evaluation

All workloads were executed against the boundaries established in [`benchmarks/baseline/SLT_DEFINITION.md`](file:///c:/Users/ARSH/Desktop/shortify/benchmarks/baseline/SLT_DEFINITION.md).

### 3.1 Empirical Summary Table

| Workload Scenario | User Class | Concurrency | Total Requests | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Avg Latency (ms) | Failures | Error Rate | SLT Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Warmup (Prime)** | `RedirectHeavyUser` | 10 | 2,050 | 409.42 | 11.0 | 17.0 | 32.0 | 14.1 | 0 | 0.0% | **GREEN** |
| **A: Redirect-Heavy** | `RedirectHeavyUser` | 50 | 6,070 | 432.81 | 91.0 | 130.0 | 160.0 | 84.94 | 0 | 0.0% | **YELLOW** |
| **B: Create-Heavy** | `CreationHeavyUser` | 50 | 5,102 | 363.63 | 95.0 | 140.0 | 160.0 | 86.43 | 0 | 0.0% | **YELLOW** |
| **C: Mixed (90/10)** | `MixedWorkloadUser` | 50 | 5,702 | 406.38 | 98.0 | 140.0 | 160.0 | 91.23 | 0 | 0.0% | **YELLOW** |
| **D: 404 Invalid** | `InvalidTrafficUser` | 50 | 7,307 | 520.87 | 75.0 | 99.0 | 110.0 | 68.95 | 0 | 0.0% | **GREEN / YELLOW** |

---

## 4. Workload Analysis & Observations

### 4.1 Workload A: Redirect-Heavy (100% Lookups)
- **Locust Artifact:** `locust_redirect_20261025_074942_stats.csv` & `BM_REDIRECT_20261025_074942.json`
- **Measured RPS:** 432.81 req/s
- **Latency Distribution:** p50: 91.0 ms | p95: 130.0 ms | p99: 160.0 ms
- **Analysis:** Lookups utilize the B-Tree index on `urls.short_code` (0.061 ms database lookup execution time). However, every redirect executes an atomic `UPDATE urls SET click_count = click_count + 1 WHERE id = :id` followed by a transaction commit. Under 50 concurrent users sharing a pool of 20 database connections, request queuing occurs while awaiting database transaction commits, elevating p50 latency from 11 ms (at 10 users) to 91 ms (at 50 users).

### 4.2 Workload B: Creation-Heavy (100% Creations)
- **Locust Artifact:** `locust_create_20261025_075000_stats.csv` & `BM_CREATE_20261025_075000.json`
- **Measured RPS:** 363.63 req/s
- **Latency Distribution:** p50: 95.0 ms | p95: 140.0 ms | p99: 160.0 ms
- **Analysis:** Creating new short URLs involves Pydantic schema validation, Base62 cryptographic generation, database INSERT, and synchronous index page splitting / WAL writes. Throughput is lowest in this scenario (363 RPS) as expected for a write-intensive workload.

### 4.3 Workload C: Mixed Production Profile (90% Redirects, 10% Creations)
- **Locust Artifact:** `locust_mixed_20261025_075018_stats.csv` & `BM_MIXED_20261025_075018.json`
- **Measured RPS:** 406.38 req/s
- **Latency Distribution:** p50: 98.0 ms | p95: 140.0 ms | p99: 160.0 ms
- **Analysis:** Represents the standard production operating model. Write locks from creations and click count increments interleave without deadlocks or integrity failures.

### 4.4 Workload D: 404 / Invalid Traffic
- **Locust Artifact:** `locust_invalid_20261025_075036_stats.csv` & `BM_INVALID_20261025_075036.json`
- **Measured RPS:** 520.87 req/s
- **Latency Distribution:** p50: 75.0 ms | p95: 99.0 ms | p99: 110.0 ms
- **Analysis:** Highest throughput across all scenarios. Because non-existent short codes terminate after the index probe without executing a write lock or updating `click_count`, the database transaction is read-only and exits quickly, freeing the connection back to the pool immediately.

---

## 5. Container & Resource Utilization

Monitored during peak load via Docker Engine statistics:

| Container | CPU % (Peak) | Memory Usage | Memory % | Network I/O | Block I/O | PIDs |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `shortify-api` | 65% – 78% | 78.5 MiB / 7.62 GiB | 1.01% | 51.7 MB / 68.2 MB | 70.8 MB / 0 B | 6 |
| `shortify-postgres` | 28% – 35% | 105.6 MiB / 7.62 GiB | 1.35% | 53.9 MB / 37.7 MB | 39.6 MB / 328 MB | 26 |
| `shortify-redis` | < 1% (Idle) | 6.2 MiB / 7.62 GiB | 0.08% | 2.3 kB / 126 B | 14.5 MB / 0 B | 6 |
| `shortify-prometheus` | < 1% | 37.1 MiB / 7.62 GiB | 0.48% | 112 kB / 101 kB | 63.5 MB / 877 kB | 19 |
| `shortify-grafana` | < 1% | 50.1 MiB / 7.62 GiB | 0.64% | 20.7 kB / 5.0 kB | 143 MB / 205 kB | 21 |

---

## 6. Bottleneck Identification & Scientific Explanation

1. **Connection Pool Queueing:**
   - Under 10 users (warmup), p50 latency is **11.0 ms** and p95 is **17.0 ms** (Green).
   - Under 50 users, p50 latency increases to **91.0 ms** and p95 to **130.0 ms** (Yellow).
   - Because the FastAPI application runs with `pool_size=20` and `max_overflow=10` (max 30 connections), 50 concurrent requests contend for 30 available connections. The excess 20 requests sit in the async event loop queue waiting for an active connection to be returned.

2. **Synchronous Click-Count Write Bottleneck on Read Path:**
   - In standard HTTP redirection, users expect sub-15ms responses. However, Shortify's baseline updates `click_count` atomically on the relational table inside the same transaction as the read lookup.
   - Every redirect incurs disk WAL (Write-Ahead Logging) write overhead and row locking in PostgreSQL.
   - This directly explains why 404 lookups (which perform no write) are 20% faster (520 RPS vs 432 RPS) than successful redirects.

---

## 7. Optimization Roadmap Driven by Baseline Evidence

| Bottleneck Identified | Planned Roadmap Phase | Proposed Solution | Expected Impact |
| :--- | :--- | :--- | :--- |
| Database connection pool saturation | **Phase 7** (DB Optimization) | Tune connection pool sizing (5, 20, 50, 100) and measure EXPLAIN ANALYZE impact across dataset scales (10k, 100k, 1M). | Match pool size to concurrency profile. |
| Synchronous DB writes on redirect | **Phase 8** (Redis Caching) | Cache short-code → original-url in Redis (sub-millisecond in-memory lookup). Buffer click counts or offload redirect path. | Cut redirect p50 from 91ms to < 5ms; eliminate DB read load. |
| Single API process saturation | **Phase 12** (Horizontal Scaling) | Nginx load balancer with 1, 2, and 4 API container replicas. | Scale RPS linearly from ~430 to > 1,500 RPS. |

---

## 8. Definition of Done & Traceability Sign-off

- [x] Baseline established with zero caching enabled.
- [x] All 4 roadmap workload profiles executed with identical parameters.
- [x] Raw Locust CSVs (`_stats.csv`, `_stats_history.csv`, `_failures.csv`) and JSON records preserved.
- [x] Host hardware, OS, CPU, memory, and runtime versions recorded.
- [x] Bottleneck clearly identified and documented with empirical evidence.
- [x] Service Level Targets compared and graded against `SLT_DEFINITION.md`.
