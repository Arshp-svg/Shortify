# Shortify — Database Index Performance Analysis

**Date:** 2026-10-25  
**Dataset:** 100,000 seeded URLs  
**Database Engine:** PostgreSQL 16-alpine (Docker)  
**Query:** `SELECT * FROM urls WHERE short_code = 's0054321';`

---

## 1. Experimental Methodology

The database was populated with 100,000 realistic URL records via `scripts/seed_urls.py`.  
Two query execution plans were captured using `EXPLAIN ANALYZE`:
1. **With B-Tree Unique Index (`ix_urls_short_code`):** Default PostgreSQL index scan.
2. **Without Index (Sequential Scan Simulation):** `enable_indexscan = off; enable_bitmapscan = off;`.

---

## 2. Measured Results

### Test Run 1: With B-Tree Index Scan (`ix_urls_short_code`)
```text
                                                        QUERY PLAN                                                         
---------------------------------------------------------------------------------------------------------------------------
 Index Scan using ix_urls_short_code on urls  (cost=0.42..8.44 rows=1 width=253) (actual time=0.033..0.034 rows=1 loops=1)
   Index Cond: ((short_code)::text = 's0054321'::text)
 Planning Time: 0.743 ms
 Execution Time: 0.061 ms
```

### Test Run 2: Without Index Scan (Full Table Sequential Scan)
```text
                                            QUERY PLAN                                             
---------------------------------------------------------------------------------------------------
 Seq Scan on urls  (cost=0.00..2975.00 rows=1 width=253) (actual time=2.755..4.964 rows=1 loops=1)
   Filter: ((short_code)::text = 's0054321'::text)
   Rows Removed by Filter: 99999
 Planning Time: 0.746 ms
 Execution Time: 4.987 ms
```

---

## 3. Quantitative Comparison

| Metric | Sequential Scan (No Index) | Index Scan (B-Tree) | Factor Improvement |
| :--- | :--- | :--- | :--- |
| **Scan Type** | `Seq Scan` (Table Scan) | `Index Scan` (`ix_urls_short_code`) | Direct Point Lookup |
| **Rows Inspected** | 100,000 rows | 1 row | 100,000x fewer rows |
| **Execution Time** | 4.987 ms | 0.061 ms | **81.75x Faster** |
| **Query Cost** | 2,975.00 | 8.44 | 352.5x lower estimated cost |

---

## 4. Conclusion & Architectural Validation

The B-Tree index on `short_code` reduces point lookup latency from ~5.0ms to ~0.06ms on a 100k-row table. Under high concurrency (e.g. 1,000+ RPS), sequential scans would instantly saturate CPU and exhaust the database connection pool, whereas the indexed scan executes in ~60 microseconds.
