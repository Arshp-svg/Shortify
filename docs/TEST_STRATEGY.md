# Shortify — Test Strategy & Quality Gates

**Authoritative Specification:** `Shortify_Project_1_Engineering_Roadmap.pdf`  
**Governing Standard:** `AGENTS.md`  
**Core Principle:** *Every claim requires empirical proof. Correctness precedes performance. Regression tests accompany every bug fix.*

---

## 1. Objectives & Testing Philosophy

Shortify employs a layered test pyramid designed to catch defects at the lowest possible layer before they propagate to production or degrade benchmark accuracy. 

Key tenets:
1. **Real Infrastructure for Integration Tests:** SQLite is explicitly forbidden for PostgreSQL-specific integration tests. All persistence tests run against real PostgreSQL instances (via Docker or local test database) to validate actual SQL dialects, constraints, and locking behaviors.
2. **Explicit Concurrency Verification:** Multi-threaded and multi-task race conditions (e.g. concurrent custom alias claims, simultaneous click counts) must be tested with automated race-condition tests.
3. **Resilience by Verification:** Failures in upstream or downstream dependencies (Redis down, PostgreSQL down, saturated pool) are tested proactively via scripted fault-injection suites.
4. **Reproducible Benchmarks:** Load tests must record hardware, commit SHA, warmup period, duration, RPS, latency percentiles (p50, p95, p99), error rates, and load generator resource usage.

---

## 2. Test Pyramid & Layers

```
                       ┌───────────────────────┐
                       │     Resilience &      │
                       │   Chaos Experiments   │
                       ├───────────────────────┤
                       │  Load & Benchmarking  │
                       │   (Locust / wrk2)     │
                       ├───────────────────────┤
                       │ API Contract & Smoke  │
                       │  (Postman / Newman)   │
                       ├───────────────────────┤
                       │  Integration Tests    │
                       │ (FastAPI + Real PG)   │
                       ├───────────────────────┤
                       │      Unit Tests       │
                       │ (Domain Logic/Base62) │
                       └───────────────────────┘
```

### Layer 1: Unit Tests (`tests/unit/`)
- **Scope:** Pure functions, domain services, URL validation algorithms, Base62 encoders, Pydantic schemas, and utility functions.
- **Dependencies:** In-memory, mocked I/O, zero external network or database calls.
- **Execution Target:** Sub-second execution for fast developer iteration.
- **Key Test Cases:**
  - `test_base62.py`: Encode/decode integers, collision-resistant random string generator, alphabet distribution.
  - `test_schemas.py`: URL format validation, scheme validation (`http`/`https` allowed; `javascript:`, `file:`, `data:` rejected), custom alias regex constraints.
  - `test_url_service.py`: Expiration computation, domain validation, soft-delete state transitions.
  - `test_rate_limiter.py`: Sliding window algorithm logic.

### Layer 2: Integration Tests (`tests/integration/`)
- **Scope:** Full FastAPI request lifecycle interacting with live PostgreSQL and Redis instances.
- **Dependencies:** Real PostgreSQL 16+ and Redis 7+.
- **Key Test Cases:**
  - `test_api_urls.py`: POST `/api/v1/urls` creates record, persists in DB, returns correct payload.
  - `test_redirect.py`: GET `/{short_code}` redirects with 307 to original URL, records click increment.
  - `test_concurrency.py`: 50 concurrent requests attempting to claim the exact same custom alias; verifies database unique constraint triggers and application safely returns 409 Conflict.
  - `test_click_counter.py`: 100 concurrent redirects to the same URL; verifies database atomic increment results in exact `click_count == 100`.
  - `test_cache_aside.py`: First redirect triggers cache miss + DB lookup + Redis SET; subsequent redirects hit Redis directly; URL deactivation invalidates cache.

### Layer 3: Contract & Smoke Tests (`tests/contract/`)
- **Scope:** Validation against the OpenAPI 3.1 specification using Postman / Newman.
- **Key Test Cases:**
  - Schema conformity for all response payloads.
  - Health check (`GET /health`) returns 200 `{"status": "ok"}`.
  - Readiness check (`GET /ready`) verifies database and cache connectivity.
  - Standard error format validation across 400, 404, 409, 410, 422, 500.

### Layer 4: Load & Performance Benchmarks (`load_tests/`)
- **Scope:** System throughput, latency distributions, and saturation limits under controlled workloads.
- **Tooling:** Locust (for complex user workflows) and wrk/wrk2 (for raw endpoint throughput).
- **Workload Profiles:**
  1. *Redirect-Heavy:* 100% redirect queries against existing URLs.
  2. *Creation-Heavy:* 100% URL creations with distinct long URLs.
  3. *Mixed Workload:* 90% redirects, 10% creations.
  4. *404 Traffic:* High volume requests for non-existent short codes.
  5. *Burst Traffic:* Sudden spikes in concurrency to test connection pooling and queueing.

### Layer 5: Resilience & Chaos Testing (`tests/resilience/`)
- **Scope:** Verifying system behavior when dependencies degrade or terminate.
- **Scenarios:**
  1. *Redis Outage:* Kill Redis container while running redirect workload. System must fail-open to PostgreSQL without returning 500 errors to clients.
  2. *PostgreSQL Outage:* Stop PostgreSQL. API `/ready` check must return 503; requests return clean JSON error.
  3. *API Replica Restart:* Gracefully terminate an API replica under load; Nginx must reroute traffic without dropped connections.

---

## 3. Static Quality Gates

All code committed to the repository must satisfy the following automated quality checks:

| Gate | Tool | Command | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **Linting & Formatting** | Ruff | `ruff check app tests` <br> `ruff format --check app tests` | Zero warnings, zero formatting discrepancies |
| **Type Checking** | mypy | `mypy app` | Strict mode enabled, zero type errors |
| **Unit & Integration Tests** | pytest | `pytest tests/unit tests/integration -v` | 100% test pass rate |
| **Security Scanning** | Bandit | `bandit -r app` | Zero medium or high severity vulnerabilities |
| **Dependency Auditing** | pip-audit | `pip-audit` | Zero known CVEs in installed dependencies |

---

## 4. Test Execution Commands

```bash
# Run unit tests only
pytest tests/unit -v

# Run integration tests (requires PostgreSQL & Redis)
pytest tests/integration -v

# Run full test suite with coverage report
pytest --cov=app --cov-report=term-missing tests/

# Execute Ruff lint and format check
ruff check app tests
ruff format --check app tests

# Execute strict type checking
mypy app

# Execute security static analysis
bandit -r app
```
