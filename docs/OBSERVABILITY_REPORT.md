# Shortify — Phase 10: Observability & Dashboards Report

**Document Version:** 1.0.0  
**Execution Date:** 2026-10-25T12:48:30Z  
**Authoritative Roadmap Phase:** Phase 10 (Observability & Dashboards)  
**Governing Standard:** `AGENTS.md` (Section 9: Observability, Security, and Scaling)  
**Core Principle:** *Instrument every vital sign; protect against label cardinality explosion; unify structured logs with Prometheus metrics and provisioned Grafana dashboards.*

---

## 1. Executive Summary

Phase 10 equips Shortify with production-grade telemetry, metrics instrumentation, and visualization infrastructure.

Key milestones achieved:
1. **Low-Cardinality Prometheus Instrumentation:** Implemented [`app/core/metrics.py`](file:///c:/Users/ARSH/Desktop/shortify/app/core/metrics.py) with 8 custom Prometheus metrics tracking HTTP volume, duration histograms (p50/p95/p99), in-flight concurrency, HTTP errors, domain URL operations, Redis cache hit/miss behavior, database latency, and rate-limiting rejections.
2. **Cardinality Explosion Defense:** Built route normalization converting high-cardinality paths (e.g. `/s0000042`, `/api/v1/urls/981/stats`) into bounded templates (`/{short_code}`, `/api/v1/urls/{id}/stats`), preventing memory exhaustion in Prometheus TSDB.
3. **Structured Request-Correlated Logs:** Every HTTP request and domain operation produces structured JSON logs incorporating correlation token (`request_id`), HTTP method, normalized path, status code, client IP, and execution latency.
4. **Provisioned Grafana Dashboard:** Authored and provisioned [`monitoring/grafana/provisioning/dashboards/shortify_overview.json`](file:///c:/Users/ARSH/Desktop/shortify/monitoring/grafana/provisioning/dashboards/shortify_overview.json) featuring 9 real-time panels for Throughput (RPS), Latency Percentiles (p50/p95/p99), Error Rate (%), Cache Hit Ratio (%), Rate Limit Rejections, and Active In-Flight Requests.
5. **Verified Live Pipeline:** Validated end-to-end data flow: Live Locust load test (576 requests) $\to$ `shortify-api:8000/metrics` $\to$ `shortify-prometheus:9090` scrape (state UP) $\to$ `shortify-grafana:3000` dashboard rendering.

---

## 2. Telemetry Architecture & Data Flow

```
+───────────────────────────────────────────────────────────────────────────+
|                               SHORTIFY STACK                              |
+───────────────────────────────────────────────────────────────────────────+
  Clients / Locust Traffic
            │
            ▼
    [FastAPI Application :8000]
            │
            ├── Request Correlation Middleware (X-Request-ID, structured access log)
            ├── Prometheus Metrics Middleware (latency timer, in-flight gauge, counters)
            ├── Rate Limiting Middleware (sliding-window rejection tracking)
            └── Endpoints / Core Services (cache hit/miss, DB query timing)
            │
            ▼ (Exposes GET /metrics)
    [Prometheus Server :9090] (Scrapes every 5s; target: api:8000/metrics)
            │
            ▼ (PromQL Evaluation)
    [Grafana Server :3000] (Auto-provisioned Shortify Service Overview Dashboard)
```

---

## 3. Metrics Catalog & Schema

All metrics are exposed under the standard Prometheus exposition format at `GET /metrics`:

| Metric Name | Type | Labels | Description / Usage |
| :--- | :---: | :--- | :--- |
| **`shortify_http_requests_total`** | Counter | `method`, `endpoint`, `status` | Total volume of HTTP requests served |
| **`shortify_http_request_duration_seconds`** | Histogram | `method`, `endpoint` | Execution latency with buckets from 1ms to 10s |
| **`shortify_http_errors_total`** | Counter | `method`, `endpoint`, `status` | Count of 4xx and 5xx client/server errors |
| **`shortify_in_flight_requests`** | Gauge | *None* | Real-time gauge of currently executing requests |
| **`shortify_url_operations_total`** | Counter | `operation` (`create`, `redirect`, `delete`, `stats`) | Core URL shortening business actions |
| **`shortify_cache_operations_total`** | Counter | `operation` (`get`, `set`, `delete`), `result` (`hit`, `miss`, `error`) | Redis Cache-Aside hit and miss dynamics |
| **`shortify_rate_limit_rejections_total`**| Counter | `bucket` (`create`, `general`) | Count of HTTP 429 rate limit interventions |
| **`shortify_db_query_duration_seconds`** | Histogram | `query_type` | Database query execution latency |

---

## 4. Route Normalization Strategy

To protect Prometheus memory against cardinality explosion, [`app/core/metrics.py`](file:///c:/Users/ARSH/Desktop/shortify/app/core/metrics.py) maps raw paths before labeling:

```python
def normalize_endpoint(path: str) -> str:
    if not path or path == "/":
        return "/"
    if path in ("/health", "/ready", "/metrics"):
        return path
    if path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json":
        return "/docs"
    if RE_URL_STATS.match(path):
        return "/api/v1/urls/{id}/stats"
    if RE_URL_DETAIL.match(path):
        return "/api/v1/urls/{id}"
    if path.startswith("/api/v1/urls"):
        return "/api/v1/urls"
    if RE_REDIRECT.match(path):
        return "/{short_code}"
    return "other"
```

*Verification:* Paths like `/s0000042` and `/viral-link-2026` are collapsed into `/{short_code}`, bounding total label combinations to less than 15 distinct strings.

---

## 5. Grafana Dashboard Specification

- **Dashboard Title:** `Shortify / Service Overview`
- **Dashboard UID:** `shortify-service-overview`
- **Auto-Refresh:** 5 seconds
- **Provisioning Location:** [`monitoring/grafana/provisioning/dashboards/shortify_overview.json`](file:///c:/Users/ARSH/Desktop/shortify/monitoring/grafana/provisioning/dashboards/shortify_overview.json)

### Configured Panels & PromQL Queries
1. **HTTP Error Rate (%):**
   ```promql
   (sum(rate(shortify_http_requests_total{status=~"[45].."}[1m])) / (sum(rate(shortify_http_requests_total[1m])) + 0.0001)) * 100
   ```
2. **Redis Cache Hit Ratio (%):**
   ```promql
   (sum(rate(shortify_cache_operations_total{operation="get",result="hit"}[1m])) / (sum(rate(shortify_cache_operations_total{operation="get"}[1m])) + 0.0001)) * 100
   ```
3. **Total Request Rate (RPS):**
   ```promql
   sum(rate(shortify_http_requests_total[1m]))
   ```
4. **Active In-Flight Requests:**
   ```promql
   shortify_in_flight_requests
   ```
5. **Throughput by Normalized Endpoint (RPS):**
   ```promql
   sum(rate(shortify_http_requests_total[1m])) by (endpoint)
   ```
6. **Latency Percentiles (p50, p95, p99 ms):**
   ```promql
   histogram_quantile(0.50, sum(rate(shortify_http_request_duration_seconds_bucket[1m])) by (le)) * 1000
   histogram_quantile(0.95, sum(rate(shortify_http_request_duration_seconds_bucket[1m])) by (le)) * 1000
   histogram_quantile(0.99, sum(rate(shortify_http_request_duration_seconds_bucket[1m])) by (le)) * 1000
   ```
7. **Redis Cache Operations Rate:**
   ```promql
   sum(rate(shortify_cache_operations_total[1m])) by (result)
   ```
8. **Rate Limit Rejections (429 Rate):**
   ```promql
   sum(rate(shortify_rate_limit_rejections_total[1m])) by (bucket)
   ```
9. **URL Domain Operations Rate:**
   ```promql
   sum(rate(shortify_url_operations_total[1m])) by (operation)
   ```

---

## 6. Empirical Verification & Quality Gates

### 6.1 Automated Test Suite
All 5 dedicated integration tests in [`tests/integration/test_observability.py`](file:///c:/Users/ARSH/Desktop/shortify/tests/integration/test_observability.py) passed:
- `test_endpoint_normalization`: Verified regex-based cardinality reduction.
- `test_metrics_endpoint_returns_prometheus_format`: Verified standard HELP/TYPE text exposition.
- `test_metrics_track_request_lifecycle`: Verified counter increments on URL creation and redirection.
- `test_metrics_track_rate_limit_rejections`: Verified counter increments on HTTP 429 interventions.
- `test_root_endpoint_includes_metrics_url`: Verified root service discovery includes `/metrics`.

*Overall Project Test Suite:* **55 passed, 0 failed in 9.21s** (100% pass rate).

### 6.2 Live Pipeline Evidence
1. **Live Traffic Generation:** Executed 576 redirect requests via Locust (`MultiClientRedirectUser`).
2. **Scrape Output Inspection:**
   ```
   shortify_http_requests_total{endpoint="/{short_code}",method="GET",status="307"} 576.0
   ```
3. **Prometheus Target API:**
   `GET http://localhost:9090/api/v1/targets` returned:
   ```json
   { "job": "shortify-api", "health": "up", "lastScrapeDuration": 0.0061, "scrapeUrl": "http://api:8000/metrics" }
   ```
4. **Grafana Dashboard API:**
   `GET http://localhost:3000/api/dashboards/uid/shortify-service-overview` returned HTTP 200 OK with status `version: 1` and all 9 configured panels.

---

## 7. Human Verification Guide (MT-004)

To visually inspect the real-time Grafana dashboard during traffic:
1. Open your browser and navigate to `http://localhost:3000`.
2. Login credentials:
   - **Username:** `admin`
   - **Password:** `admin`
3. Click on **Dashboards** $\to$ **Shortify** $\to$ **Shortify / Service Overview**.
4. Observe the live panels updating every 5 seconds under load.
