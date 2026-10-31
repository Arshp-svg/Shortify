# Shortify — Production Operations Runbook

**Authoritative Specification:** `Shortify_Project_1_Engineering_Roadmap.pdf` (Phase 14)  
**Governing Standard:** `AGENTS.md`  
**Version:** `1.0.0`  
**Last Updated:** 2026-10-31  

---

## 1. System Overview & Architecture

Shortify is a high-performance URL shortener and backend engineering laboratory designed for resilience, horizontal scalability, and sub-millisecond redirect latency.

```
Ingress Traffic (HTTP :8000)
       │
       ▼
Nginx Reverse Proxy & Load Balancer (Round-Robin)
       ├──► FastAPI Instance 1 ──┐
       ├──► FastAPI Instance 2 ──┼──► Redis 7 (Cache-Aside & Rate Limiting)
       └──► FastAPI Instance N ──┴──► PostgreSQL 16 (Durable ACID Storage)
```

- **Reverse Proxy:** Nginx 1.27 (`nginx/nginx.conf`)
- **Application:** FastAPI + Uvicorn + Pydantic v2 (Async, Stateless)
- **Primary Database:** PostgreSQL 16 Alpine (`pg_stat_statements` enabled)
- **Cache & Rate Limiter:** Redis 7 Alpine (`appendonly yes`)
- **Observability:** Prometheus 2.54 (`:9090`) + Grafana 11.2 (`:3000`)

---

## 2. Cold-Start Deployment Procedure

### Prerequisites
- Docker Engine $\ge 24.0$ & Docker Compose $\ge 2.20$
- Ports available on host: `8000` (Nginx), `5432` (PostgreSQL), `6379` (Redis), `9090` (Prometheus), `3000` (Grafana).

### Step-by-Step Launch
1. **Clone repository and configure environment:**
   ```bash
   cp .env.example .env
   ```
2. **Build images and launch multi-replica stack:**
   ```bash
   docker compose -f docker-compose.scaling.yml up -d --build --scale api=2
   ```
3. **Verify container health:**
   ```bash
   docker compose -f docker-compose.scaling.yml ps
   ```
   *All services (`shortify-nginx`, `shortify-api-1`, `shortify-api-2`, `shortify-postgres`, `shortify-redis`) must display `Up (healthy)`.*

4. **Verify application health and readiness:**
   ```bash
   curl -f http://localhost:8000/health
   # Expected: {"status": "ok"}

   curl -f http://localhost:8000/ready
   # Expected: {"status": "ready", "checks": {"database": "connected", "redis": "healthy"}}
   ```

5. **Apply Database Migrations:**
   ```bash
   docker compose -f docker-compose.scaling.yml exec -T api alembic upgrade head
   ```

---

## 3. Database Administration & Backup/Restore

### A. Database Backup (pg_dump)
To take a point-in-time logical backup of the PostgreSQL database:
```bash
# Create backups directory
mkdir -p backups

# Perform compressed custom-format dump
docker compose exec -T postgres pg_dump -U postgres -d shortify -Fc > backups/shortify_backup_$(date +%Y%m%d_%H%M%S).dump
```

### B. Database Restore (pg_restore)
To restore from an existing backup dump:
```bash
# Terminate existing connections and drop active schema
docker compose exec -T postgres psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS shortify;"
docker compose exec -T postgres psql -U postgres -d postgres -c "CREATE DATABASE shortify;"

# Restore schema and data
docker compose exec -T postgres pg_restore -U postgres -d shortify -c < backups/shortify_backup_TARGET.dump
```

---

## 4. Scaling API Replicas Dynamically

Shortify API instances are completely stateless; all session, rate-limiting, and cache state is shared across Redis and PostgreSQL.

### Scale Up to 4 Replicas
```bash
docker compose -f docker-compose.scaling.yml up -d --scale api=4
docker compose -f docker-compose.scaling.yml restart nginx
```
*Restarting Nginx updates the upstream DNS pool to immediately round-robin across all 4 container IPs.*

### Scale Down to 2 Replicas
```bash
docker compose -f docker-compose.scaling.yml up -d --scale api=2
docker compose -f docker-compose.scaling.yml restart nginx
```

---

## 5. Cache & Rate Limit Operations (Redis)

### Inspect Redis Status
```bash
docker compose exec redis redis-cli info memory
docker compose exec redis redis-cli info stats
```

### Flush Cache (Emergency Cache Invalidation)
In the event of corrupted cache keys or inconsistent states:
```bash
# Flush only database 0 (application cache & rate limit keys)
docker compose exec redis redis-cli -n 0 FLUSHDB
```
*Note: Shortify will automatically fail-open to PostgreSQL without returning 500 errors.*

---

## 6. Observability & Dashboards

- **Prometheus UI:** `http://localhost:9090`
  - Core queries:
    - Rate per second: `rate(shortify_http_requests_total[1m])`
    - p95 Latency: `histogram_quantile(0.95, sum(rate(shortify_http_request_duration_seconds_bucket[1m])) by (le))`
    - Cache Hit Ratio: `sum(rate(shortify_cache_hits_total[1m])) / (sum(rate(shortify_cache_hits_total[1m])) + sum(rate(shortify_cache_misses_total[1m])))`
- **Grafana UI:** `http://localhost:3000`
  - Default credentials: `admin` / `admin`
  - Pre-provisioned dashboard: **Shortify / Service Overview**

---

## 7. Incident Response & Troubleshooting Runbook

| Symptom | Root Cause Diagnosis | Remediation Procedure |
| :--- | :--- | :--- |
| **HTTP 503 on `/ready`** | Database or Redis container offline. | Run `docker compose ps`. Check logs: `docker compose logs postgres` or `docker compose logs redis`. Restart service. |
| **HTTP 429 Too Many Requests** | Client IP exceeded sliding-window rate limit (default: 120 req/min). | Client must honor `Retry-After` header. To adjust limit, modify `RATE_LIMIT_REQUESTS_PER_MINUTE` in `.env` and restart. |
| **`TooManyConnectionsError`** | PostgreSQL `max_connections` reached by concurrent API connection pools. | Ensure `max_connections=200` in `docker-compose.scaling.yml`. Inspect active connections: `SELECT count(*) FROM pg_stat_activity;`. |
| **Nginx returning 502 Bad Gateway** | API replicas crashed or still starting up. | Inspect replica health: `docker compose logs api`. Ensure healthcheck passes before Nginx routes traffic. |

---

## 8. Rollback Runbook

If a new deployment or migration causes regressions:
1. **Rollback Application Containers:**
   ```bash
   git checkout <PREVIOUS_STABLE_COMMIT_OR_TAG>
   docker compose -f docker-compose.scaling.yml up -d --build --scale api=2
   ```
2. **Rollback Database Migration (if required):**
   ```bash
   docker compose exec api alembic downgrade -1
   ```
3. **Verify System Restoration:**
   ```bash
   curl -f http://localhost:8000/ready
   pytest tests/
   ```
