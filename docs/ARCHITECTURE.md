# Shortify — System Architecture Specification

**Specification:** `Shortify_Project_1_Engineering_Roadmap.pdf`  
**Governing Standard:** `AGENTS.md`  
**Architectural Stage:** Phase 1 Baseline Architecture

---

## 1. Architectural Philosophy: The Clean Baseline

A foundational requirement of the Shortify engineering laboratory is:
> *"Do not add Redis yet. The intentionally simple architecture gives you a clean baseline. Never claim an optimization, scale limit, or performance improvement until you have measured a baseline, recorded the test conditions, identified the bottleneck, changed one variable, and reproduced the result."*

Therefore, the system is architected in distinct evolutionary tiers:
1. **Tier 1 (Phases 0–6 Baseline):** Pure FastAPI + PostgreSQL relational persistence.
2. **Tier 2 (Phases 7–9 Optimized Storage & Caching):** B-Tree indexes, connection pool tuning, and Redis Cache-Aside.
3. **Tier 3 (Phases 10–12 Observability & Horizontal Scaling):** Prometheus/Grafana instrumentation and Nginx load-balanced replicas.

---

## 2. Baseline Architecture (Phases 0–6)

```mermaid
graph TD
    Client["Client / Load Generator<br>(Locust / wrk / Newman)"]
    
    subgraph FastAPI_App ["FastAPI Application (Single Process)"]
        Router["API Router<br>(/api/v1/urls, /{short_code})"]
        Middleware["Middleware Stack<br>(Request-ID Logging, Error Handling)"]
        Service["URL Service<br>(Business Logic, Base62, Expiration)"]
        Repo["URL Repository<br>(SQLAlchemy Async Core)"]
    end
    
    subgraph Database ["PostgreSQL 16 Engine"]
        PG_Pool["asyncpg Connection Pool<br>(size=20, max_overflow=10)"]
        PG_Table["urls Table<br>(id, short_code, original_url, active)"]
    end

    Client -->|HTTP Request| Middleware
    Middleware --> Router
    Router --> Service
    Service --> Repo
    Repo --> PG_Pool
    PG_Pool --> PG_Table
```

### Component Responsibilities

1. **Client / Load Generator:**
   - Initiates HTTP requests (`POST /api/v1/urls`, `GET /{short_code}`, `GET /health`).
   - Acts as load generator during benchmarking (Locust, wrk).

2. **Middleware Stack:**
   - **Correlation ID Middleware:** Assigns a unique `X-Request-ID` to every incoming request and injects it into structured log contexts.
   - **Central Exception Handler:** Intercepts unhandled exceptions, ensures zero leak of database stack traces, and formats standardized JSON error responses.

3. **API Router Layer (`app/api/`):**
   - Pure HTTP layer: deserializes JSON, handles FastAPI dependency injection (`get_db`, `get_url_service`), and returns typed response models.

4. **Service Layer (`app/services/`):**
   - Enforces core domain rules: validates original URLs against SSRF/malformed patterns, executes Base62 short-code generation with collision retry backoff, checks expiration timestamps, and manages soft deletion.

5. **Repository Layer (`app/repositories/`):**
   - Isolates all database operations: executes atomic click count increments (`UPDATE urls SET click_count = click_count + 1 WHERE ...`), manages transactions, and executes clean queries.

6. **Durable Persistence (`PostgreSQL 16`):**
   - Managed via SQLAlchemy 2.0 async and `asyncpg` connection pool. Enforces database-level unique constraint on `short_code`.

---

## 3. Data Flow Workflows

### 3.1 Short URL Creation Flow
```
Client ──► POST /api/v1/urls ──► URL Service
                                   │ 1. Validate original URL (scheme, length, syntax)
                                   │ 2. Check custom alias or generate Base62 code
                                   ▼
                             URL Repository ──► PostgreSQL
                                                 │ INSERT INTO urls ...
                                                 ▼
                             Response 201 Created ◄── Return URL entity
```

### 3.2 High-Throughput Redirection Flow
```
Client ──► GET /{short_code} ──► Redirect Endpoint
                                    │ 1. Query short_code from URL Repository
                                    ▼
                              PostgreSQL
                                    │ SELECT original_url, expires_at, active FROM urls...
                                    ▼
                              Validation: active == true && expires_at > NOW()
                                    │
                                    ├─ If invalid ──► Return 404 Not Found / 410 Gone
                                    └─ If valid   ──► Atomic increment click_count
                                                      Return HTTP 307 (Location: target)
```

---

## 4. Future Architecture Evolution (Phases 8–12)

```mermaid
graph LR
    Client["Clients / Locust"] -->|Port 80| Nginx["Nginx Reverse Proxy"]
    Nginx -->|Upstream| API1["API Replica 1"]
    Nginx -->|Upstream| API2["API Replica 2"]
    Nginx -->|Upstream| API3["API Replica 3"]
    
    API1 -->|Cache Aside| Redis[("Redis 7<br>(Cache + Rate Limits)")]
    API2 -->|Cache Aside| Redis
    API3 -->|Cache Aside| Redis
    
    API1 -->|asyncpg Pool| PG[("PostgreSQL 16<br>(Durable Data)")]
    API2 -->|asyncpg Pool| PG
    API3 -->|asyncpg Pool| PG
    
    Prometheus["Prometheus"] -.->|Scrape /metrics| API1
    Prometheus -.->|Scrape /metrics| API2
    Prometheus -.->|Scrape /metrics| API3
    Grafana["Grafana"] --> Prometheus
```
