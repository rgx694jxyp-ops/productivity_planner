# 02 — Database & Data Model

> All 25+ tables mapped to their migration origin, purpose, key columns, and future platform object.

---

## Overview

- **Database:** Supabase (managed PostgreSQL)
- **Auth enforcement:** Row-Level Security (RLS) on every tenant-scoped table via `get_my_tenant_id()` Postgres function reading the JWT claim
- **Migration files:** 19 SQL files in `migrations/` (001–019); some migration numbers have multiple files (003 has three variants)
- **Tenant isolation:** `tenant_id UUID NOT NULL` foreign key on every data table referencing `tenants(id)`

---

## Table Inventory

### Core Tenant & Identity (Migration 001)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `tenants` | Tenant registry — one row per paying account | `id (uuid PK)`, `name`, `invite_code`, `stripe_customer_id` |
| `user_profiles` | Links `auth.users` → tenant; stores role | `id (uuid)`, `tenant_id`, `role (viewer/manager/admin)`, `name` |

**Note:** Migration 018 normalized `"member"` role → `"manager"`. Legacy alias handled in `access_control_service._LEGACY_ALIASES`.

---

### Workforce & Orders (Migration 001)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `employees` | Employee roster | `id`, `tenant_id`, `emp_id (text)`, `name`, `department`, `shift`, `is_new (bool)` |
| `clients` | Customer/client accounts | `id`, `tenant_id`, `name`, `contact`, `email`, `notes` |
| `orders` | Work orders against clients | `id`, `tenant_id`, `client_id`, `order_number`, `description`, `total_units`, `status`, `target_date` |
| `order_assignments` | Employee-to-order mapping | `id`, `tenant_id`, `order_id`, `emp_id`, `active (bool)` |
| `unit_submissions` | Raw unit counts submitted per employee per order | `id`, `tenant_id`, `order_id`, `emp_id`, `units`, `hours_worked`, `work_date`, `source_file` |
| `uph_history` | Historical UPH tracking per employee | `id`, `tenant_id`, `emp_id`, `work_date`, `uph`, `process_name` |
| `shifts` | Shift definitions | `id`, `tenant_id`, `shift_name`, `shift_date`, `shift_length` |

**Gap:** Orders/clients tables are basic — no line items, SKU, quantity, carrier, or shipment fields. The schema supports productivity tracking against orders but not full order fulfillment, inventory, or logistics workflows.

---

### Tenant Configuration (Migration 001)

| Table | Purpose |
|-------|---------|
| `tenant_goals` | Per-tenant productivity targets (`dept_targets` JSON, global UPH goal) |
| `tenant_settings` | Tenant config blob (timezone, display prefs) |
| `tenant_email_config` | SMTP config + schedule JSON (credentials Fernet-encrypted) |
| `coaching_notes` | Free-form notes per employee |

---

### Billing & Subscriptions (Migrations 002–006)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `subscriptions` | Active Stripe subscription state | `tenant_id`, `plan (starter/pro/business)`, `status`, `employee_limit`, `current_period_end`, `cancel_at_period_end`, `stripe_customer_id`, `stripe_subscription_id` |
| `subscription_events` | Lifecycle audit log (checkout, upgrade, cancel…) | `tenant_id`, `event_type`, `plan`, `stripe_event_id`, `created_at` |
| `pending_plan_changes` | Stripe proration / upgrade-in-flight state | `tenant_id`, `new_plan`, `effective_at` |
| `stripe_webhook_events` | Deduplicated Stripe event store (idempotency key) | `stripe_event_id`, `event_type`, `processed_at` |

**Plan limits (from `plan_service.py`):**
| Plan | Max employees | Advanced features | Coaching intel |
|------|-------------|-------------------|----------------|
| starter | 25 | ✗ | ✗ |
| pro | 100 | ✓ | ✓ |
| business | unlimited | ✓ | ✓ + priority support |

---

### Operations (Migrations 005, 007–013)

| Table | Migration | Purpose | Key Columns |
|-------|-----------|---------|-------------|
| `shift_plans` | 005 | Planned staffing per shift | `tenant_id`, `plan_date`, `department`, `planned_headcount` |
| `shift_checkpoints` | 005 | Shift progress check-ins | `tenant_id`, `plan_date`, `department`, `checkpoint_time`, `actual_headcount` |
| `coaching_followups` | 007 | Scheduled follow-up reminders (legacy) | `tenant_id`, `emp_id`, `followup_date`, `name`, `dept`, `note_preview` |
| `actions` | 008→010 | Core workflow object (was `supervisor_actions`) | `id`, `tenant_id`, `employee_id`, `employee_name`, `department`, `issue_type`, `trigger_source`, `status`, `priority`, `action_type`, `note`, `follow_up_due_at`, `last_event_at`, `resolved_at`, `created_by` |
| `action_events` | 011 | Immutable action lifecycle log | `id`, `tenant_id`, `action_id`, `employee_id`, `event_type`, `event_at`, `performed_by`, `notes`, `outcome`, `next_follow_up_at` |
| `operational_exceptions` | 012 | Operating context / floor exceptions | `id`, `tenant_id`, `employee_id`, `exception_date`, `category`, `summary`, `notes`, `status`, `created_by`, `resolved_at` |

**`actions` status flow (from `action_state_service.py`):** `open` → `in_progress` → `resolved` / `deferred` / `no_action`

**`action_events` event types:** creation, status_change, note_added, follow_up_set, follow_up_completed, resolved, deferred

---

### Signal Pipeline (Migrations 014–019)

This is the core data model for the "daily operating clarity" product value.

#### `activity_records` (Migration 014)

Normalized rows from each CSV/Excel import. One row = one employee + date + process.

```sql
id            uuid PK
tenant_id     uuid FK → tenants
employee_id   text           -- matches employees.emp_id
activity_date date
process_name  text
units         numeric
hours         numeric
productivity_value  numeric  -- computed UPH = units / hours
source_import_job_id uuid    -- import traceability
data_quality_status  text    -- 'ok' | 'low_hours' | 'zero_units' | 'estimated' etc.
source_record_hash   text    -- SHA fingerprint for dedup
```

#### `daily_employee_snapshots` (Migration 016 + 017)

Pre-aggregated per-employee per-day summary. Computed from `activity_records` by `daily_snapshot_service.py`.

```sql
id               uuid PK
tenant_id        uuid FK
snapshot_date    date
employee_id      text
process_name     text
performance_uph  numeric
expected_uph     numeric      -- baseline / target
trend_state      text         -- from migration 017: 'improving' | 'declining' | 'stable' | 'new' | 'inconsistent'
goal_status      text         -- 'above' | 'at' | 'below'
confidence_label text         -- 'high' | 'moderate' | 'low' | 'insufficient_data'
confidence_score numeric
repeat_count     int           -- days in current trend_state
recent_trend_history jsonb    -- array of recent trend_states
```

#### `daily_signals` (Migration 019)

Precomputed, interpretable signals for the Today page queue. One row = one signal event for one employee.

```sql
id              uuid PK
tenant_id       uuid FK
signal_date     date
signal_key      text    -- unique key (employee_id + signal_type + date)
employee_id     text
signal_type     text    -- e.g. 'below_target', 'new_trend_decline', 'recovery', 'high_output'
section         text    -- queue section: 'needs_attention' | 'doing_well' | 'notable'
observed_value  numeric
baseline_value  numeric
confidence      numeric
completeness    numeric
flags           jsonb   -- arbitrary signal metadata
payload         jsonb   -- full signal detail for rendering
```

---

### Process Targets (Migration 015)

```sql
process_targets:
  tenant_id, process_name, target_uph, department, effective_date
```

Stores per-process, per-department UPH targets. Used by `daily_snapshot_service` to compute `goal_status`.

---

## Signal Pipeline Data Flow

```
CSV/Excel upload
        ↓
  import_pipeline/ (parse → map → validate → persist)
        ↓
  activity_records  (one row per employee+date+process)
        ↓
  daily_employee_snapshots  (aggregated, with trend_state + confidence)
        ↓
  daily_signals  (interpretable signals: type, section, payload)
        ↓
  pages/today.py  (renders Today queue from daily_signals)
```

---

## Notable Schema Gaps

| Gap | Impact |
|-----|--------|
| Orders table has no SKU, quantity, carrier, or shipment fields | Cannot support order fulfillment or logistics clarity |
| No labor cost columns (hourly rate, cost center) | Cost impact estimates are approximations only |
| No shift_assignments linking employees to shifts by date | Shift plan page shows planned headcount but cannot verify who was actually present |
| No integration_events or external_id columns | No clean foreign key slot for WMS/TMS/ERP IDs |
| `unit_submissions` and `activity_records` serve overlapping purposes | Dual write surfaces — legacy (unit_submissions) vs. new (activity_records) |
| `coaching_followups` partially superseded by `action_events` | Two follow-up storage paths; `coaching_followups` is the older one |

---

## Future Platform Object Mapping

| Current Table(s) | Future Platform Object |
|-----------------|----------------------|
| `tenants`, `user_profiles` | Organization + Members |
| `employees` | Workforce Member |
| `clients`, `orders` | Customer + Work Order |
| `activity_records` | Productivity Record |
| `daily_employee_snapshots` | Daily Member Snapshot |
| `daily_signals` | Operating Signal |
| `actions`, `action_events` | Action (workflow object with history) |
| `operational_exceptions` | Floor Exception |
| `process_targets` | Performance Target |
| `subscriptions` | Subscription / Entitlement |
| `tenant_email_config` | Notification Config |
| `shift_plans`, `shift_checkpoints` | Shift Plan |
