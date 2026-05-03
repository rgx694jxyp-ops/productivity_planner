# 09 — Performance & Observability: Current State

> Assessment of logging, error tracking, operational events, and performance profiling.

---

## Overview

The app has a well-designed observability stack for a Streamlit application, with three distinct layers:
1. **Structured JSONL application logging** — `services/app_logging.py`
2. **Operational event logging** — `services/observability.py` (thin wrapper)
3. **Performance profiling** — `services/perf_profile.py` (context manager)

All three write to local log files. There is no centralized log aggregation service (Datadog, CloudWatch, Sentry, etc.) configured.

---

## Structured JSONL Logging: `services/app_logging.py` (145 lines)

### Log File

```
logs/dpd_app.jsonl        # Application-wide structured log
```

Each entry is a newline-delimited JSON object.

### Sensitive Key Redaction

All log entries pass through `sanitize_context()` before writing:

```python
# Blocked token substrings (case-insensitive):
_REDACT_TOKENS = [
    "access_token", "api_key", "password", "secret",
    "token", "cookie", "auth", "credential", "private_key"
]
```

Values of matching keys are replaced with `"[REDACTED]"`. This is applied to both the `context` dict and free-text `message` via `sanitize_text()`.

### Log Levels / Functions

| Function | Purpose |
|----------|---------|
| `log_info(category, message, context)` | Informational events |
| `log_warn(category, message, context)` | Warning events |
| `log_error(category, message, context)` | Error events |
| `log_debug(category, message, context)` | Debug (only emitted if `DPD_DEBUG=1`) |

### Per-Tenant Operational Logs

In addition to the shared JSONL log, per-tenant text logs are written by `services/observability.py`:

```python
tenant_log_path("dpd_ops")    → logs/dpd_ops_<tenant_id>.log
tenant_log_path("dpd_audit")  → logs/dpd_audit_<tenant_id>.log
tenant_log_path("dpd_email_scheduler") → logs/dpd_email_scheduler.log
```

These are flat text logs (not JSONL), one line per event with timestamp prefix.

---

## Operational Event Logging: `services/observability.py` (70 lines)

Thin wrapper that writes to both the file logger and `database.log_error()`:

```python
log_app_error(category, message, detail, tenant_id, context)
    → app_logging.log_error(...)
    → database.log_error(...) → error_reports table

log_operational_event(event_type, payload, tenant_id)
    → app_logging.log_info(...)
    → per-tenant ops log file
```

`database.log_error()` persists to the `error_reports` Supabase table, making errors queryable per-tenant. `get_error_reports(tenant_id, limit)` and `clear_error_reports(tenant_id)` allow admin review in-app.

---

## Performance Profiling: `services/perf_profile.py` (~120 lines)

### `PerfProfile` Context Manager

```python
with PerfProfile("today_cold_start", tenant_id=tid) as prof:
    prof.mark("snapshot_check")
    # ... do work ...
    prof.mark("signal_compute")
    prof.cache_hit("today_signals")
    prof.db_query("daily_signals.select")
```

On exit, emits to `log_operational_event()` with:
- Total wall time
- Per-stage durations (ms)
- Cache hit/miss counts
- DB query counts

### `profile_block()` Context Manager

Lightweight single-stage profiler:

```python
with profile_block("import_commit", tenant_id=tid):
    orchestrator.commit_import(...)
```

---

## Today Page Milestone Logging

`pages/today.py` includes `_today_log_milestone()` for cold-start timing instrumentation:

```python
_today_log_milestone("cold_start")
_today_log_milestone("snapshot_check_done")
_today_log_milestone("signal_compute_done")
_today_log_milestone("render_start")
```

These are timestamped and logged to `log_operational_event()`, providing a per-session load timeline in the operational log.

---

## `error_reports` Table

Stores structured error reports queryable per-tenant:

```sql
id, tenant_id, category, message, detail, context (jsonb), created_at
```

- Max retention governed by `clear_error_reports()` (manual or admin-triggered)
- No automatic expiry or rotation policy
- No alerting (no email/Slack on error_reports insert)

---

## What Is Not Present

| Gap | Impact |
|-----|--------|
| No centralized log aggregation (Datadog, CloudWatch, etc.) | Logs are local files on Render ephemeral disk — lost on dyno restart |
| No error alerting / on-call integration (PagerDuty, Sentry) | Errors are silent unless someone reads `error_reports` in-app |
| No application performance monitoring (APM) | No distributed tracing, no p95/p99 latency tracking |
| No log rotation policy | `logs/dpd_app.jsonl` grows unboundedly |
| No structured metrics / dashboards (Grafana, etc.) | `perf_profile` emits to log but no time-series store |
| No health check endpoint | No `/health` route for load balancer or uptime monitoring |
| No query performance tracking (slow query log) | DB query times are approximate (counted in PerfProfile, not timed individually) |
| Logs on ephemeral filesystem | Render dyno restarts erase all local logs — `logs/` directory data is not persisted |

---

## Deployment Observability

The app is deployed on Render (inferred from `RENDER_EXTERNAL_URL` env var and `Procfile` presence). Render provides:
- Basic stdout/stderr log streaming
- Automatic dyno restart on crash

But no Render-specific observability integrations are configured (no Render log drains, no health check routes).

---

## Summary Assessment

The observability stack is thoughtful for a single-dyno Streamlit app in early stage:
- Sensitive data is protected by redaction
- Per-tenant logs enable tenant-specific debugging
- `PerfProfile` provides stage-level load timing
- `error_reports` table enables in-app error review

The primary gap is **persistence and aggregation**: all logs are local files that disappear on dyno restart, and there is no alerting path for errors. Transitioning to a production-grade platform would require adding a log drain (Papertrail, Logtail, Datadog) or writing operational events to Supabase directly.
