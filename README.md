# Shortify — Production-Grade URL Shortener & Backend Performance Laboratory

[![CI Quality Gates](https://github.com/Arshp-svg/Shortify/actions/workflows/ci.yml/badge.svg)](https://github.com/Arshp-svg/Shortify/actions/workflows/ci.yml)
[![Nightly Benchmarks](https://github.com/Arshp-svg/Shortify/actions/workflows/benchmarks.yml/badge.svg)](https://github.com/Arshp-svg/Shortify/actions/workflows/benchmarks.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type Checked: Mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)
[![Security: Bandit & pip-audit](https://img.shields.io/badge/security-passed-brightgreen.svg)](https://github.com/PyCQA/bandit)

Shortify is a production-grade URL shortener and high-concurrency backend engineering laboratory built with FastAPI, PostgreSQL 16, Redis 7, Nginx, Docker Compose, and Prometheus/Grafana.

It was developed following an empirical, hypothesis-driven engineering methodology:  
**Build → Test → Measure → Observe → Identify Bottleneck → Change One Variable → Test Again → Measure Again → Explain the Evidence.**

---

## 1. System Architecture

```
                               Ingress Traffic (HTTP :8000)
                                            │
                                            ▼
                      Nginx Reverse Proxy & Load Balancer (Round-Robin)
                            ├── keepalive 64; proxy_pass
                            │
               ┌────────────┴────────────┬────────────────────────┐
               ▼                         ▼                        ▼
       FastAPI Replica 1         FastAPI Replica 2        FastAPI Replica N
       (Async I/O Worker)        (Async I/O Worker)       (Async I/O Worker)
               │                         │                        │
               └────────────┬────────────┴────────────────────────┘
                            │
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼
    [Redis 7 Alpine]                  [PostgreSQL 16 Alpine]
    - Cache-Aside (TTL: 1hr)          - Durable ACID Relational Store
    - Fail-Open Graceful Degradation  - B-Tree Unique Index on `short_code`
    - Sliding-Window Rate Limiter     - Atomic Counters (`click_count = click_count + 1`)
    - Sub-millisecond Lookups         - Connection Pooled (`max_connections=200`)
          ▲                                   ▲
          │                                   │
          └─────────────────┬─────────────────┘
                            │ Scraped every 5s
                            ▼
                 [Prometheus 2.54 Engine]
                            │
                            ▼
                  [Grafana 11.2 Dashboards]
```

---

## 2. API Contract Summary

| Method | Endpoint | Description | Status Codes | Rate Limit |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/urls` | Create shortened URL (random or custom alias) | `201`, `400`, `409`, `422`, `429` | 60 req/min |
| `GET` | `/{short_code}` | Redirect to original target URL | `307`, `404`, `410`, `429` | 120 req/min |
| `GET` | `/api/v1/urls/{id}` | Retrieve URL metadata | `200`, `404` | 120 req/min |
| `GET` | `/api/v1/urls/{id}/stats` | Retrieve click analytics & status | `200`, `404` | 120 req/min |
| `DELETE` | `/api/v1/urls/{id}` | Deactivate URL (soft delete & cache purge) | `204`, `404` | 60 req/min |
| `GET` | `/health` | Kubernetes/Container liveness probe | `200` | Excluded |
| `GET` | `/ready` | Dependency readiness probe (DB & Redis) | `200`, `503` | Excluded |
| `GET` | `/metrics` | Prometheus exposition endpoint | `200` | Excluded |

*Detailed request/response schemas and RFC specifications are in [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).*

---

## 3. Empirical Performance Engineering & Benchmark Evolution

Every architectural decision was measured under identical hardware and concurrency conditions (50 concurrent Locust users, Intel Core 16-core, Windows 11 / Linux containers):

### A. Database Indexing Impact (Phase 7)
Comparing a sequential scan against an indexed B-tree scan across 100,000 seeded URLs:
- **Sequential Scan (No Index):** `43.80 ms` latency, 1,724 disk page reads.
- **Index Scan (B-Tree on `short_code`):** `0.108 ms` latency, 4 buffer page hits.
- **Speedup Factor:** **$405.6\times$ query speedup**, reducing database CPU load by $99.8\%$.

### B. Redis Cache-Aside & Fail-Open Impact (Phase 8)
- **Database-Only Baseline Redirect Throughput:** `432.8 RPS` (p95: `130 ms`, p99: `160 ms`).
- **Redis Cache-Aside Redirect Throughput:** **`907.8 RPS`** (p95: `67 ms`, p99: `95 ms`).
- **Cache Hit Ratio Under Mixed Traffic:** **$96.4\%$** with sub-millisecond Redis lookups ($<1\text{ms}$).
- **Fail-Open Resilience:** When Redis container was killed during active load, traffic degraded gracefully to PostgreSQL with **$0.0\%$ HTTP 5xx errors**.

### C. Horizontal Scaling Progression (Phase 12)
Ingress traffic load balanced across Nginx reverse proxy using round-robin upstream:

| Replicas | Upstreams | Throughput (RPS) | Scaling Factor | Efficiency | p50 Latency | p95 Latency | p99 Latency | Error Rate |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1 Replica** | 1 instance | **217.41 RPS** | 1.00x | 100.0% | 180.0 ms | 300.0 ms | 490.0 ms | 0.0% |
| **2 Replicas** | 2 instances | **311.60 RPS** | **1.43x** | 71.5% | 92.0 ms | 260.0 ms | 320.0 ms | 0.0% |
| **4 Replicas** | 4 instances | **481.24 RPS** | **2.21x** | 55.2% | 51.0 ms | 200.0 ms | 230.0 ms | 0.0% |

*Sublinear scaling analysis:* Beyond 2 replicas, throughput scaling becomes sublinear due to shared relational storage locks on `click_count` updates and connection pool contention on PostgreSQL. See [`docs/SCALING_REPORT.md`](docs/SCALING_REPORT.md).

---

## 4. Security Hardening & Controls (Phase 14)

Shortify incorporates defense-in-depth security controls:
1. **SSRF Defense:** The server **never** fetches user-supplied URLs. Target URLs are validated via `ipaddress` parsing to strictly prohibit loopback (`127.0.0.1`, `localhost`), link-local (`169.254.x.x` AWS/GCP metadata service), private CIDRs (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and internal DNS suffixes (`.local`, `.internal`).
2. **Strict Protocol Restrictions:** Only `http` and `https` schemes are accepted; dangerous protocols (`file://`, `javascript:`, `ftp://`) are rejected at schema validation.
3. **Response Security Headers:** Injected across all responses:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `X-XSS-Protection: 1; mode=block`
   - `Referrer-Policy: strict-origin-when-cross-origin`
4. **Static Security Scans:**
   - **Bandit:** 0 security vulnerabilities identified across codebase.
   - **pip-audit:** 0 known CVEs across all project dependencies.
   - **Secret Scanning:** Zero hardcoded credentials or private keys in repository.

---

## 5. Quickstart & Deployment

### Quick Launch with Docker Compose
```bash
# 1. Clone repository
git clone https://github.com/shortify/shortify.git
cd shortify

# 2. Configure environment defaults
cp .env.example .env

# 3. Start complete load-balanced cluster (Nginx + 2 API Replicas + DB + Redis + Monitoring)
docker compose -f docker-compose.scaling.yml up -d --build --scale api=2

# 4. Verify cluster health
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

### URLs & Dashboards
- **API Endpoint:** `http://localhost:8000`
- **Swagger / OpenAPI Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Prometheus Metrics Scrape:** [http://localhost:8000/metrics](http://localhost:8000/metrics)
- **Grafana Real-Time Dashboard:** [http://localhost:3000](http://localhost:3000) *(User: `admin`, Pass: `admin`)*

---

## 6. Developer Commands & Quality Gates

| Command | Action | Acceptance Criteria |
| :--- | :--- | :--- |
| `pytest` | Execute automated test pyramid | 71/71 tests passing (Unit, Integration, Resilience, Security) |
| `ruff check .` | Run linter checks | 0 errors |
| `ruff format --check .` | Check code formatting | Clean formatting |
| `mypy app tests scripts` | Strict static type checking | Strict mode passing without errors |
| `bandit -r app` | Static application security testing | 0 issues identified |
| `pip-audit` | Dependency CVE vulnerability scan | 0 known vulnerabilities |
| `python scripts/check_regression.py` | Performance regression audit | Flags any p95 regression $>15\%$ |

---

## 7. Authoritative Documentation Index

- [Production Operations Runbook](docs/RUNBOOK.md)
- [Requirement Traceability Matrix (RTM)](docs/TRACEABILITY_MATRIX.md)
- [Phase Progress Tracker](docs/PHASE_TRACKER.md)
- [Performance Regression Guide](docs/PERFORMANCE_REGRESSION_GUIDE.md)
- [Horizontal Scaling & Load Balancing Report](docs/SCALING_REPORT.md)
- [Failure Testing & Resilience Report](docs/FAILURE_EXPERIMENTS.md)
- [Observability & Dashboard Report](docs/OBSERVABILITY_REPORT.md)
- [Rate Limiting Overhead Report](docs/RATE_LIMITING_REPORT.md)
- [Redis Caching & Invalidation Report](docs/REDIS_CACHING_REPORT.md)
- [Database Performance Engineering Report](docs/DATABASE_OPTIMIZATION_REPORT.md)
- [API Contract & Schema Specification](docs/API_CONTRACT.md)
- [Architectural Decision Records (ADRs)](docs/DECISIONS.md)

---

## 8. Limitations & Future Work

1. **Database Write Scalability:** Atomic updates on `click_count` lock individual rows in PostgreSQL. At 10,000+ RPS, click counts should be buffered in Redis using hyperloglog or atomic increment buffers and flushed periodically to PostgreSQL in bulk.
2. **Distributed Redis:** Current architecture utilizes a single master Redis with fail-open. Production multi-region deployments should adopt Redis Cluster with read replicas.
3. **Geo-Distributed Anycast:** Ingress currently enters a single Nginx reverse proxy; geo-distributed anycast routing (e.g., Cloudflare Workers or AWS Route53 latency routing) would further reduce p99 global redirect latency.
