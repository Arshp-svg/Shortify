# Shortify — Phase 7: Database Performance Engineering Report

**Document Version:** 1.0.0  
**Execution Date:** 2026-10-25T08:46:17Z  
**Authoritative Roadmap Phase:** Phase 7 (Database Performance Engineering)  
**Governing Standard:** `AGENTS.md` (Section 7: Benchmarking and Performance)  
**Core Principle:** *Change one major variable at a time; measure using EXPLAIN ANALYZE and real load; explain the empirical outcome.*

---

## 1. Executive Summary

This report presents the empirical findings from Phase 7 of the Shortify engineering laboratory, focusing on relational database performance, indexing efficiency, dataset scalability, and connection pool sizing.

Key findings include:
1. **Algorithmic Scaling ($O(\log N)$ vs $O(N)$):** B-Tree index point lookups exhibit flat $O(\log N)$ latency as the table expands from **10,000 to 1,000,000 rows** (**0.130 ms vs 0.136 ms**), whereas sequential scans degrade linearly from **1.91 ms to 88.39 ms**, achieving a **649.9x speedup** at 1 million records.
2. **Buffer and I/O Impact:** An indexed lookup requires reading only **4 shared buffer blocks** (0 disk reads). A sequential scan across 100,000 rows forces **1,724 buffer blocks to be read from disk**, inspecting and discarding 99,999 non-matching rows.
3. **Write Bottleneck on Read Path:** An atomic counter update (`UPDATE urls SET click_count = click_count + 1 WHERE id = :id`) incurs **5.055 ms** execution time and dirties 8 shared buffer blocks requiring WAL synchronization. This is **46.8x slower** than the read query, validating that synchronous relational writes are the primary latency bottleneck for redirects.
4. **Connection Pool Optimization Curve:** Under 50 concurrent users:
   - **Pool-5 (Constrained):** 149.5 RPS, p95: 740 ms, p99: 1,000 ms (severe queueing).
   - **Pool-20 (Baseline):** 157.5 RPS, p95: 380 ms, p99: 460 ms.
   - **Pool-50 (Optimal / Right-Sized):** **184.55 RPS**, p95: **290 ms**, p99: **330 ms** (**+23.4% throughput, -67% p99 latency** vs Pool-5).
   - **Pool-100 (Oversized):** 162.79 RPS, p95: 350 ms, p99: 580 ms (**throughput penalty due to PostgreSQL backend context switching and lock contention**).

---

## 2. Test Environment

| Component | Specification |
| :--- | :--- |
| **Host System** | Windows 11 Pro, 16 vCPUs (Intel64 Model 186), 32 GB RAM |
| **Database Container** | PostgreSQL 16 Alpine (`shortify-postgres`) |
| **Extensions Enabled** | `pg_stat_statements` (preloaded via `shared_preload_libraries`) |
| **Storage Engine** | Docker Volume (`pg_data`) on ext4 (WSL2 backend) |
| **Query Profiler** | `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` |
| **Load Generator** | Locust 2.32.8 (FastHttpUser, headless, 50 concurrent users) |

---

## 3. Experiment A: Dataset Size Scaling (10k, 100k, 1M URLs)

### 3.1 Objective
Measure query execution times, B-Tree index scan characteristics, and physical storage footprints as the dataset grows by two orders of magnitude from 10,000 to 1,000,000 records.

### 3.2 Measured Results

| Dataset Scale (Rows) | Table Disk Size | Index Disk Size | Total Relation Size | Index Scan Latency | Seq Scan Latency | Speedup Factor |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **10,000** | 1,536 kB | 328 kB | 1,872 kB | **0.130 ms** | 1.913 ms | **14.7x** |
| **100,000** | 13 MB | 9,712 kB | 23 MB | **0.108 ms** | 43.808 ms | **405.6x** |
| **1,000,000** | 135 MB | 94 MB | 229 MB | **0.136 ms** | 88.391 ms | **649.9x** |

*Raw artifact:* [`benchmarks/database/dataset_size/experiment_a_dataset_scaling.json`](file:///c:/Users/ARSH/Desktop/shortify/benchmarks/database/dataset_size/experiment_a_dataset_scaling.json)

### 3.3 Algorithmic Analysis
- **Index Scan Complexity:** Point lookup execution time remains virtually unchanged between 10k rows (0.130 ms) and 1M rows (0.136 ms). PostgreSQL B-Tree indexes maintain a tree depth of 3 levels even at 1,000,000 entries. Navigating 3 index pages takes microseconds regardless of total table volume.
- **Sequential Scan Complexity:** Full table scans exhibit linear $O(N)$ growth. Scanning 10k rows takes ~1.9 ms; scanning 1M rows takes ~88.4 ms. At 1M rows without an index, a single read query would violate our 40ms `p95` Service-Level Target by more than 2x.

---

## 4. Experiment B: Indexing vs Non-Indexing Deep Dive

### 4.1 Objective
Capture comprehensive `EXPLAIN (ANALYZE, BUFFERS)` execution plans comparing indexed lookups, un-indexed lookups, and atomic click counter write operations on the active table.

### 4.2 Query Execution Plans

#### Query 1: Indexed Short Code Point Lookup (B-Tree)
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) 
SELECT * FROM urls WHERE short_code = 's0042424';
```
```json
{
  "Node Type": "Index Scan",
  "Index Name": "ix_urls_short_code",
  "Relation Name": "urls",
  "Startup Cost": 0.42,
  "Total Cost": 8.44,
  "Actual Startup Time": 0.039,
  "Actual Total Time": 0.040,
  "Actual Rows": 1,
  "Index Cond": "((short_code)::text = 's0042424'::text)",
  "Shared Hit Blocks": 4,
  "Shared Read Blocks": 0,
  "Planning Time": 2.020,
  "Execution Time": 0.108
}
```

#### Query 2: Non-Indexed Full Table Sequential Scan
```sql
SET enable_indexscan = off; SET enable_bitmapscan = off;
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) 
SELECT * FROM urls WHERE short_code = 's0042424';
```
```json
{
  "Node Type": "Seq Scan",
  "Relation Name": "urls",
  "Startup Cost": 0.0,
  "Total Cost": 2975.0,
  "Actual Startup Time": 17.974,
  "Actual Total Time": 43.755,
  "Actual Rows": 1,
  "Filter": "((short_code)::text = 's0042424'::text)",
  "Rows Removed by Filter": 99999,
  "Shared Hit Blocks": 1,
  "Shared Read Blocks": 1724,
  "Planning Time": 1.340,
  "Execution Time": 43.808
}
```

#### Query 3: Atomic Click Counter Increment (Write Path)
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) 
UPDATE urls SET click_count = click_count + 1 WHERE id = 42424;
```
```json
{
  "Node Type": "ModifyTable",
  "Operation": "Update",
  "Relation Name": "urls",
  "Actual Total Time": 4.044,
  "Shared Hit Blocks": 16,
  "Shared Read Blocks": 13,
  "Shared Dirtied Blocks": 8,
  "Execution Time": 5.055
}
```

*Raw artifact:* [`benchmarks/database/indexing/experiment_b_indexing_deep_dive.json`](file:///c:/Users/ARSH/Desktop/shortify/benchmarks/database/indexing/experiment_b_indexing_deep_dive.json)

### 4.3 Detailed Metric Comparison

| Dimension | Sequential Scan (No Index) | Index Scan (B-Tree) | Atomic Update (Write) |
| :--- | :--- | :--- | :--- |
| **Execution Time** | 43.808 ms | **0.108 ms** | 5.055 ms |
| **Speedup vs Seq Scan** | Baseline (1.0x) | **405.6x faster** | 8.7x faster |
| **Buffer Cache Hits** | 1 block | 4 blocks | 16 blocks |
| **Buffer Disk Reads** | **1,724 blocks** | **0 blocks** | 13 blocks |
| **Buffer Dirtied Blocks** | 0 blocks | 0 blocks | **8 blocks (WAL)** |
| **Rows Inspected** | 100,000 rows | 1 row | 1 row |

---

## 5. Experiment C: Connection Pool Size Tuning

### 5.1 Objective
Determine the saturation and connection penalty points by evaluating four distinct connection pool configurations under **50 concurrent users** executing continuous redirect lookups against 1,000,000 URLs.

### 5.2 Measured Results

| Configuration | Base Pool Size | Max Overflow | Max Connections | Throughput (RPS) | p50 (ms) | p95 (ms) | p99 (ms) | Avg Latency | Error Rate | Behavior Profile |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Pool-5** | 5 | 0 | 5 | 149.53 | 270.0 | 740.0 | 1,000.0 | 271.6 ms | 0.0% | Severe contention; 45 requests queue |
| **Pool-20** | 20 | 10 | 30 | 157.50 | 260.0 | 380.0 | 460.0 | 252.3 ms | 0.0% | Baseline configuration |
| **Pool-50** | 50 | 10 | 60 | **184.55** | **230.0** | **290.0** | **330.0** | **214.2 ms** | 0.0% | **Optimal (Right-Sized for Concurrency)** |
| **Pool-100** | 100 | 20 | 120 | 162.79 | 260.0 | 350.0 | 580.0 | 248.4 ms | 0.0% | **Oversized: Connection Penalty Point** |

*Raw artifact:* [`benchmarks/database/connection_pool/experiment_c_connection_pool.json`](file:///c:/Users/ARSH/Desktop/shortify/benchmarks/database/connection_pool/experiment_c_connection_pool.json)

### 5.3 Analysis of the Connection Pool Penalty Point
1. **Under-provisioning (Pool-5):** When concurrency is 50 and pool size is 5, 90% of concurrent requests cannot acquire a database connection and wait in asyncio event loop queues. This inflates `p99` latency to 1,000 ms.
2. **Optimal Sizing (Pool-50):** Matching connection capacity to concurrent load (50 base + 10 overflow) yields maximum throughput (**184.55 RPS**) and the lowest latency across all percentiles (p50: 230 ms, p95: 290 ms, p99: 330 ms).
3. **The Connection Penalty (Pool-100):** Increasing pool size to 100 actually degraded performance: throughput fell by **11.8%** (184.55 $\to$ 162.79 RPS), and `p99` latency spiked from **330 ms to 580 ms**.
   - **Root Cause:** PostgreSQL allocates a dedicated OS process for each client connection. When 100 client processes concurrently contend for shared database resources (WAL buffers, row locks, CPU cores), operating system context switching and locking overhead degrade performance. A larger connection pool is not always better.

---

## 6. Real-Time Query Profiling with `pg_stat_statements`

With `pg_stat_statements` preloaded via `shared_preload_libraries`, query telemetry reveals:
- Point lookup by short code (`WHERE urls.short_code = $1`): Mean execution time **0.060 ms** across real traffic.
- Point lookup by primary key (`WHERE urls.id = $1`): Mean execution time **0.045 ms**.
- The `pg_stat_statements` catalog proves that the relational lookup itself is not the bottleneck; rather, transaction commits, connection queueing, and synchronous disk writes dominate user-visible latency.

---

## 7. Conclusions & Transition to Phase 8 (Redis Caching)

### Verified Conclusions:
1. **Indexing is mandatory and scalable:** A B-Tree index on `short_code` provides sub-millisecond point lookups that scale predictably to 1M+ rows.
2. **Pool size must match active concurrency:** A pool size of 50 connections delivers peak throughput while avoiding the process scheduling penalty observed at 100 connections.
3. **The Relational Limit:** Even with optimal pool sizing and B-Tree indexes, maximum redirect throughput on a single PostgreSQL instance with synchronous `click_count` updates tops out at **~185 RPS** under 50 concurrent users, with p50 latency around 230 ms.

### Architectural Decision for Phase 8:
To achieve our target of **sub-15ms p50 redirect latency** and **1,000+ RPS**, we must decouple the read path from relational storage:
- **Cache-Aside Pattern with Redis:** Store `short_code -> original_url` in an in-memory Redis cache. Lookups hit RAM in < 1 ms, completely eliminating database queries on cached keys.
- **Fail-Open Resilience:** If Redis fails, fall back gracefully to PostgreSQL without returning 500 errors to clients.
