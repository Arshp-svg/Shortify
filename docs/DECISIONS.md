# Shortify — Architectural Decision Records (ADRs)

**Specification:** `Shortify_Project_1_Engineering_Roadmap.pdf` (Phase 1)  
**Governing Standard:** `AGENTS.md`

---

## ADR-001: Short-Code Generation & Collision Handling Strategy

### Context
Shortify requires generating compact, URL-friendly identifiers for destination URLs when no custom alias is specified. High concurrency may produce duplicate code attempts.

### Decision
1. **Algorithm:** Generate a 7-character string using a Base62 alphabet (`[0-9a-zA-Z]`).
   - $62^7 \approx 3.52 \times 10^{12}$ unique permutations.
   - Generated using cryptographically secure random bytes (`secrets.choice`) rather than sequential counters to prevent enumeration and predictability.
2. **Collision Handling:**
   - Enforce an explicit database-level `UNIQUE` constraint on the `short_code` column.
   - In the service layer, implement a collision retry loop with exponential backoff (up to 3 retries) on `IntegrityError`.
   - Application-level pre-checks are intentionally acknowledged as non-atomic; the database constraint is the authoritative source of truth.

### Consequences
- **Positive:** Massive keyspace, non-guessable URLs, atomic duplicate prevention under race conditions.
- **Negative:** Rare collision retries consume an additional DB roundtrip.

---

## ADR-002: HTTP Redirection Status Code Selection (307 vs 302 vs 301)

### Context
When a client requests `GET /{short_code}`, the service must redirect the user agent to the target URL. HTTP defines `301 Moved Permanently`, `302 Found`, and `307 Temporary Redirect`.

### Decision
1. Use **`HTTP 307 Temporary Redirect`** (with fallback compatibility for `HTTP 302`).
2. Add `Cache-Control: no-cache, no-store, must-revalidate` to redirect responses.

### Rationale
- **Why NOT 301 Moved Permanently?** Browsers aggressively cache 301 responses in their local disk cache indefinitely. If 301 were used, subsequent clicks would bypass the Shortify server entirely, corrupting analytics, breaking expiration enforcement, and preventing URL deactivation.
- **Why 307 Temporary Redirect over 302?** RFC 9110 specifies that HTTP 307 guarantees that the HTTP method and request body are not altered upon redirection (e.g. `POST` stays `POST`).
- For benchmark baseline comparisons, status code configuration will be controllable via settings to measure impact.

---

## ADR-003: Expiration Semantics & Timezone Handling

### Context
Short URLs can optionally specify an expiration timestamp (`expires_at`). System clocks and timezone inconsistencies can lead to race conditions or premature link expiry.

### Decision
1. All timestamps in Shortify are stored, transmitted, and evaluated in **UTC (ISO 8601 with `Z` suffix)**.
2. The database column is typed `TIMESTAMP WITH TIME ZONE`.
3. An incoming expiration timestamp must strictly be in the future (`expires_at > NOW()`).
4. **Behavior on Expiry:**
   - When a requested short URL exists in the database but `expires_at <= NOW()`, the server returns **`HTTP 410 Gone`** rather than generic `404 Not Found`. This informs clients that the resource previously existed but has expired.

---

## ADR-004: Authentication Scope

### Context
The primary objective of Shortify is backend performance engineering, benchmarking, concurrency, and failure resilience across high-throughput scenarios.

### Decision
1. In the initial baseline phases (Phases 0–13), endpoints are **publicly accessible** without mandatory JWT/session authentication, permitting direct load testing without synthetic token generation overhead.
2. The database schema includes an optional, indexed `user_id: Optional[str]` column to support future multi-tenant authentication without requiring schema refactoring.
3. In Phase 14, API keys or optional bearer token middleware will be integrated as an optional security layer.

---

## ADR-005: Click Counter Consistency (Exact Atomic vs Eventual)

### Context
Redirect endpoints must record each access in `click_count`. High-frequency redirection creates write contention on the database row.

### Decision
1. **Baseline Phase (Phases 0–7):**
   - Use **Exact Atomic SQL Increments**:
     ```sql
     UPDATE urls SET click_count = click_count + 1 WHERE id = :id;
     ```
   - This provides immediate consistency and establishes an unoptimized database write baseline.
2. **Future Caching Phase (Phase 8+):**
   - Evaluate Redis `INCR` with background batch flushing (eventual consistency) as a documented optimization experiment.
   - Benchmark and document the throughput difference between immediate relational write vs asynchronous Redis counter flush.
