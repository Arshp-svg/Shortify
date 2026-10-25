# Shortify — Production-Grade URL Shortener & Backend Performance Laboratory

Shortify is a high-performance, production-grade URL shortening system and backend engineering laboratory built with FastAPI, PostgreSQL, Redis, Docker, and Prometheus/Grafana.

It is developed following an empirical engineering roadmap:  
**Build → Test → Measure → Observe → Identify Bottleneck → Change One Variable → Test Again → Measure Again → Explain the Evidence.**

---

## 1. Architecture Overview

### Baseline Architecture (Phases 0–6)
```
[Client / Load Generator]
           │
           ▼ HTTP
    [FastAPI Service]
           │
           ▼ asyncpg (Connection Pool)
    [PostgreSQL 16] (Durable Storage)
```

### Production Architecture (Phases 8–15)
```
[Clients / Locust / wrk]
           │
           ▼ HTTP:80
   [Nginx Reverse Proxy]
     ├── Round-Robin
     ├── [FastAPI Replica 1] ──┐
     ├── [FastAPI Replica 2] ──┼──► [Redis 7] (Cache-Aside + Sliding-Window Rate Limiting)
     └── [FastAPI Replica 3] ──┴──► [PostgreSQL 16] (Indexed, Connection-Pooled Storage)
                                           │
                                           ▼ Scraped by
                                 [Prometheus & Grafana]
```

---

## 2. Prerequisites

Ensure the following tools are installed on your host system:
- **Python 3.12+**
- **Docker Desktop** (Engine 20.10+ and Docker Compose v2+)
- **Git**

---

## 3. Quickstart Guide (Reproducible Start)

### Option A: Complete Docker Compose Stack (Recommended)

1. **Clone the repository and copy environment defaults:**
   ```bash
   git clone <repo-url> shortify
   cd shortify
   cp .env.example .env
   ```

2. **Start all services in background:**
   ```bash
   docker compose up -d --build
   ```

3. **Verify running services:**
   ```bash
   docker compose ps
   ```
   All services (`api`, `postgres`, `redis`, `prometheus`, `grafana`) should be `Up` or `healthy`.

4. **Test the API Health Check:**
   ```bash
   curl http://localhost:8000/health
   # Expected response: {"status":"ok"}
   ```

5. **Access Observability Dashboards:**
   - **FastAPI OpenAPI Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Prometheus Metrics:** [http://localhost:8000/metrics](http://localhost:8000/metrics)
   - **Prometheus UI:** [http://localhost:9090](http://localhost:9090)
   - **Grafana Dashboard:** [http://localhost:3000](http://localhost:3000) *(User: `admin`, Pass: `admin`)*

---

### Option B: Local Python Development

1. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

3. **Start PostgreSQL & Redis backing services via Docker:**
   ```bash
   docker compose up -d postgres redis
   ```

4. **Run migrations:**
   ```bash
   alembic upgrade head
   ```

5. **Start development server:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## 4. Developer Commands & Automation

Cross-platform developer commands are provided via `Makefile` (Linux/macOS) and `scripts/runner.ps1` (Windows):

| Action | Makefile | Windows PowerShell | Description |
| :--- | :--- | :--- | :--- |
| **Install** | `make install` | `.\scripts\runner.ps1 install` | Install package in editable mode with dev tools |
| **Run API** | `make run` | `.\scripts\runner.ps1 run` | Start FastAPI server with live reload |
| **Test** | `make test` | `.\scripts\runner.ps1 test` | Run pytest unit and integration test suite |
| **Lint** | `make lint` | `.\scripts\runner.ps1 lint` | Execute Ruff linter |
| **Format** | `make format` | `.\scripts\runner.ps1 format` | Verify Ruff code formatting |
| **Typecheck**| `make typecheck` | `.\scripts\runner.ps1 typecheck` | Execute mypy strict type checks |
| **Security** | `make security` | `.\scripts\runner.ps1 security` | Execute Bandit and pip-audit scans |
| **Load Test**| `make load-test` | `.\scripts\runner.ps1 load-test`| Execute Locust load test in headless mode |
| **Stack Up** | `make up` | `.\scripts\runner.ps1 up` | Start full Docker Compose stack |
| **Stack Down**| `make down` | `.\scripts\runner.ps1 down` | Terminate Docker Compose services |
| **Clean** | `make clean` | `.\scripts\runner.ps1 clean` | Remove cache files and build artifacts |

---

## 5. Repository Structure

```
shortify/
├── app/                  # Application core, API, models, repositories, schemas, services
├── tests/                # Unit, integration, contract, and resilience test suites
├── load_tests/           # Locust load testing scenarios
├── benchmarks/           # Raw benchmark metrics, plans, and reports across phases
├── monitoring/           # Prometheus and Grafana provisioning & dashboard configurations
├── migrations/           # Alembic database migrations
├── scripts/              # Automation, database seeding, and benchmarking scripts
├── docs/                 # Authoritative project tracking and architecture documentation
├── docker-compose.yml    # Multi-service local and benchmark orchestration
├── Dockerfile            # Multi-stage production container build
├── pyproject.toml        # Pinned dependencies, Ruff, mypy, and pytest configuration
└── README.md             # Project documentation and reproduction guide
```

---

## 6. Engineering Documentation & Status

- [Project Baseline Audit](docs/PROJECT_AUDIT.md)
- [Requirement Traceability Matrix](docs/TRACEABILITY_MATRIX.md)
- [Implementation Plan](docs/IMPLEMENTATION_PLAN.md)
- [Phase Progress Tracker](docs/PHASE_TRACKER.md)
- [Test Strategy & Quality Gates](docs/TEST_STRATEGY.md)
- [Manual Test Plan & Human Verification Log](docs/MANUAL_TEST_PLAN.md)
