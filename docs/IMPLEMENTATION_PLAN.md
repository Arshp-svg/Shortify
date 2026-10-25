# Shortify — Implementation Plan

**Author:** Master Autonomous Software Engineering Agent  
**Specification:** `Shortify_Project_1_Engineering_Roadmap.pdf`  
**Governing Rule:** `AGENTS.md`  
**Core Principle:** *Build → Test → Measure → Observe → Identify Bottleneck → Change One Variable → Test Again → Measure Again → Explain the Evidence.*

---

## 1. Project Overview & Architecture Evolution

Shortify is engineered not merely as a simple URL shortener, but as a production-grade backend engineering laboratory. It demonstrates progressive architectural evolution:

1. **Baseline Phase (Phases 0–6):**
   ```
   Client / Load Generator
         │
         ▼
     FastAPI (Single Replica)
         │ (SQLAlchemy async + asyncpg pool)
         ▼
     PostgreSQL (Durable Storage)
   ```
   *No caching, no proxy. Clean baseline to measure raw relational database bottlenecks and establish unoptimized benchmarks.*

2. **Database Optimization Phase (Phase 7):**
   - Measure 10k, 100k, 1M datasets.
   - Profile queries using `EXPLAIN ANALYZE` and `pg_stat_statements`.
   - Add B-Tree unique index on `short_code`.
   - Measure connection pool saturation points.

3. **Caching & Rate Limiting Phase (Phases 8–9):**
   ```
   Client ──► FastAPI ──► Redis (Cache-Aside: GET key)
                 │              │
                 │ (Cache Miss) │ (Cache Hit)
                 ▼              ▼
            PostgreSQL       Return Redirect
   ```
   - Redis cache-aside with configurable TTL and fail-open resilience.
   - Sliding window rate limiting in Redis.

4. **Observability & Resilience Phase (Phases 10–11):**
   - Prometheus metrics collector (`/metrics`) exposing throughput, latency histograms, error counters, cache hit/miss ratio.
   - Provisioned Grafana dashboards.
   - Structured JSON logging with request correlation IDs.
   - Fault injection testing (PostgreSQL drop, Redis drop, API kill).

5. **Scale & Production Release Phase (Phases 12–15):**
   ```
   Client ──► Nginx Load Balancer (Reverse Proxy)
                   ├──► FastAPI (Replica 1) ──┐
                   ├──► FastAPI (Replica 2) ──┼──► Redis Cluster / Instance
                   └──► FastAPI (Replica 3) ──┴──► PostgreSQL DB
   ```
   - Benchmark 1 vs 2 vs 4 replicas.
   - Automated performance regression detection in CI.
   - Security auditing (Bandit, pip-audit, SSRF protection).
   - Final benchmark report and verified resume evidence.

---

## 2. Directory Layout Plan

```
shortify/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── urls.py          # POST /api/v1/urls, GET/DELETE /api/v1/urls/{id}, stats
│   │   │   │   └── health.py        # /health, /ready
│   │   │   └── router.py            # APIRouter grouping v1 endpoints
│   │   ├── redirect.py              # GET /{short_code} high-throughput redirect endpoint
│   │   └── deps.py                  # FastAPI dependency injection (DB session, Redis, settings)
│   ├── core/
│   │   ├── config.py                # Pydantic Settings from environment
│   │   ├── database.py              # Async SQLAlchemy engine & sessionmaker with pool tuning
│   │   ├── exceptions.py            # Centralized custom exceptions & standard error handlers
│   │   ├── logging.py               # Structured JSON logging & request-ID context filter
│   │   ├── metrics.py               # Prometheus metrics instrumentation & middleware
│   │   └── rate_limit.py            # Redis-based sliding-window rate limiter
│   ├── models/
│   │   ├── base.py                  # DeclarativeBase with standard timestamps
│   │   └── url.py                   # URL entity (id, short_code, original_url, created_at, expires_at, click_count, active)
│   ├── repositories/
│   │   ├── base.py                  # Abstract base repository pattern
│   │   └── url_repository.py        # Optimized SQL queries, atomic increments, index utilization
│   ├── schemas/
│   │   ├── url.py                   # URLCreateRequest, URLResponse, URLStatsResponse schemas with URL validation
│   │   └── error.py                 # ErrorResponse schema matching roadmap format
│   ├── services/
│   │   ├── base62.py                # Base62 encoder/decoder & cryptographic collision-safe generator
│   │   ├── cache_service.py         # Redis cache-aside layer with fail-open fallback
│   │   └── url_service.py           # Core business logic: creation, alias validation, expiration, soft delete
│   └── main.py                      # Application lifespan, middleware stack, CORS, routing
├── migrations/                      # Alembic environment and versions
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── monitoring/
│   ├── prometheus/
│   │   └── prometheus.yml           # Scrape configuration for Shortify API instances
│   └── grafana/
│       ├── provisioning/
│       │   ├── datasources/
│       │   └── dashboards/
│       └── dashboards/
│           ├── shortify_traffic.json
│           └── shortify_resources.json
├── nginx/
│   └── nginx.conf                   # Upstream load balancing for 1, 2, 4 replicas
├── tests/
│   ├── unit/
│   │   ├── test_base62.py
│   │   ├── test_schemas.py
│   │   ├── test_url_service.py
│   │   └── test_rate_limiter.py
│   ├── integration/
│   │   ├── test_api_urls.py
│   │   ├── test_redirect.py
│   │   ├── test_concurrency.py      # Duplicate alias race condition test
│   │   ├── test_click_counter.py    # Atomic concurrent redirect click count updates
│   │   └── test_cache_aside.py      # Redis cache hit/miss/invalidation/failover
│   ├── contract/
│   │   └── shortify_collection.json # Postman / Newman collection
│   ├── resilience/
│   │   └── test_fault_injection.py  # Simulated Redis / DB outage behavior
│   └── conftest.py                  # Pytest fixtures, test DB containers, async client
├── load_tests/
│   └── locustfile.py                # Realistic mixed scenarios (redirect-heavy, create, burst, 404)
├── benchmarks/
│   ├── baseline/                    # Phase 6 raw CSVs & reports
│   ├── database/                    # Phase 7 EXPLAIN ANALYZE, pool tuning, dataset scaling
│   ├── redis/                       # Phase 8 cache performance benchmarks
│   ├── rate_limiting/               # Phase 9 rate limiting overhead benchmarks
│   ├── scaling/                     # Phase 12 1 vs 2 vs 4 replica scaling benchmarks
│   └── reports/                     # Generated charts and comparison summaries
├── scripts/
│   ├── seed_urls.py                 # Fast bulk generator for 10k, 100k, 1M URLs
│   ├── run_benchmarks.py            # Automated load test runner & CSV parser
│   └── export_metrics.py            # Prometheus metric exporter to CSV
├── docs/                            # Traceability, audit, plans, reports, runbooks
├── .github/
│   └── workflows/
│       └── ci.yml                   # CI quality gates (lint, typecheck, pytest, security)
├── .pre-commit-config.yaml
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── README.md
```

---

## 3. Detailed Phase Execution Roadmap

### Phase 0: Engineering Setup & Workflow (Milestone 1)
- **Goal:** Clean repository, environment configurations, reproducible start command, and CI.
- **Tasks:**
  1. Git init and `.gitignore` authoring.
  2. `pyproject.toml` with Python 3.12, FastAPI, SQLAlchemy 2.0, asyncpg, Redis, Pydantic v2, Ruff, mypy, pytest, Locust.
  3. `.env.example` defining all required configuration keys.
  4. Docker Compose with services: `app`, `postgres`, `redis`, `prometheus`, `grafana`.
  5. Multi-stage `Dockerfile` with non-root user and minimal footprint.
  6. `Makefile` and PowerShell companion scripts (`run`, `test`, `lint`, `typecheck`, `load-test`).
  7. GitHub Actions CI workflow (`.github/workflows/ci.yml`).
  8. Pre-commit configuration (`.pre-commit-config.yaml`).

### Phase 1: Requirements, Architecture & API Contract
- **Goal:** Documented architectural decisions, OpenAPI schemas, and formal contracts.
- **Tasks:**
  1. Author `docs/API_CONTRACT.md` defining request payloads, responses, headers, and status codes.
  2. Author `docs/ARCHITECTURE.md` with data flow diagrams.
  3. Author `docs/DECISIONS.md` covering:
     - 307 Temporary Redirect vs 302/301 (caching semantics, method preservation).
     - Collision resolution strategy (Base62 crypto-random generation + DB constraint retry).
     - Click counter consistency (Atomic DB increment `UPDATE click_count = click_count + 1` vs Redis buffer).
     - Expiration timestamp handling (UTC timezone-aware datetime).

### Phase 2: FastAPI Service Skeleton & Configuration
- **Goal:** Typed, robust service skeleton with health checks and structured logging.
- **Tasks:**
  1. Implement `app/core/config.py` with `pydantic-settings`.
  2. Structured JSON logging with `request_id` correlation in middleware.
  3. Global exception handlers converting unhandled errors to standard JSON format without leaking internal traces.
  4. Implement `/health` (liveness) and `/ready` (dependency readiness).
  5. Database connection pooling setup with explicit pool size, overflow, and recycle times.

### Phase 3: PostgreSQL Schema, Migrations & Repositories
- **Goal:** Relational persistence, versioned migrations, and race condition defense.
- **Tasks:**
  1. Define `URL` SQLAlchemy declarative model.
  2. Configure Alembic async environment and initial migration.
  3. Add unique constraint on `short_code` and composite indexes.
  4. Implement `URLRepository` with async sessions.
  5. Build `tests/integration/test_concurrency.py` verifying duplicate alias rejection at the database constraint level.
  6. Author `scripts/seed_urls.py` capable of bulk-inserting 100k+ records.

### Phase 4: Core URL Lifecycle & Correctness
- **Goal:** End-to-end URL shortener lifecycle with comprehensive error handling.
- **Tasks:**
  1. URL creation service (`POST /api/v1/urls`) with custom alias validation and collision retries.
  2. Redirection endpoint (`GET /{short_code}`) with expiration checking and atomic click count increment.
  3. URL retrieval (`GET /api/v1/urls/{id}`) and statistics (`GET /api/v1/urls/{id}/stats`).
  4. Soft deletion/deactivation (`DELETE /api/v1/urls/{id}`).
  5. Concurrency tests for simultaneous redirects and expiration races.

### Phase 5: Testing Strategy & Quality Gates
- **Goal:** Rock-solid test suite ensuring zero regressions before performance benchmarking.
- **Tasks:**
  1. Unit tests covering all business rules, Base62 logic, and schema validations.
  2. Integration tests with real PostgreSQL container.
  3. Postman / Newman collection for API contract and smoke validation.
  4. Quality gates: Ruff linting & formatting, mypy strict type checking, Bandit security scans.

### Phase 6: Baseline Deployment & Benchmarking
- **Goal:** Measure and record the baseline performance of the raw FastAPI + PostgreSQL system before caching.
- **Tasks:**
  1. Author `load_tests/locustfile.py` with realistic user behaviors.
  2. Execute baseline benchmarks for 5 workloads: Redirect-heavy (100%), Creation-heavy (100%), Mixed (90/10), 404/Invalid, and Burst.
  3. Record environment specs, CPU, RAM, RPS, p50, p95, p99, error rate, and DB connections.
  4. Save raw CSV/JSON outputs under `benchmarks/baseline/`.

### Phase 7: Database Performance Engineering
- **Goal:** Scientifically analyze database scaling and index impact.
- **Tasks:**
  1. **Experiment A (Dataset size):** Benchmark with 10k, 100k, and 1M rows.
  2. **Experiment B (Index impact):** Benchmark with and without index on `short_code`; capture `EXPLAIN ANALYZE` output.
  3. **Experiment C (Connection pool):** Measure throughput and latency across pool sizes (5, 20, 50, 100).
  4. Publish `docs/DATABASE_OPTIMIZATION_REPORT.md`.

### Phase 8: Redis Caching & Cache Correctness
- **Goal:** Cache-aside implementation with verified hit ratios, fail-open resilience, and TTL invalidation.
- **Tasks:**
  1. Implement `CacheService` using `redis-py` async.
  2. Instrument cache hits/misses.
  3. Invalidate/update cache upon URL deactivation or update.
  4. Verify fail-open behavior: when Redis terminates, API continues serving via PostgreSQL.
  5. Benchmark cold vs warm cache, hit vs miss ratios, and hot-key traffic.

### Phase 9: Rate Limiting & Abuse Controls
- **Goal:** Predictable Redis-backed rate limiting that does not become a bottleneck.
- **Tasks:**
  1. Implement sliding window rate limiter in Redis.
  2. Enforce limits per IP; return HTTP 429 with `Retry-After` header.
  3. Measure latency overhead introduced by rate limiting.

### Phase 10: Observability & Dashboards
- **Goal:** Real-time visibility into traffic, latency, errors, and system health.
- **Tasks:**
  1. Prometheus instrumentation (`prometheus-client`) for HTTP requests, duration histograms, DB latencies, and cache metrics.
  2. Grafana dashboard JSON definitions for Traffic, Latency Percentiles, Error Rates, and Resource Utilization.
  3. Structured log enrichment with request correlation.

### Phase 11: Failure Testing & Resilience
- **Goal:** Empirically verified fault tolerance and incident recovery.
- **Tasks:**
  1. Test Redis failure during peak redirect traffic (verify fail-open to DB).
  2. Test PostgreSQL failure (verify graceful 503 response, health status degraded).
  3. Test API container restart under load (verify zero orphan connections, recovery time).
  4. Document incident reports in `docs/FAILURE_EXPERIMENTS.md`.

### Phase 12: Horizontal Scaling & Load Balancing
- **Goal:** Multi-instance deployment with Nginx reverse proxy.
- **Tasks:**
  1. Configure Nginx upstream for round-robin load balancing.
  2. Deploy 1, 2, and 4 API replicas.
  3. Run comparative scaling benchmarks; identify when scaling becomes sublinear and document the shared bottleneck.

### Phase 13: Benchmark Automation & Regression Detection
- **Goal:** Continuous performance verification.
- **Tasks:**
  1. Build automated benchmark execution script `scripts/run_benchmarks.py`.
  2. Configure CI performance regression rules (warn/fail on >15% p95 latency degradation).

### Phase 14: Security, Documentation & Release
- **Goal:** Production-grade security posture and complete public documentation.
- **Tasks:**
  1. Enforce strict URL scheme checks (prohibit `javascript:`, `file:`, localhost SSRF destinations).
  2. Run Bandit and `pip-audit`.
  3. Produce comprehensive `README.md` and operational `docs/RUNBOOK.md`.

### Phase 15: Final Benchmark Report & Resume Evidence
- **Goal:** Portfolio-ready evidence package.
- **Tasks:**
  1. Compile all benchmark data, query plans, and before/after comparisons into `docs/FINAL_BENCHMARK_REPORT.md`.
  2. Produce reproducible resume bullet points with zero fabricated figures.
