# Functional Architecture: DPD (Daily Productivity Dashboard)

## System Overview

DPD is a **supervisor-focused productivity monitoring and intervention system**. It ingests operational shift data, computes performance signals via statistical and heuristic analysis, surfaces actionable alerts, and tracks follow-through on coaching actions. The system is built on Streamlit for UI, Supabase for persistence, and a service-oriented architecture for business logic.

**Core Premise:** Show supervisors what stands out from recent patterns, rank by urgency/impact, enable fast case management, and measure follow-through.

---

## Functional Architecture Map

### 1. **Data Ingestion & Validation**
**Responsibility:** Accept CSV uploads, parse structure, validate data quality, detect schema mismatches, and surface issues to users before import.

**Key Components:**
- **Parser & Mapper** → `services/import_pipeline/parser.py`, `mapper.py`, `mapping_profiles.py`
  - Detects CSV structure automatically
  - Maps user columns to system schema (Date, EmployeeID, Department, Units, HoursWorked)
  - Handles multiple CSV layouts via saved mapping profiles
  
- **Validator** → `services/import_pipeline/validator.py`
  - Row-level validation: date format, numeric ranges, required fields
  - Records validation errors per row
  - Categorizes issues: missing fields, invalid dates, out-of-range UPH, duplicate shifts
  
- **Upload Orchestrator** → `services/import_pipeline/orchestrator.py`, `job_service.py`
  - Multi-stage import pipeline: parse → validate → map → preview → process
  - Tracks import job state and completion
  - Handles demo mode seeding
  
- **Import Quality Assessment** → `services/import_quality_service.py`
  - Summarizes validation results
  - Determines trust level (complete, partial, limited, insufficient)
  - Suggests user action (proceed, fix, cancel)

**Data Flow:**
- **IN:** CSV bytes from upload dialog or file selector
- **OUT:** Structured `activity_records` table rows ready for processing; validation report with issue groupings
- **Uses:** `data_loader.py` (auto-detect CSV format), `models/import_quality_models.py` (data structures)

**Diagram:**
```
CSV File
   ↓
[Parser] → Detect structure, split rows
   ↓
[Mapper] → Map columns to schema
   ↓
[Validator] → Check row-level constraints
   ↓
[Orchestrator] → Build job stages
   ↓
[Preview] → Show preview & quality summary → User Review
   ↓
[Process] → Insert to activity_records table
   ↓
database.activity_records (persistent)
```

---

### 2. **Activity Records Storage & Query**
**Responsibility:** Persist raw operational data (shift-level performance metrics) and provide efficient time-windowed queries for analysis.

**Key Components:**
- **Activity Records Repository** → `repositories/activity_records_repo.py`
  - CRUD for shift-level data (one row per employee per shift)
  - Columns: `activity_date`, `employee_id`, `department`, `uph`, `units`, `hours_worked`, `tenant_id`
  - Queries: by employee, by date range, by department
  
- **Activity Records Service** → `services/activity_records_service.py`
  - High-level queries: recent performance, trend windows, department summaries
  - Handles date filtering, aggregation
  - Used by snapshot builder to compute employee profiles

**Data Flow:**
- **IN:** Validated rows from import pipeline, coaching events that affect dates
- **OUT:** Query results (lists of dicts) for snapshot/signal computation
- **Used by:** Daily Snapshot Service, Trend Classification, Activity Comparison

**Database Table:**
```sql
activity_records (
  id, tenant_id, activity_date, employee_id, employee_name, department,
  uph, units, hours_worked, imported_at, source_mode
)
```

---

### 3. **Employee & Roster Management**
**Responsibility:** Maintain employee master data, departments, roles, and handle employee lifecycle (active, archived, rehired).

**Key Components:**
- **Employee Repository** → `repositories/employees_repo.py`
  - CRUD for employee master records
  - Columns: employee_id, name, department, shift, status (active/archived)
  
- **Employee Service** → `services/employees_service.py`, `services/employee_service.py`
  - Employee lookup, filtering by tenant/department
  - Archival handling (don't show archived in current lists)
  - Map employee IDs to names and vice versa
  
- **Employees Page** → `pages/employees.py`
  - UI to view roster, see performance history, archive/restore employees

**Data Flow:**
- **IN:** Initial roster from first import; updates from import pipeline
- **OUT:** Employee metadata for signal context (name, department, shift pattern)
- **Used by:** All signal services, UI display, action tracking

**Database Table:**
```sql
employees (
  id, tenant_id, emp_id, name, department, shift, status, active_from, archived_at
)
```

---

### 4. **Daily Snapshot Computation**
**Responsibility:** Build daily-per-employee performance snapshots by analyzing recent activity records and computing trend state, expected performance, and confidence metrics.

**Key Components:**
- **Daily Snapshot Service** → `services/daily_snapshot_service.py`
  - Core: `recompute_daily_employee_snapshots()` — main entry point
  - Queries 30 days of activity records per employee
  - Computes: trend_state, recent_avg_uph, expected_uph, confidence_label, data_completeness
  - Handles minimum data validation (need ≥2 days for trend, else "early_signal")
  - Outputs: `daily_employee_snapshots` table (one row per employee per date)
  
- **Snapshot Goal Status Converter** → `services/daily_snapshot_service.py:snapshots_to_goal_status_rows()`
  - Transforms raw snapshots into display-ready format for UI
  - Adds computed fields: performance_variance, expected_range
  
- **Snapshot Repository** → `repositories/daily_employee_snapshots_repo.py`
  - CRUD for snapshots
  - Queries: latest by date, by employee, get_latest_snapshot_goal_status()

**Data Flow:**
- **IN:** activity_records (30-day window per employee)
- **OUT:** daily_employee_snapshots rows; goal_status format for Today/Team pages
- **Triggers:** Manual refresh, post-import hook, daily scheduler
- **Used by:** Signal computation, Today page rendering, Team page analytics

**Snapshot Row Structure:**
```python
{
  snapshot_date: "2026-04-19",
  employee_id: "EMP001",
  employee_name: "Marcus Webb",
  department: "Picking",
  recent_avg_uph: 50.2,
  expected_uph: 48.5,
  variance: 3.5,  # %
  trend_state: "improving",  # or "below_expected", "inconsistent", "stable"
  confidence_label: "high",  # or "medium", "low"
  data_completeness: "complete",  # or "partial", "limited", "early_signal"
  recent_record_count: 18  # days with data in window
}
```

---

### 5. **Trend Classification & Pattern Detection**
**Responsibility:** Analyze historical performance sequences and classify trend states (declining, improving, below_expected, inconsistent, stable).

**Key Components:**
- **Trend Classification Service** → `services/trend_classification_service.py`
  - Deterministic trend classification rules:
    - **Below Expected:** recent_avg < (expected * 0.95) for 3+ days
    - **Declining:** recent_avg < previous_avg (slope negative)
    - **Improving:** recent_avg > previous_avg (slope positive)
    - **Inconsistent:** high variance (CV > 15%) with no clear direction
    - **Stable:** flat performance, close to expected
  - Handles low-data cases (returns "early_signal" if < 3 days)
  
- **Repeat Pattern Detection** → `services/action_recommendation_service.py`
  - Identifies employees with recurring issues in recent coaching history
  - Counts repeat offenders (same issue appears 2+ times)
  - Used for prioritization

**Data Flow:**
- **IN:** Performance sequences from snapshots or activity records
- **OUT:** Trend label ("improving", "below_expected", etc.); repeat_count
- **Used by:** Attention Scoring, Signal Generation, Decision Engine

---

### 6. **Attention Scoring & Prioritization**
**Responsibility:** Score and rank employees based on a deterministic model combining trend, exceptions, pattern recurrence, and action urgency.

**Key Components:**
- **Attention Scoring Service** → `services/attention_scoring_service.py`
  - **Scoring Model:** Base 50 points, adjusted by factors:
    - Trend: declining (+25), below_expected (+15), inconsistent (+10), improving (+5)
    - Repeat patterns: 3+ occurrences (+20), 2 (+10), 1 (+5)
    - Action urgency: overdue (+20), due_today (+10)
    - Variance from expected: >20% (+15), 10-19% (+8)
    - Confidence: high (+10), low (-20)
    - Data completeness: complete (+5), partial (-5), limited (-15)
  - **Tiers:** high (≥75), medium (50-74), low (30-49), suppressed (<30)
  - Returns: `AttentionSummary` with ranked items
  
- **Attention Item** → Domain object with employee context, score, reasons
  - `AttentionItem`: employee_id, attention_score, attention_tier, attention_summary, attention_reasons, snapshot

**Data Flow:**
- **IN:** Snapshots (trend, confidence, variance), action_state (overdue flags), repeat_count
- **OUT:** Ranked AttentionSummary with employees sorted by urgency
- **Used by:** Decision Engine, Today page queue, Signal rendering

**Example Ranking:**
```
1. (Score 92, high) EMP004 - Declining trend + 2 repeat patterns + 1 overdue follow-up
2. (Score 81, high) EMP012 - Below expected + overdue follow-up
3. (Score 68, medium) EMP007 - Inconsistent performance + limited data confidence
4. (Score 45, low) EMP019 - Slight decline, improving lately
5. ... (filtered: score < 30 suppressed)
```

---

### 7. **Action Lifecycle Management**
**Responsibility:** Track coaching actions (interventions, follow-ups) from creation through resolution, including state transitions and outcome logging.

**Key Components:**
- **Actions Repository** → `repositories/actions_repo.py`
  - CRUD for action records
  - Columns: action_id, employee_id, created_at, last_event_at, status (open, resolved, follow_up_pending), priority, reason
  
- **Action Query Service** → `services/action_query_service.py`
  - Get open actions for employee
  - Get actions due today / overdue
  - List recent actions by employee
  
- **Action Lifecycle Service** → `services/action_lifecycle_service.py`
  - Create action, log event, mark as follow-up-pending, resolve action
  - Tracks who created, who last touched, timestamps
  
- **Action Events Repository** → `repositories/action_events_repo.py`
  - Log of all touches: coaching sessions, follow-through logged, status change, outcome recorded
  - Columns: action_id, event_at, event_type (coaching, follow_through, status_change), outcome (improved, worse, no_change), details, recorded_by
  
- **Action State Service** → `services/action_state_service.py`
  - Builds employee action state lookup (what actions they have, which are overdue)
  - Determines: is_overdue, due_today, status, next_due_date
  - Used for UI display and prioritization

**Data Flow:**
- **IN:** User logs coaching session / follow-through event; system checks due dates daily
- **OUT:** Action events (immutable); action status updates (mutable)
- **Used by:** Today page, Team page, Decision engine (urgency), Follow-through metrics

**Database Tables:**
```sql
actions (id, employee_id, created_at, last_event_at, status, priority, reason, tenant_id)
action_events (id, action_id, event_at, event_type, outcome, details, recorded_by)
```

---

### 8. **Signal Generation & Persistence**
**Responsibility:** Compute interpretable signals (alerts) from snapshots and actions, format them as displayable cards, and cache for fast page load.

**Key Components:**
- **Daily Signals Service** → `services/daily_signals_service.py`
  - Entry: `compute_daily_signals(signal_date, tenant_id)` — main computation
  - Aggregates: snapshots, actions, decisions into a single daily payload
  - Builds: action queue, home sections (insights, recognition), decision items
  - Persists to `daily_signals` table for fast read-only rendering
  
- **Signal Interpretation Service** → `services/signal_interpretation_service.py`
  - Converts snapshots + actions into human-readable "why is this person shown" explanations
  - Generates copy like: "Performance declined 8% vs 7-day average; 1 follow-up overdue"
  - Handles confidence hedging: "based on 3 shifts, may change as more data arrives"
  
- **Action Recommendation Service** → `services/action_recommendation_service.py`
  - Identifies high-performers to recognize
  - Identifies repeat offenders (pattern problems)
  - Suggests recognition vs intervention
  
- **Today Home Service** → `services/today_home_service.py`
  - Builds home section cards (trending issues, top performers, exceptions)
  - Aggregates insights across all employees
  
- **Display Signal Factory** → `services/display_signal_factory.py`
  - Converts raw snapshots into `DisplaySignal` domain objects
  - Filters for eligibility (don't show if too early/too low-data)
  - Sets display mode (CURRENT_STATE, EARLY_TREND, LOW_DATA, etc.)

**Data Flow:**
- **IN:** daily_employee_snapshots, actions, action_events
- **OUT:** `daily_signals` table (precomputed payload for Today page)
- **Triggers:** Post-import, daily scheduler, manual refresh
- **Used by:** Today page, signal rendering, drill-down context

**Signals Table:**
```sql
daily_signals (
  id, tenant_id, signal_date,
  queue_items (JSON: actions with context),
  home_sections (JSON: insights, recognition),
  import_summary (JSON: # days, # employees, data quality),
  attention_summary (JSON: ranked employees),
  decision_items (JSON: decision engine results),
  as_of_date, computed_at
)
```

---

### 9. **Decision Engine & Ranking**
**Responsibility:** Synthesize snapshot trends, action state, and attention scores into ranked decision items for final prioritization.

**Key Components:**
- **Decision Engine Service** → `services/decision_engine_service.py`
  - Entry: `build_decision_items()` — returns list of ranked DecisionItem objects
  - Combines: attention_score + action_state + primary_reason
  - Final score: weighted average of attention + action urgency
  - Produces `DecisionItem` (frozen dataclass with all context for rendering)
  
- **Decision Item** → Domain object:
  ```python
  @dataclass(frozen=True)
  class DecisionItem:
    employee_id, process_name, final_score, final_tier, 
    attention_score, action_score, attention_item,
    confidence_label, normalized_action_state,
    primary_reason
  ```

**Data Flow:**
- **IN:** AttentionSummary (scored employees), action_state_lookup (overdue/due_today status)
- **OUT:** Ranked DecisionItem list
- **Used by:** Today page queue rendering, drill-down context

---

### 10. **Business Logic & Heuristics**
**Responsibility:** Encapsulate domain rules for productivity assessment, confidence determination, and data quality checks.

**Key Components:**
- **Benchmarking Service** → `domain/benchmarks.py`, `services/target_service.py`
  - Defines expected performance targets per role/department
  - Provides baseline for "below_expected" classification
  - May be configurable per tenant
  
- **Activity Comparison Service** → `services/activity_comparison_service.py`
  - Compares current vs historical (7-day, 14-day averages)
  - Computes variance percentages
  - Determines if change is "significant" (>10%, >15%, etc.)
  
- **Risk Scoring** → `domain/risk_scoring.py`, `services/risk_*.py`
  - Converts trend + variance + recurrence into risk levels
  - Used for prioritization and alert weighting
  
- **Data Quality Rules** → `services/import_quality_service.py`, `services/signal_quality_service.py`
  - Minimum days required per employee to compute trend (3+)
  - Confidence degradation with limited data (<7 days)
  - Data completeness assessment (missing shifts, outlier values)

**Data Flow:**
- **IN:** Snapshots, activity records, historical benchmarks
- **OUT:** Classification labels (trend_state, confidence, risk_level), quality assessments
- **Used by:** All signal services, UI display

---

### 11. **State Management & Caching**
**Responsibility:** Cache expensive computations, manage Streamlit session state for UI interactivity, and coordinate multi-stage data preparation.

**Key Components:**
- **Streamlit Session State** → `core/session.py`
  - `tenant_id`, `user_email`, `user_role`, `subscription_tier`
  - `today_queue_filter`, `emp_view`, `cn_selected_emp` (current page selections)
  - `_post_import_refresh_pending`, `_today_recovery_attempted_*` (recovery flags)
  - `_today_precomputed_payload` (cache of Today page data)
  
- **Cached Functions** → Throughout services
  - `@st.cache_data(ttl=300)` decorators on heavy queries
  - Examples: `_cached_today_signals_payload()`, `_cached_employees()`, `_cached_manager_outcome_stats()`
  - TTL typically 300s (5 min) for read-only data
  
- **Recovery Locks** → `pages/today.py`
  - Per-date recovery lock to prevent concurrent snapshot rebuilds
  - Lock state: `_today_recovery_in_progress_2026-04-19`, `_today_recovery_started_at_*`
  - TTL: 90 seconds; older locks automatically expire
  
- **Cache Busting** → `core/dependencies.py`
  - `_bust_cache()` clears all caches after import
  - Selective cache clear for specific functions
  - Ensures fresh data after state changes

**Data Flow:**
- **IN:** Computations, user interactions, imports
- **OUT:** Cached results, session state persisted during request → cleared on new session
- **Pattern:** Heavy computation → cache → reuse across multiple renders → bust on import

---

### 12. **UI State Management & Navigation**
**Responsibility:** Render pages, route navigation, manage user selections, and coordinate multi-page workflows (import flow, drill-down, etc.).

**Key Components:**
- **Page Router** → `core/page_router.py`
  - Dispatches to correct page based on navigation state
  - Pages: today, team, productivity, shift_plan, settings, import, etc.
  
- **Navigation** → `core/navigation.py`
  - Renders sidebar, page selector, handles page transitions
  - Manages `st.session_state["goto_page"]` to trigger navigation
  
- **Today Page** → `pages/today.py`
  - Reads precomputed daily_signals from cache/DB
  - Renders queue, value strip, weekly summary, exceptions
  - Handles signal status marking ("looked at", "needs follow-up")
  - Triggers recovery if payload stale
  
- **Team Page** → `pages/employees.py` or supervisor page
  - Lists all employees with current status
  - Drill-down to employee detail with action history
  - Enable coaching entry, action creation
  
- **Import Page** → `pages/import_page.py`
  - Multi-stage flow: upload → validate → map → preview → confirm → process
  - Handles demo mode ("Try sample data")
  - Shows import quality summary
  
- **Settings Page** → `pages/settings_page.py`
  - User preferences, notification settings, export options

**Data Flow:**
- **IN:** User clicks, page selections stored in session_state
- **OUT:** Page render (HTML/markdown), updates to session_state
- **Pattern:** State change → trigger computation → update cache → re-render

---

### 13. **External Integrations & Notifications**
**Responsibility:** Deliver insights outside the app (email, Slack), manage auth, billing, and external service calls.

**Key Components:**
- **Email Service** → `services/email_service.py`, `email_engine.py`, `email/templates.py`
  - Send daily alerts, coaching confirmations
  - Template rendering (team summary, alerts, links)
  - Batch send per tenant
  
- **Auth & Multitenancy** → `auth.py`, `repositories/tenant_repo.py`, `services/access_control_service.py`
  - OAuth (via Supabase Auth or custom)
  - Per-tenant data isolation (all queries filtered by tenant_id)
  - Role-based access control (supervisor, manager, admin)
  
- **Billing & Subscription** → `services/billing_service.py`, `repositories/billing_repo.py`
  - Subscription tiers (free, pro, enterprise)
  - Feature gates based on tier
  - Usage tracking, upgrade prompts
  
- **Analytics & Observability** → `services/app_logging.py`, `services/observability.py`
  - Log app errors, operational events
  - Track user actions for product insights
  - Error tracking to `dpd_ops.log`, error summaries

**Data Flow:**
- **IN:** Coaching actions, import completions, daily scheduler
- **OUT:** Email messages, auth tokens, billing records, log entries
- **External:** Email provider API, Auth provider (Supabase), Logging system

---

### 14. **Background Jobs & Scheduling**
**Responsibility:** Execute long-running or scheduled tasks (snapshot recompute, email sends, recovery) without blocking UI.

**Key Components:**
- **Job Service** → `services/import_pipeline/job_service.py`, `jobs/job_service.py`
  - Define async job types: import_process, snapshot_recompute, email_send, recovery
  - Track job state: pending, in_progress, completed, failed
  - Retry logic
  
- **Job Entrypoints** → `jobs/entrypoints.py`
  - `run_import_postprocess_job()` — process rows after validation
  - `run_import_preview_job()` — compute preview stats
  
- **Job Runner** → `jobs/runner.py`
  - Execute jobs, log results
  - Handle failures, retry
  
- **Scheduler Integration** → `services/import_pipeline/job_service.py`, scheduler setup
  - Daily/hourly triggers for signal recompute
  - Email batch sends
  - Cleanup of old logs

**Data Flow:**
- **IN:** Triggers from UI (manual refresh), scheduler (time-based), post-import hooks
- **OUT:** Completed snapshots/signals, sent emails, job status logs
- **Pattern:** Enqueue job → background execute → update DB → cache bust → notify UI

---

### 15. **Database & Persistence**
**Responsibility:** Abstract all database interactions; manage schema, transactions, multitenancy, and provide consistent data access.

**Key Components:**
- **Database Client** → `database.py`
  - Single Supabase client initialization
  - Configuration from env vars / Streamlit secrets
  - Connection pooling, error handling
  
- **Repository Pattern** → `repositories/*.py`
  - Each entity (employees, actions, activity_records, etc.) has a repo
  - CRUD methods, query filters, batch operations
  - All queries include tenant_id filter for isolation
  
- **Query Builders** → Within repos
  - Named queries for common patterns (e.g., `get_latest_snapshot_goal_status()`)
  - Handle NULL/empty safely
  - Return dicts or dataclass instances
  
- **Migrations** → `migrations/` folder
  - Schema versioning, table creation, index management
  - Applied at app startup if needed

**Data Flow:**
- **IN:** Write requests from services (insert/update/delete)
- **OUT:** Query results (select)
- **Isolation:** All queries scoped by tenant_id to prevent cross-tenant data leaks

**Core Tables:**
```
employees, activity_records, daily_employee_snapshots,
daily_signals, actions, action_events,
import_batches, import_quality_summaries,
tenants, users, operational_exceptions
```

---

## Data Flow Diagram: High Level

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE LAYER                     │
│  (Streamlit Pages: Today, Team, Import, Settings, Productivity) │
└──────────────────┬──────────────────────────────────────────────┘
                   │ User interactions: upload, view, log action
                   ↓
      ┌────────────────────────────┐
      │   DATA INGESTION           │
      │ (Import Pipeline)          │
      │ • Parse CSV                │
      │ • Validate rows            │
      │ • Map columns              │
      │ • Assess quality           │
      └─────────┬──────────────────┘
                │ Validated data
                ↓
      ┌────────────────────────────────────────────────────┐
      │   PERSISTENCE & QUERY LAYER                        │
      │ (Database: activity_records, employees,            │
      │  import_batches, import_quality_summaries)         │
      └─────────┬──────────────────────────────────────────┘
                │ Query: recent activity per employee
                ↓
      ┌────────────────────────────────────────────────────────┐
      │   COMPUTATION LAYER (Service Orchestration)           │
      │                                                        │
      │  ┌──────────────────────────────────────────────┐     │
      │  │ Snapshot Computation                         │     │
      │  │ • Analyze 30-day activity per employee      │     │
      │  │ • Compute trend_state, confidence           │     │
      │  │ • Write daily_employee_snapshots            │     │
      │  └──────────┬───────────────────────────────────┘     │
      │             │                                         │
      │             ↓                                         │
      │  ┌──────────────────────────────────────────────┐     │
      │  │ Signal Generation                            │     │
      │  │ • Attention scoring (rank by urgency)       │     │
      │  │ • Action urgency (overdue, due_today)       │     │
      │  │ • Decision engine (combine scores)          │     │
      │  │ • Build queue items, home sections          │     │
      │  │ • Write daily_signals (precomputed)         │     │
      │  └──────────┬───────────────────────────────────┘     │
      │             │                                         │
      └─────────────┼─────────────────────────────────────────┘
                    │
      ┌─────────────┴──────────────────────────────────┐
      │   CACHE LAYER (Streamlit @st.cache_data)      │
      │ • daily_signals payload                       │
      │ • employee roster                             │
      │ • manager outcome stats                       │
      │ • TTL: 300s (5 min) per type                 │
      └──────────┬──────────────────────────────────┘
                 │ High-speed read
                 ↓
      ┌──────────────────────────────────┐
      │   UI RENDERING (Today, Team,     │
      │   Productivity, etc.)            │
      │ • Display signals with context   │
      │ • Show queue items ranked        │
      │ • Enable user interactions       │
      │ • Signal status marking          │
      └──────────────────────────────────┘

   ┌─────────────────────────────────────────────────────────┐
   │   BACKGROUND JOBS & SCHEDULING (Async)                │
   │ • Snapshot recompute (daily/on-demand)                │
   │ • Email sends (alerts, summaries)                     │
   │ • Recovery lock management (90s TTL)                  │
   │ • Imports post-processing                            │
   └─────────────────────────────────────────────────────────┘
```

---

## Component Dependencies

### 1. **Snapshot Computation** depends on:
   - `activity_records_service` (fetch recent shifts)
   - `trend_classification_service` (classify trend)
   - `benchmark_service` (expected UPH)
   - `activity_comparison_service` (compute variance)
   - `daily_employee_snapshots_repo` (persist)

### 2. **Signal Generation** depends on:
   - `daily_snapshot_service` (fetch latest snapshots)
   - `action_query_service` (fetch open actions)
   - `action_state_service` (determine overdue/due_today)
   - `attention_scoring_service` (rank employees)
   - `decision_engine_service` (finalize ranking)
   - `today_home_service` (build home sections)
   - `daily_signals_repo` (persist precomputed payload)

### 3. **Today Page** depends on:
   - `daily_signals_repo` (read precomputed payload)
   - `daily_snapshot_service` (rebuild if stale)
   - `today_page_meaning_service` (interpret payload)
   - `today_queue_service` (format queue)
   - `today_view_model_service` (build view objects)
   - `signal_formatting_service` (render signals)
   - `today_signal_status_service` (track user markings)

### 4. **Import Pipeline** depends on:
   - `data_loader.py` (auto-detect CSV)
   - `import_pipeline/parser` (parse rows)
   - `import_pipeline/validator` (validate)
   - `import_pipeline/mapper` (map columns)
   - `import_quality_service` (assess quality)
   - `activity_records_repo` (insert validated rows)
   - `import_repo` (track import batch)

### 5. **Decision Engine** depends on:
   - `attention_scoring_service` (get ranked items)
   - `action_state_service` (get action context)
   - `decision_surfacing_policy_service` (apply ranking rules)

### 6. **Email & Notifications** depends on:
   - `daily_signals_repo` (read today's signals)
   - `employees_repo` (get recipient list)
   - `action_events_repo` (get recent actions)
   - `email_service` (send)

---

## Data Model: Key Entities

### **Activity Record**
```python
{
  "id": "uuid",
  "tenant_id": "tenant-uuid",
  "activity_date": "2026-04-19",
  "employee_id": "EMP001",
  "employee_name": "Marcus Webb",
  "department": "Picking",
  "shift": "Day",
  "uph": 51.60,  # Units Per Hour
  "units": 413,
  "hours_worked": 8.00,
  "imported_at": "2026-04-19T14:32:00Z",
  "source_mode": "upload"  # or "demo"
}
```

### **Daily Employee Snapshot**
```python
{
  "id": "uuid",
  "tenant_id": "tenant-uuid",
  "snapshot_date": "2026-04-19",
  "employee_id": "EMP001",
  "employee_name": "Marcus Webb",
  "department": "Picking",
  "recent_avg_uph": 50.2,
  "expected_uph": 48.5,
  "variance_percent": 3.5,
  "trend_state": "improving",
  "confidence_label": "high",
  "data_completeness": "complete",
  "recent_record_count": 18,
  "computed_at": "2026-04-19T15:00:00Z"
}
```

### **Daily Signal (Precomputed Payload)**
```python
{
  "id": "uuid",
  "tenant_id": "tenant-uuid",
  "signal_date": "2026-04-19",
  "as_of_date": "2026-04-19",
  "queue_items": [  # Today action queue
    {
      "employee_id": "EMP004",
      "line_1": "Nate Okafor · Picking",
      "line_2": "Performance declined 8% vs 7-day average",
      "line_3": "1 follow-up overdue",
      "_queue_status": "overdue",
      "_is_repeat_issue": true,
      "confidence_label": "high",
      "normalized_action_state": "Open"
    },
    ...
  ],
  "import_summary": {
    "days": 19,
    "emp_count": 32,
    "valid_rows": 608,
    "source_mode": "demo",
    "below": 2,
    "risks": 1
  },
  "home_sections": {
    "top_insight_cards": [...]
  },
  "attention_summary": {
    "ranked_items": [...],
    "is_healthy": false,
    "healthy_message": "...",
    "suppressed_count": 5,
    "total_evaluated": 32
  },
  "computed_at": "2026-04-19T15:00:00Z"
}
```

### **Action**
```python
{
  "id": "uuid",
  "tenant_id": "tenant-uuid",
  "employee_id": "EMP004",
  "created_at": "2026-04-17T10:30:00Z",
  "last_event_at": "2026-04-17T10:30:00Z",
  "status": "open",  # open, resolved, follow_up_pending
  "priority": "high",
  "reason": "Performance below expected",
  "next_due_date": "2026-04-20",
  "created_by": "supervisor@example.com"
}
```

### **Action Event**
```python
{
  "id": "uuid",
  "action_id": "action-uuid",
  "event_at": "2026-04-17T10:30:00Z",
  "event_type": "coaching",  # coaching, follow_through, status_change, outcome_logged
  "outcome": null,  # or "improved", "worse", "no_change", "blocked", "pending"
  "details": "Discussed pace strategies; will check back Wed",
  "recorded_by": "supervisor@example.com"
}
```

---

## Data Flow: Import Scenario

```
1. User clicks "Try sample data"
   ↓
2. Import Page renders multi-stage flow
   ↓
3. Parser detects CSV schema (Date, Department, EmployeeID, ...)
   ↓
4. Mapper applies profile (user → system columns)
   ↓
5. Validator checks each row:
   - Valid date format?
   - EmployeeID populated?
   - UPH in reasonable range?
   - Records: valid_rows, error_rows, issue_count
   ↓
6. Quality Assessment:
   - % valid rows: 100% → trust=COMPLETE
   - Data issues: none → quality=HIGH
   ↓
7. User confirms import
   ↓
8. Insert activity_records (608 rows for demo)
   ↓
9. Post-Import Hook:
   - Set session flag: _post_import_refresh_pending = True
   - Bust cache: clear all @st.cache_data
   ↓
10. Today Page detects need for recovery:
    - Checks if payload stale (no snapshots for today)
    - Triggers: recompute_daily_employee_snapshots()
    ↓
11. Snapshot Recompute:
    - Fetch 30 days activity per employee
    - Compute trend, variance, confidence
    - Write daily_employee_snapshots (32 rows for today)
    ↓
12. Signal Computation:
    - Read snapshots + actions
    - Score by attention, rank by urgency
    - Generate queue_items, home_sections
    - Write daily_signals (1 precomputed payload)
    ↓
13. Today Page render:
    - Read from cache (or DB if not cached)
    - Display queue, summaries, metrics
    - Show 32 employees with trends
```

---

## Data Flow: User Interaction Scenario

```
1. Supervisor views Today page
   ↓
2. Sees queue of 3 priority employees
   - #1: EMP004 (Nate) - Declining + overdue follow-up
   - #2: EMP012 (Simone) - Below expected
   - #3: EMP007 (Devon) - Inconsistent
   ↓
3. Clicks "View details →" on EMP004
   ↓
4. Navigates to Team/Employee Detail page
   - Shows full action history
   - Displays 19 days of activity
   - Shows trend chart, recent UPH values
   ↓
5. Clicks "Log quick note" / "Create action"
   ↓
6. Fills form:
   - Action type: coaching
   - Notes: "Discussed pace; expecting improvement"
   - Due date: 2026-04-22
   ↓
7. Submits → Creates action record in DB
   ↓
8. Marks signal status as "Needs follow-up"
   ↓
9. Supervisor navigates back to Today
   ↓
10. Cache invalidated (action created)
    ↓
11. Next Today page render:
    - Snapshots still valid (same date)
    - But action state changed (now has next_due_date)
    - Queue item now shows: "Follow-up due 2026-04-22"
    ↓
12. Supervisor sees updated context
```

---

## Summary: Architecture Characteristics

1. **Layered & Service-Oriented:** Separation of concerns: ingestion → computation → persistence → caching → rendering
2. **Read-Optimized:** Precomputation of signals + heavy caching = fast page loads
3. **Deterministic Scoring:** Attention scoring, trend classification use explicit rules (reproducible, auditable)
4. **Tenant-Isolated:** All queries include tenant_id; no cross-tenant data leaks
5. **Recovery Patterns:** Stale detection + auto-rebuild of snapshots/signals on stale conditions
6. **User-Friendly:** Non-prescriptive (shows "what stands out", not "you must do X")
7. **Async-Ready:** Background jobs decouple long computations from UI responsiveness
