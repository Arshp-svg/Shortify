# Shortify — Performance Regression Comparison Report

**Status:** **PASSED (NO REGRESSION)**  
**Baseline Commit:** `a303895` | **Current Commit:** `a303895`  

| Scenario | Status | Baseline RPS | Current RPS | RPS Delta | Baseline p95 | Current p95 | p95 Delta | Baseline p99 | Current p99 | p99 Delta | Errors |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `redirect` | **PASSED** | 432.8 | 432.8 | -0.0% | 130.0ms | 130.0ms | 0.0% | 160.0ms | 160.0ms | 0.0% | 0.00% |
| `create` | **PASSED** | 363.6 | 363.6 | -0.0% | 140.0ms | 140.0ms | 0.0% | 160.0ms | 160.0ms | 0.0% | 0.00% |
| `mixed` | **PASSED** | 406.4 | 406.4 | -0.0% | 140.0ms | 140.0ms | 0.0% | 160.0ms | 160.0ms | 0.0% | 0.00% |
| `invalid` | **PASSED** | 520.9 | 520.9 | -0.0% | 99.0ms | 99.0ms | 0.0% | 110.0ms | 110.0ms | 0.0% | 0.00% |

All scenarios meet performance criteria: p95 within +15%, p99 within +20%, error rate <0.5%.