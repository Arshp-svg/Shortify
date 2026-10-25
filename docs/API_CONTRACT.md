# Shortify — API Contract Specification

**Version:** 1.0.0  
**Specification Protocol:** OpenAPI 3.1 compatible  
**Base URL:** `http://localhost:8000`

---

## 1. Overview & Standard Protocols

All API endpoints reside under `/api/v1/`, with the sole exception of the top-level redirection endpoint `GET /{short_code}`, which remains root-level for minimal URL length.

### Common Response Headers
Every response includes:
- `X-Request-ID`: Unique UUIDv4 or KSUID correlation identifier assigned to each HTTP request.
- `Content-Type`: `application/json` (except redirect endpoints returning `Location` headers).

### Standard Error Format
When an operation fails (4xx or 5xx), the service returns a structured JSON payload:
```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Detailed human-readable explanation of error.",
    "request_id": "0192ec51-4e89-7000-8f92-95f2a74c4e1a",
    "timestamp": "2026-10-25T12:00:00Z",
    "details": []
  }
}
```

---

## 2. Service Health & Readiness Endpoints

### 2.1 Liveness Probe
- **Method & Path:** `GET /health`
- **Description:** Verifies that the FastAPI process is responsive. Does not probe downstream dependencies.
- **Success Response:** `200 OK`
  ```json
  {
    "status": "ok"
  }
  ```

### 2.2 Readiness Probe
- **Method & Path:** `GET /ready`
- **Description:** Verifies connectivity to required backing services (PostgreSQL, Redis when enabled).
- **Success Response:** `200 OK`
  ```json
  {
    "status": "ready",
    "checks": {
      "database": "connected",
      "redis": "connected"
    }
  }
  ```
- **Failure Response:** `503 Service Unavailable`
  ```json
  {
    "status": "unready",
    "checks": {
      "database": "disconnected: connection refused",
      "redis": "connected"
    }
  }
  ```

---

## 3. URL Management Endpoints (`/api/v1/urls`)

### 3.1 Create Short URL
- **Method & Path:** `POST /api/v1/urls`
- **Description:** Creates a short URL mapping for a given original destination URL. Supports optional custom alias and optional expiration timestamp.
- **Request Headers:**
  - `Content-Type: application/json`
- **Request Body:**
  ```json
  {
    "original_url": "https://docs.fastapi.tiangolo.com/tutorial/bigger-applications/",
    "custom_alias": "fastapi-docs",
    "expires_at": "2026-12-31T23:59:59Z"
  }
  ```
  *Fields:*
  - `original_url` (string, required): Valid HTTP or HTTPS URL (max length 2048 chars).
  - `custom_alias` (string, optional): 4 to 32 characters, alphanumeric plus hyphens/underscores `^[a-zA-Z0-9_-]{4,32}$`. Cannot collide with reserved words (`health`, `ready`, `api`, `metrics`, `docs`).
  - `expires_at` (ISO 8601 UTC string, optional): Expiration time in future.
- **Responses:**
  - `201 Created`:
    ```json
    {
      "id": 1,
      "short_code": "fastapi-docs",
      "short_url": "http://localhost:8000/fastapi-docs",
      "original_url": "https://docs.fastapi.tiangolo.com/tutorial/bigger-applications/",
      "created_at": "2026-10-25T12:00:00Z",
      "expires_at": "2026-12-31T23:59:59Z",
      "click_count": 0,
      "active": true
    }
    ```
  - `400 Bad Request`: Invalid destination URL format, disallowed scheme (e.g. `javascript:`, `file:`), or past expiration timestamp.
  - `409 Conflict`: Custom alias already exists.
  - `422 Unprocessable Entity`: Request body validation failed.

---

### 3.2 Get URL Metadata
- **Method & Path:** `GET /api/v1/urls/{id}`
- **Description:** Retrieves metadata for an existing short URL record by primary ID.
- **Responses:**
  - `200 OK`: Returns URL entity payload.
  - `404 Not Found`: URL ID does not exist.

---

### 3.3 Get URL Analytics / Statistics
- **Method & Path:** `GET /api/v1/urls/{id}/stats`
- **Description:** Retrieves detailed click statistics and lifecycle state for the URL.
- **Responses:**
  - `200 OK`:
    ```json
    {
      "id": 1,
      "short_code": "fastapi-docs",
      "original_url": "https://docs.fastapi.tiangolo.com/tutorial/bigger-applications/",
      "created_at": "2026-10-25T12:00:00Z",
      "expires_at": "2026-12-31T23:59:59Z",
      "click_count": 42,
      "active": true,
      "is_expired": false
    }
    ```
  - `404 Not Found`: URL ID does not exist.

---

### 3.4 Deactivate / Delete URL
- **Method & Path:** `DELETE /api/v1/urls/{id}`
- **Description:** Soft-deactivates the short URL record (`active = false`). Subsequent redirects return 410 Gone or 404 Not Found.
- **Responses:**
  - `204 No Content`: Successfully deactivated.
  - `404 Not Found`: URL ID does not exist.

---

## 4. Redirection Endpoint (Root Level)

### 4.1 Redirect Short Code
- **Method & Path:** `GET /{short_code}`
- **Description:** Resolves short code and redirects client to original target URL.
- **Responses:**
  - `307 Temporary Redirect`:
    - Header: `Location: <original_url>`
    - Header: `Cache-Control: no-cache, no-store, must-revalidate` (preserves server-side analytics accuracy).
  - `404 Not Found`: Short code does not exist.
  - `410 Gone`: Short code exists but has expired (`expires_at < NOW()`) or has been deactivated (`active = false`).
