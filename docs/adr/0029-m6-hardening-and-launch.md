# 29. Production hardening, security headers, and launch readiness

Date: 2026-10-31
Status: Accepted

## Context

With Milestones M0 through M5 completed, GST Copilot provides:
- Grounded statutory question answering with citation verification (M1, M2).
- Observability, streaming answers, latency optimization, and cost tracking (M3).
- Deterministic ITC reconciliation, single invoice validation, and Form GSTR-3B Table 4 compilation (M4, M4b).
- 24-hour notification freshness reporting, temporal date-aware retrieval, and prompt injection defense (M5).

Milestone M6 focuses on production hardening, lifecycle cleanliness, web client readiness, and end-to-end verification.

## Decision

### 1. Database Connection Pool Tuning & Graceful Shutdown

- Configurable SQLAlchemy async connection pool parameters in `Settings`:
  - `db_pool_size` (default: 10)
  - `db_max_overflow` (default: 10)
  - `db_pool_timeout` (default: 30.0s)
  - `pool_pre_ping=True` (preserves existing liveness checking).
- Application `lifespan`:
  - Cleanly cancels any pending warm-up tasks.
  - Calls `await get_engine().dispose()` on application shutdown, guaranteeing zero orphaned Postgres connections during deployments and container restarts.

### 2. HTTP Security Headers & CORS Middleware

- Added standard production security response headers to all API endpoints:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- Added FastAPI `CORSMiddleware` with configurable `cors_origins` (default: `["*"]` in local/dev, restrictive in production) allowing seamless browser-based frontends, desktop sidecars, and accounting portal integrations.

### 3. Standardized Unhandled Error Handling

- Global exception handler catches unhandled exceptions, logs the full exception with `request_id`, and returns a consistent JSON response:
  ```json
  {
    "detail": "An internal server error occurred.",
    "request_id": "<request_id>"
  }
  ```
  Prevents raw stack trace leakage to API consumers while keeping errors fully traceable in server logs.

### 4. End-to-End Launch Integration Test Suite

- Added `tests/test_e2e_launch.py` verifying the complete compliance journey in a single test run:
  1. `/health` & `/ready` probes.
  2. Single invoice checking (`POST /check-invoice`).
  3. Bulk purchase register vs. GSTR-2B reconciliation (`POST /reconcile`).
  4. Draft Form GSTR-3B Table 4 generation with audit links.
  5. Date-aware statutory question answering (`POST /ask` with `as_of`).
  6. Feedback submission (`POST /feedback`).

## Consequences

- Prevents connection pool leakage across rolling restarts and worker reloads.
- Protects clients with standard HTTP security headers and structured 500 error payloads.
- Verified end-to-end user compliance workflow.
