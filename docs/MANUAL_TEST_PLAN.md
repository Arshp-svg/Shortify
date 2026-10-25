# Shortify — Manual Test Plan & Human Verification Log

**Authoritative Specification:** `Shortify_Project_1_Engineering_Roadmap.pdf`  
**Governing Standard:** `AGENTS.md`  
**Status Policy:** *No manual test may be marked `MANUALLY VERIFIED` without documented user observations or attached evidence.*

---

## 1. Overview & Verification Protocol

Certain operational, visual, and deployment behaviors cannot be fully verified autonomously by an agent (e.g., launching desktop services, visual inspection of Grafana dashboards, external browser clicks, external cloud deployments).

This document catalogs all tests requiring human verification or interactive execution.

---

## 2. Manual Test Cases

### MT-001: Local Docker Desktop Environment Verification
- **Test ID:** `MT-001`
- **Objective:** Verify that Docker Desktop engine is running and able to spawn Linux containers.
- **Preconditions:** Docker Desktop is installed on the host machine.
- **Step-by-Step Instructions:**
  1. Open the **Docker Desktop** application from the Windows Start menu.
  2. Wait until the status icon in the bottom-left turns green ("Engine running").
  3. Open a terminal / PowerShell window and execute:
     ```powershell
     docker info
     ```
- **Expected Result:** Docker engine information is returned showing running Linux containers and server version.
- **Pass/Fail Criteria:** Pass if `docker info` exits with code 0.
- **Evidence to Capture:** Console output of `docker info` or confirmation of Docker status.
- **Cleanup / Recovery:** N/A.
- **User Observed Result:** Docker Desktop successfully started. `docker info --format '{{.ServerVersion}}'` returned `29.6.1`.
- **User Evidence:** ServerVersion: 29.6.1, build 8900f1d, Docker Desktop Linux Engine responsive.
- **Status:** `LOCALLY VERIFIED`

---

### MT-002: Multi-Container Stack Startup (`docker compose`)
- **Test ID:** `MT-002`
- **Objective:** Verify that the full Shortify local stack (API, PostgreSQL, Redis, Prometheus, Grafana) starts cleanly from cold state.
- **Preconditions:** Docker Desktop is running (MT-001 passed); repository configuration files present.
- **Step-by-Step Instructions:**
  1. Navigate to the project root in terminal.
  2. Run:
     ```powershell
     docker compose up -d --build
     docker compose ps
     ```
  3. Verify all 5 containers show state `Up` or `healthy`.
- **Expected Result:** All services (`api`, `postgres`, `redis`, `prometheus`, `grafana`) start without crashing.
- **Pass/Fail Criteria:** All containers reach `healthy` / `running` status.
- **Evidence to Capture:** Output of `docker compose ps`.
- **Cleanup / Recovery:** `docker compose down -v`
- **User Observed Result:** `[PENDING USER EXECUTION]`
- **User Evidence:** `[PENDING]`
- **Status:** `NOT TESTED`

---

### MT-003: Fresh Clone Bootstrap Verification
- **Test ID:** `MT-003`
- **Objective:** Confirm that an external engineer can clone the repository and start the application using only the documented setup instructions in `README.md`.
- **Preconditions:** Clean directory outside the current workspace.
- **Step-by-Step Instructions:**
  1. Open terminal in a temporary directory (`C:\Users\ARSH\AppData\Local\Temp\shortify-test`).
  2. Execute:
     ```powershell
     git clone <repo-path> .
     cp .env.example .env
     docker compose up -d
     curl http://localhost:8000/health
     ```
- **Expected Result:** API responds with `{"status": "ok"}` on port 8000.
- **Pass/Fail Criteria:** Zero undocumented steps or hidden prerequisites required.
- **Evidence to Capture:** Curl response and command logs.
- **Cleanup / Recovery:** Remove temporary test directory and stop containers.
- **User Observed Result:** `[PENDING USER EXECUTION]`
- **User Evidence:** `[PENDING]`
- **Status:** `NOT TESTED`

---

### MT-004: Grafana & Prometheus Dashboard Visual Inspection
- **Test ID:** `MT-004`
- **Objective:** Visually inspect that Grafana dashboards render real-time request rates, latency percentiles, error rates, and cache hit ratios during traffic.
- **Preconditions:** Stack is running; traffic generator or locust test is executing.
- **Step-by-Step Instructions:**
  1. Open browser and navigate to `http://localhost:3000` (Grafana).
  2. Log in with credentials from `.env` (`admin` / configured password).
  3. Open dashboard **Shortify / Service Overview**.
  4. Confirm panels render graphs for:
     - RPS / Request Rate
     - Latency (p50, p95, p99)
     - Error rate
     - Redis Cache Hit Ratio
- **Expected Result:** Dashboard shows non-zero, live data updating every 5–10 seconds.
- **Pass/Fail Criteria:** Graphs render without query errors or broken panel messages.
- **Evidence to Capture:** Screenshot of Grafana dashboard under load.
- **Cleanup / Recovery:** None.
- **User Observed Result:** `[PENDING USER EXECUTION]`
- **User Evidence:** `[PENDING]`
- **Status:** `NOT TESTED`

---

### MT-005: Resilience Chaos Injection — Redis Outage Under Live Traffic
- **Test ID:** `MT-005`
- **Objective:** Verify system fail-open behavior when Redis container is stopped during an active load test.
- **Preconditions:** Locust load test is generating redirect traffic at ~200 RPS.
- **Step-by-Step Instructions:**
  1. While load test is active, run:
     ```powershell
     docker compose stop redis
     ```
  2. Observe client responses in Locust web UI (`http://localhost:8089`).
  3. Confirm redirect requests continue to succeed (status 307) via PostgreSQL fallback.
  4. Restart Redis:
     ```powershell
     docker compose start redis
     ```
  5. Confirm cache starts populating again and latency recovers.
- **Expected Result:** Client-visible error rate remains 0% or within SLT (<0.1%); p95 latency increases during outage but recovers after restart.
- **Pass/Fail Criteria:** Zero 500 Internal Server Errors returned to clients.
- **Evidence to Capture:** Locust failure graph and terminal recovery log.
- **Cleanup / Recovery:** Ensure all containers running.
- **User Observed Result:** `[PENDING USER EXECUTION]`
- **User Evidence:** `[PENDING]`
- **Status:** `NOT TESTED`

---

### MT-006: End-to-End Browser Redirection Verification
- **Test ID:** `MT-006`
- **Objective:** Verify human user experience when visiting a short URL in a standard web browser (Chrome / Edge / Firefox).
- **Preconditions:** Shortify API is running; a test short URL has been generated pointing to `https://fastapi.tiangolo.com`.
- **Step-by-Step Instructions:**
  1. Open Chrome or Edge.
  2. In the URL address bar, enter `http://localhost:8000/<short_code>`.
  3. Hit Enter and observe browser address bar and loaded page.
  4. Verify redirect arrives at `https://fastapi.tiangolo.com`.
  5. Check `GET /api/v1/urls/<id>/stats` to confirm `click_count` incremented by 1.
- **Expected Result:** Seamless HTTP redirect to destination; click count incremented.
- **Pass/Fail Criteria:** Redirect functions in modern browser without TLS or header errors.
- **Evidence to Capture:** Browser address bar final destination and stats JSON payload.
- **Cleanup / Recovery:** N/A.
- **User Observed Result:** `[PENDING USER EXECUTION]`
- **User Evidence:** `[PENDING]`
- **Status:** `NOT TESTED`
