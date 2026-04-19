# Systematic Audit Plan: DPD Codebase

## Executive Summary

This audit plan covers 15 functional components organized by risk level. Execution sequence prioritizes **CRITICAL** areas (data isolation, signal correctness, state coherence) before **HIGH** (logic, prioritization) and **MEDIUM** areas (UX, integrations).

**Total audit steps:** 15  
**Estimated time:** 3-5 hours for technical review, 2-3 hours for manual testing  
**Risk focus:** Data isolation, mathematical correctness, state consistency, recovery from failure

---

## Risk Assessment Summary

| Rank | Component | Risk Level | Reason |
|------|-----------|-----------|--------|
| 1 | Database & Persistence (15) | CRITICAL | Data isolation breach affects all users; single tenant_id filter miss = data leak |
| 2 | Activity Records Storage (2) | CRITICAL | Aggregation math errors compound into snapshots; NULL handling wrong = silent failures |
| 3 | Daily Snapshot Computation (4) | CRITICAL | Foundation for all downstream signals; off-by-one here cascades to entire queue |
| 4 | Signal Generation & Persistence (8) | CRITICAL | Today page displays this; if broken = user sees nothing or stale data |
| 5 | State Management & Caching (11) | CRITICAL | Cache poisoning causes data leaks; stale flag wrong = recovery stuck |
| 6 | Data Ingestion & Validation (1) | HIGH | Multi-stage state machine; off-by-one in batch processing = data loss/corruption |
| 7 | Trend Classification & Patterns (5) | HIGH | Boundary conditions wrong = systematic bias in signal display |
| 8 | Attention Scoring & Prioritization (6) | HIGH | Weight formula bugs = wrong queue order defeats entire system |
| 9 | Decision Engine & Ranking (9) | HIGH | Final ranking wrong = supervisors act on wrong priorities |
| 10 | UI State & Navigation (12) | HIGH | State pollution between pages = errors from stale context |
| 11 | Action Lifecycle Management (7) | MEDIUM | State transitions violated = audit trail corrupt |
| 12 | Business Logic & Heuristics (10) | MEDIUM | Underlying assumptions wrong = biased results (visible but silent) |
| 13 | Employee & Roster Management (3) | MEDIUM | Archived filter missing = wrong employees shown |
| 14 | External Integrations (13) | MEDIUM | Email fails silently = notifications never arrive |
| 15 | Background Jobs & Scheduling (14) | MEDIUM | Job queue stuck = snapshots don't update but no alert |

---

# AUDIT SEQUENCE

## PHASE 1: CRITICAL FOUNDATION (Steps 1-5)

These 5 components form the data pipeline core. Failures here affect all downstream logic.

---

## **STEP 1: Database & Persistence (CRITICAL)**

### Scope
Files: `database.py`, `repositories/*.py`, all query builders

### Likely Logic Bugs
- **Tenant isolation breach:** Single query missing `tenant_id` filter leaks data across users
- **NULL handling:** Mixed use of `is None` vs `or` vs `.get()` with defaults
- **Type mismatches:** String IDs vs UUIDs, dates stored as strings vs actual dates
- **Transaction boundaries:** Multi-row operations not atomic; partial writes on error
- **Update semantics:** `WHERE` clause missing or too permissive; updates affect wrong rows

### Specific Checks

#### 1.1: Tenant ID Filter Audit
```
For EVERY query in repositories/:
- CONFIRM: WHERE clause includes tenant_id = ?
- CONFIRM: tenant_id comes from parameter, not hardcoded
- CONFIRM: JOIN operations filter on tenant_id
- CONFIRM: No query returns data without tenant_id scoped

Files to check:
  repositories/actions_repo.py
  repositories/activity_records_repo.py
  repositories/daily_employee_snapshots_repo.py
  repositories/daily_signals_repo.py
  repositories/employees_repo.py
  repositories/action_events_repo.py
  repositories/import_repo.py
  repositories/operational_exceptions_repo.py
  repositories/billing_repo.py

Pattern: GOOD
  def get_employee_actions(tenant_id, employee_id):
    return db.table("actions")
      .select("*")
      .eq("tenant_id", tenant_id)
      .eq("employee_id", employee_id)
      .execute()

Pattern: BAD
  def get_employee_actions(employee_id):
    return db.table("actions")
      .select("*")
      .eq("employee_id", employee_id)  # Missing tenant_id!
      .execute()
```

#### 1.2: NULL/Empty Handling
```
For all numeric queries:
- Check: Division by zero guards (e.g., variance = numerator / max(denominator, 1))
- Check: `.get()` calls provide defaults vs raise on missing keys
- Check: Empty list handling (e.g., avg([]) should not crash)
- Check: String operations handle None, empty string, whitespace

Example check:
  recent_avg = sum([r['uph'] for r in rows]) / len(rows)  # BAD if rows=[]
  recent_avg = sum([r['uph'] for r in rows]) / max(len(rows), 1)  # GOOD
```

#### 1.3: Date & Timestamp Consistency
```
- Check: All dates stored consistently (ISO format, UTC, no timezone confusion)
- Check: Date comparisons use .isoformat() consistently
- Check: Boundary dates (today, yesterday, 30-days-ago) computed correctly
- Check: No implicit timezone conversions

Example:
  today = date.today()  # Could be wrong if server is in different timezone
  should use: today = datetime.utcnow().date()
```

#### 1.4: Update Semantics
```
For any UPDATE or upsert operation:
- Check: WHERE clause is specific (not UPDATE all rows by accident)
- Check: Upsert logic doesn't double-write same value
- Check: ON CONFLICT behavior defined explicitly
- Check: Old values aren't accidentally overwritten with NULL

Example:
  BAD: update_action(action_id, status=None)  # Could clear action_status!
  GOOD: update_action(action_id, status=status) if status is not None
```

### Highest-Risk Areas
- `get_latest_snapshot_goal_status()` — used everywhere, one NULL bug here breaks Today page
- `batch_upsert_daily_signals()` — concurrent writes could create duplicates
- Any JOIN without tenant_id filter

### Manual Test
```
1. Log in as tenant A, import data
2. Log in as tenant B (different account)
3. View employee list → should NOT see tenant A's employees
4. Query API directly with wrong tenant_id → should return empty, not error
```

---

## **STEP 2: Activity Records Storage & Query (CRITICAL)**

### Scope
Files: `repositories/activity_records_repo.py`, `services/activity_records_service.py`

### Likely Logic Bugs
- **Date range off-by-one:** 30-day window should be [today-30, today] inclusive, not exclusive
- **Timezone confusion:** Dates compared without UTC normalization
- **Aggregation errors:** SUM/COUNT/AVG on empty results or with NULLs
- **Filtering logic:** Department/shift filters don't exclude archived employees
- **Duplicate handling:** Same date + employee + shift imported twice = double counting

### Specific Checks

#### 2.1: Date Range Window Verification
```
Test code:
  today = date(2026, 4, 19)
  records = get_activity_records_30_days(employee_id, today)
  
  # Check 1: Oldest record should be ≤ 2026-03-21 (30 days ago)
  oldest = min(r['activity_date'] for r in records)
  assert oldest <= (today - timedelta(days=30)).isoformat()
  
  # Check 2: Newest record should be ≤ today
  newest = max(r['activity_date'] for r in records)
  assert newest <= today.isoformat()
  
  # Check 3: With 3 weeks of data (21 days), should get all 21
  assert len([r for r in records if r['activity_date'] >= (today-timedelta(days=21)).isoformat()]) == 21

Files:
  services/activity_records_service.py:recent_activities()
  repositories/activity_records_repo.py:list_activity_records()
```

#### 2.2: NULL & Empty Result Handling
```
Test edge cases:
  # New employee with 0 records
  records = get_activity_records(employee_id="NEW001", days=30)
  assert records == []
  assert len(records) == 0  # Don't crash
  
  # Employee with 1 record (not enough for trend)
  avg_uph = sum(r['uph'] for r in records) / max(len(records), 1)
  assert avg_uph > 0
  
  # Records with missing UPH values
  records_with_nulls = [..., {'uph': None}, ...]
  avg_uph = sum(float(r.get('uph') or 0) for r in records) / max(len(records), 1)
  assert avg_uph >= 0  # No NaN
```

#### 2.3: Aggregation Correctness
```
For each aggregation in services/activity_records_service.py:
  - Check: Formula matches documented business logic
  - Check: Handles 0, 1, empty, and typical cases
  - Check: Unit consistency (UPH in units/hour, not units)
  
Example:
  daily_avg = sum(r['units'] for r in records) / sum(r['hours_worked'] for r in records if r['hours_worked'] > 0)
  
  Verify:
    - hours_worked never 0 (would be division by zero)
    - units and hours_worked are numeric, not strings
    - Result is UPH (units per hour), not total units
```

#### 2.4: Duplicate Detection
```
Check import flow doesn't double-count:
  - Same (date, employee_id, shift) imported twice
  - Should either: reject duplicate or replace old with new
  
Verify in:
  services/import_service.py (before insert)
  repositories/activity_records_repo.py (UNIQUE constraint or upsert)
  
Test:
  1. Import 608 rows for demo (April 1-19)
  2. Import same 608 rows again
  3. Final count should be 608, not 1216 (if using upsert)
     OR should reject with "duplicate found" (if insert fails on constraint)
```

### Highest-Risk Areas
- **`recent_activities()` date window** — off by 1 day breaks all trend calculations
- **Aggregation in empty result** — crashes trend classifier
- **Timezone in date comparison** — all dates off by N hours if UTC not used consistently

### Manual Test
```
1. Import data on April 19
2. Query activity_records for employee on that day
3. Verify count = 1 (not 2 if same employee appears twice per day)
4. Query 30-day window; count should match manual count
5. Manually calculate avg UPH; compare to service result ± 0.01
```

---

## **STEP 3: Daily Snapshot Computation (CRITICAL)**

### Scope
Files: `services/daily_snapshot_service.py`, `repositories/daily_employee_snapshots_repo.py`

### Likely Logic Bugs
- **Trend calculation off-by-one:** Should compare avg(recent_14_days) vs avg(prior_14_days), but might compare to single day
- **Variance formula:** sqrt((x - mean)^2 / n) vs sqrt((x - mean)^2 / (n-1)) — different results
- **Confidence threshold:** "high" if n >= 14 days, but what if exactly 14?
- **Early signal miscalculation:** < 3 days data should be "early_signal", but might be "low_confidence"
- **Expected UPH lookup:** Benchmark might be missing for department; should default to recent_avg, not crash
- **Null snapshots:** Employee with no activity_records still gets snapshot? (Should they?)

### Specific Checks

#### 3.1: Trend Calculation Logic
```
Verify in: services/daily_snapshot_service.py:recompute_daily_employee_snapshots()

Expected behavior:
  recent_14 = activity_records from [today-14, today]
  prior_14 = activity_records from [today-28, today-14]
  
  trend = classify_trend(avg(recent_14), avg(prior_14), expected_uph)
  
Audit:
  1. Is date window inclusive or exclusive?
  2. Are boundaries == or <?
  3. What if recent_14 = 3 days (weekend), prior_14 = 14 days?
     Does classifier handle unequal sample sizes?

Test:
  employee = EMP001
  activity_records for EMP001:
    2026-04-06: 48.0 UPH
    2026-04-07: 49.0 UPH
    ... (12 more days)
    2026-04-19: 51.0 UPH (today)
  
  expected_uph = 48.5
  
  Compute:
    recent_14_avg = (48+49+...+51) / 14
    prior_14_avg = (? values for Apr 1-6 + Mar 25-31)
    
  Verify:
    - Both windows are exactly 14 days (or <= 14 if less data available)
    - recent_14_avg > expected_uph → trend = "improving" ✓
    - Snapshot shows trend_state = "improving" ✓
```

#### 3.2: Confidence & Data Completeness
```
Verify: services/daily_snapshot_service.py:determine_confidence_label()

Rules:
  - If < 3 days data: confidence = "early_signal", data_completeness = "early_signal"
  - If 3-6 days data: confidence = "low", data_completeness = "limited"
  - If 7-13 days data: confidence = "medium", data_completeness = "partial"
  - If >= 14 days data: confidence = "high", data_completeness = "complete"

Test matrix:
  days_with_data | expected_confidence | expected_completeness
  1              | low/early           | early_signal
  3              | low                 | limited
  7              | medium              | partial
  14             | high                | complete
  21             | high                | complete

Check actual values in snapshot output for each case.
```

#### 3.3: Expected UPH Lookup
```
Check: What happens if expected_uph is missing for an employee's department?

Expected behavior:
  if expected_uph is None:
    expected_uph = recent_avg_uph  # Use actual as baseline
  
  variance = ((recent_avg - expected_uph) / expected_uph * 100)
  
Edge case: What if recent_avg = 0? Division by zero?
  variance = (0 - 100) / max(100, 0.1) = -1000%  (OK, very negative)
  
Verify:
  - No snapshot with NULL expected_uph (should fallback to recent_avg)
  - Variance formula always produces a number (no NaN)
  - No division by zero
```

#### 3.4: Null Snapshot Handling
```
Question: If employee has 0 activity_records on a date, do they get a snapshot?

Current behavior (verify):
  for each employee:
    if get_activity_records(employee, date) is empty:
      OPTION A: skip, don't create snapshot
      OPTION B: create snapshot with zero_records marker
      OPTION C: create snapshot with recent_avg carried forward

Check code:
  services/daily_snapshot_service.py:recompute_daily_employee_snapshots()
  
  Does it iterate all employees or only employees_with_records?
  
If OPTION C used: Verify carried-forward values are clearly marked
  (so UI doesn't show yesterday's data as today's)
```

### Highest-Risk Areas
- **Trend window boundaries** — ±1 day = cascading error to all signals
- **Confidence thresholds** — if off by 1 day, massive users jump from "low" to "high" confidence
- **Division by zero in variance** — could produce NaN, breaking sorting

### Manual Test
```
1. Take EMP001 with known activity history (e.g., 19 days)
2. Manually calculate: avg(days 6-19), avg(days 1-5), variance, trend
3. Import; recompute snapshots
4. Verify snapshot.recent_avg_uph matches manual calculation ± 0.1
5. Verify trend_state matches manual classification
6. Verify confidence_label matches expected level
7. Change one activity record (e.g., April 10); recompute
8. Verify snapshot changes correctly, not stale
```

---

## **STEP 4: Signal Generation & Persistence (CRITICAL)**

### Scope
Files: `services/daily_signals_service.py`, `repositories/daily_signals_repo.py`, 
`services/today_home_service.py`, `services/decision_engine_service.py`

### Likely Logic Bugs
- **Stale detection logic wrong:** Doesn't detect when snapshots rebuilt but payload not updated
- **Queue item ordering:** Sorted by score, but secondary sort inconsistent (same score items shuffle?)
- **Home sections logic:** "Top performers" logic backwards (shows worst instead of best?)
- **Decision item scope:** Missing employees who should be ranked, or showing duplicates
- **Signal payload serialization:** Complex nested dicts fail JSON round-trip (lose precision, types)
- **Timestamp freshness:** `computed_at` stale but payload not rebuilt

### Specific Checks

#### 4.1: Stale Payload Detection
```
Check: pages/today.py:_precomputed_payload_looks_stale()

Logic should detect:
  - Demo mode + rows_processed > 100 + emp_count = 0 + valid snapshots exist for today
    → Payload is stale (snapshots exist but payload empty)

Test cases:
  1. Demo import, 608 rows, emp_count=32, days=19, queue_items=5
     → NOT stale (emp_count > 0)
  
  2. Demo import, 608 rows, emp_count=0, days=0, queue_items=[]
     → IS stale (rows >> summary mismatch + valid snapshots for today exist)
  
  3. Demo import, 50 rows, emp_count=5, days=5, queue_items=[]
     → NOT stale (rows < 100, too small to judge)

Verify:
  - Stale detection returns True/False correctly
  - Doesn't false-positive on healthy payloads
  - Doesn't false-negative on broken payloads
```

#### 4.2: Queue Item Ordering
```
Check: services/daily_signals_service.py (or today_queue_service.py)

Question: When two employees have same score, what's secondary sort?
  - By employee_id (alphabetical)?
  - By recency (last_event_at)?
  - By confidence (high → low)?
  - Random?

Verify:
  - If deterministic, document sort order
  - If should be deterministic, ensure it's not random
  - If multiple sorts, check ORDER BY clause has secondary columns

Test:
  Import data where two employees have identical confidence/trend/actions
  → Verify same order on multiple runs
```

#### 4.3: Home Sections Logic
```
Check: services/today_home_service.py

Expected behavior for each section:
  - top_insight_cards: Highest confidence + most actionable
  - top_performers: Highest avg UPH, meeting/exceeding targets
  - exceptions: Operational context (weather, equipment down, etc.)
  - recognition: Rare high performers (>2 std dev above mean)

Verify:
  - top_performers NOT showing lowest performers
  - recognition NOT showing average employees
  - All sections filtered for eligibility (not showing suppressed items)

Test:
  1. Import data with clear high/low performers
  2. Check home_sections.top_performers has highest-UPH employees
  3. Check top_performers[0].avg_uph > top_performers[-1].avg_uph (sorted descending)
```

#### 4.4: Signal Payload Serialization
```
Check: daily_signals table structure and JSON serialization

Test:
  1. Compute daily_signals payload
  2. Write to daily_signals table
  3. Read back from table
  4. Deserialize JSON
  5. Verify all fields match:
     - queue_items list length
     - home_sections keys
     - import_summary numeric fields
     - attention_summary.ranked_items count

Verify:
  - No loss of precision in floats (e.g., 51.234 → 51.23)
  - No type confusion (int vs string, date vs datetime)
  - Nested dicts properly nested, not flattened
```

#### 4.5: Timestamp Freshness
```
Check: is computed_at always recent?

Code should:
  1. Compute snapshots (if stale)
  2. Compute signals → write daily_signals with computed_at = now()
  3. On page load, check computed_at vs today
     - If computed_at = today, use cache
     - If computed_at < today, rebuild

Verify:
  - computed_at is set when payload written (not left NULL)
  - computed_at is recent datetime (within last hour, not days old)
  - Stale payload gets rebuilt, not displayed
```

### Highest-Risk Areas
- **Stale detection logic** — one condition wrong = shows old data indefinitely
- **Queue item ordering** — if random, supervisors see different queue each page load
- **Serialization round-trip** — loses precision in numeric fields breaks sorting

### Manual Test
```
1. Import demo data
2. Check daily_signals table: payload should exist
3. Read payload JSON; verify all keys present
4. On second page load, verify same queue_items order
5. Manually change one snapshot; recompute signals
6. Verify computed_at updated
7. Verify queue changed appropriately (no stale items)
```

---

## **STEP 5: State Management & Caching (CRITICAL)**

### Scope
Files: `core/session.py`, `pages/today.py` (caching + recovery), `core/dependencies.py`

### Likely Logic Bugs
- **Cache invalidation incomplete:** `_bust_cache()` doesn't clear all @st.cache_data decorators
- **Recovery lock timeout:** Lock expires but new recovery doesn't check old completion timestamp
- **Session state leak:** Stale state from previous user visible to new user (multiuser confusion)
- **Stale flag logic:** `_post_import_refresh_pending` set but never cleared, causing infinite rebuilds
- **Race condition:** Two concurrent reruns both pass recovery guard, execute rebuild twice
- **Cache key collisions:** Different tenants see each other's cached data

### Specific Checks

#### 5.1: Cache Invalidation Coverage
```
Check: core/dependencies.py:_bust_cache()

Question: Does it clear ALL @st.cache_data decorated functions?

Audit:
  1. Search codebase for @st.cache_data decorators
  2. For each, verify clear() or cache_clear() called in _bust_cache()
  
Common places:
  - _cached_today_signals_payload() ✓?
  - _cached_recent_action_outcomes() ✓?
  - _cached_manager_outcome_stats() ✓?
  - _cached_today_action_state_lookup() ✓?
  - _cached_employees() ✓?
  - Other services/*/py with @st.cache_data? ✓?

Pattern to find:
  grep -r "@st.cache_data" --include="*.py" | wc -l
  (should match # of cache.clear() calls in _bust_cache())
  
If count differs, some caches aren't being cleared.
```

#### 5.2: Recovery Lock Timeout & Race Condition
```
Check: pages/today.py:_attempt_signal_payload_recovery()

Lock logic should:
  1. Check if recovery_lock_key is set AND (now - started_at) < TTL
     → If yes, return False (skip recovery)
  2. If lock not set OR expired:
     - Set recovery_lock_key = True
     - Set started_at = now
     - Execute recovery
     - Clear lock (in finally block)

Audit for bugs:
  1. Is there check for both conditions? (lock AND time < TTL)
  2. Is started_at set BEFORE recovery starts?
  3. Is lock cleared in finally block?
  4. What if recovery takes longer than TTL?
     - Lock expires during recovery
     - New request sees lock expired, starts second recovery
     - Both run concurrently

Test race condition:
  1. Recompute snapshots (takes 5 seconds)
  2. During execution, refresh page (triggers rerun)
  3. Should NOT start second rebuild
  4. Second rebuild should wait or skip
  
Verify in logs: Only one snapshot recompute job per date
```

#### 5.3: Post-Import Refresh Pending Flag
```
Check: pages/today.py and services/import_pipeline/

Flag lifecycle:
  1. Import completes → set _post_import_refresh_pending = True
  2. Today page detects flag → triggers recovery
  3. Recovery completes → CLEARS flag = False
  4. Next load: flag is False, no unnecessary rebuild

Verify:
  - Flag set in import completion handler
  - Flag checked in today.py before recovery
  - Flag CLEARED in recovery completion (in finally or at end)
  
If NOT cleared: Infinite rebuilds every page load!

Test:
  1. Import data
  2. Check flag: should be True
  3. Load Today page
  4. Check flag: should be False (cleared after rebuild)
  5. Refresh page
  6. Should NOT rebuild again (no need)
```

#### 5.4: Session State Multiuser Isolation
```
Check: core/session.py:init_session_state()

Question: Is session_state specific to each browser user?

Streamlit behavior:
  - Each browser session gets own session_state dict (by design)
  - Should NOT leak between users
  
But verify:
  - No shared global variables (cache module-level dicts, not session_state)
  - No user_id in global cache keys → could collide if same key for different users
  
Example BAD pattern:
  _GLOBAL_CACHE = {}  # Shared across all sessions!
  def get_snapshot(employee_id):
    if employee_id not in _GLOBAL_CACHE:
      _GLOBAL_CACHE[employee_id] = expensive_query(employee_id)
    return _GLOBAL_CACHE[employee_id]
  
  User A queries EMP001 → cached
  User B queries EMP001 → gets User A's data!

Check:
  - No module-level dict caches
  - All caching via @st.cache_data (built-in Streamlit isolation)
  - All session data stored in st.session_state (not global)
```

#### 5.5: Cache Key Collisions Between Tenants
```
Check: @st.cache_data decorated functions

Pattern:
  @st.cache_data(ttl=300)
  def _cached_employees(*, tenant_id: str):
    ...
  
Cache key includes function name + args, so:
  _cached_employees(tenant_id="TENANT_A") → different cache entry
  _cached_employees(tenant_id="TENANT_B") → different cache entry
  
✓ Good: tenant_id in args → different caches
✗ Bad: tenant_id NOT in args → cache shared across tenants

Audit:
  For each @st.cache_data function:
    - Does it have tenant_id parameter?
    - Is tenant_id passed to function?
    - If it queries tenant data, are all query params in function signature?

Bad example:
  @st.cache_data
  def _cached_snapshots():
    tenant_id = st.session_state.get("tenant_id")  # NOT IN SIGNATURE!
    return query_snapshots(tenant_id)
  
  Streamlit doesn't know cache depends on tenant_id
  Cache key ignores tenant_id
  Different users share same cache!

Good example:
  @st.cache_data
  def _cached_snapshots(*, tenant_id: str):
    return query_snapshots(tenant_id)
  
  Cache key includes tenant_id
  Different tenants get different cache entries
```

### Highest-Risk Areas
- **`_bust_cache()` incomplete** — new user loads old employee data from previous user's cache
- **Recovery lock race condition** — two concurrent recomputes corrupt snapshot state
- **Cache key without tenant_id** — tenant A sees tenant B's employee list

### Manual Test
```
1. Login as User A (tenant A), import data
2. View employee EMP001 with UPH = 50.0
3. Logout
4. Login as User B (tenant B), import data for EMP001 with UPH = 75.0
5. Check: User B should see UPH = 75.0, NOT 50.0 (cached from User A)
6. If still shows 50.0 → cache key collision bug

Also test:
7. Import data
8. Check _post_import_refresh_pending = True
9. Load Today page
10. Check _post_import_refresh_pending = False (cleared)
11. Refresh page
12. Check logs: should see only ONE snapshot recompute, not two
```

---

## PHASE 2: HIGH LOGIC (Steps 6-10)

These components contain algorithmic logic where off-by-one errors and boundary conditions cause systematic bias.

---

## **STEP 6: Data Ingestion & Validation (HIGH)**

### Scope
Files: `services/import_pipeline/*.py`, `pages/import_page.py`, `services/import_quality_service.py`

### Likely Logic Bugs
- **Stage sequencing wrong:** Rows validated before mapping, or mapping before parse
- **State machine violation:** Jump from stage 2 → stage 4, skipping stage 3
- **Batch processing off-by-one:** Last batch dropped or first batch duplicated
- **Error aggregation:** Some errors ignored, others break entire import
- **Preview stats wrong:** Shows 500 rows valid but imports 600 (mismatch)
- **Demo seed bypass:** Demo data doesn't use validation pipeline (different code path)

### Specific Checks

#### 6.1: Pipeline Stage Sequencing
```
Expected order:
  1. Parse CSV bytes → detect structure, split into rows
  2. Map columns → user's columns → system schema
  3. Validate rows → check constraints
  4. Build preview → show statistics, issues
  5. Get user confirmation → user clicks "import"
  6. Process rows → insert to DB

Check pages/import_page.py:
  - Is each stage executed in order?
  - Can user jump stages (e.g., confirm without preview)?
  - If validation fails on one row, does entire import fail or skip that row?
  
Verify state machine:
  stage = "parse" → stage = "map" → stage = "validate" → stage = "preview" → stage = "process"
  
  NOT:
  stage = "parse" → stage = "process"  (skipped validate!)
```

#### 6.2: Batch Processing Boundaries
```
Check: When importing large file (e.g., 10,000 rows)

Question: Does chunking process each row exactly once?

Code pattern to verify:
  rows = parse_csv(file_bytes)  # All rows
  validated_rows = validate_all(rows)  # Should = all rows
  insert_batch(validated_rows)  # Insert exactly validated_rows, not 1 less
  
  # Check: Last row not dropped, first row not duplicated
  
Test:
  1. Create CSV with 7 rows (not multiple of batch_size)
  2. Import with batch_size=3
     - Batch 1: rows 0-2 (3 rows)
     - Batch 2: rows 3-5 (3 rows)
     - Batch 3: rows 6 (1 row)
  3. Verify all 7 rows inserted (not 6 or 8)
```

#### 6.3: Error Handling
```
Check: How are validation errors handled?

Question: If 1 of 608 rows has invalid date, what happens?

Scenarios:
  A. Entire import fails (strict mode)
  B. Invalid row skipped, 607 rows imported (lenient mode)
  C. User shown issue groups, can choose "skip", "fix", or "cancel"

Check code path in:
  services/import_quality_service.py:build_issue_groups()
  services/import_pipeline/validator.py
  pages/import_page.py (user choices)

Verify:
  - Invalid row count accurate
  - Valid row count accurate
  - User can't accidentally import + skip at same time
```

#### 6.4: Preview Stats Accuracy
```
Check: pages/import_page.py preview shows stats matching what gets imported

Stats to verify:
  - Valid rows count
  - Error rows count
  - Date range (earliest → latest)
  - Employee count
  - Department breakdown

Test:
  1. Show import preview
  2. Note: "500 valid rows, 8 errors, 25 employees, Apr 1-19"
  3. Click import
  4. Verify: activity_records table has 500 rows (not 492 or 508)
  5. Count employees: should be exactly 25
  6. Verify date range: min(date) ≈ Apr 1, max(date) ≈ Apr 19
```

#### 6.5: Demo Seed Path Bypass
```
Check: Demo import uses same validation pipeline

Pattern:
  Real import: CSV → parse → validate → insert
  Demo import: JSON seed → ??? → insert
  
Verify demo seed:
  1. Uses same validation as CSV (or at least checks basic constraints)
  2. Doesn't insert invalid data (e.g., future dates, negative UPH)
  3. Normalized timestamp fields (empty strings removed)

In pages/import_page.py:
  _seed_demo_action_storyline() → _normalize_seed_payload() 
  Should strip blank timestamps before insert
```

### Highest-Risk Areas
- **Stage sequencing wrong** — rows processed before validation inserted bad data
- **Preview vs actual mismatch** — user thinks 500 rows imported, but really 492
- **Demo seed validation gap** — demo data has bugs that CSV path would have caught

### Manual Test
```
1. Create CSV: 1 header row + 10 data rows
2. Make row 5 have invalid date: "2026-13-01" (month 13)
3. Import via strict mode
4. Verify: Import fails, shows error on row 5
5. Create same CSV, but in lenient mode: skip errors
6. Verify: 9 rows imported, row 5 skipped
7. Count database: activity_records for tenant = 9 rows ✓

Also test:
8. Import demo data
9. Count demo rows: should match expected (608 for full demo)
10. Check: All timestamps valid (not empty or NULL)
11. Check: All numeric fields are actually numeric (not text)
```

---

## **STEP 7: Trend Classification & Patterns (HIGH)**

### Scope
Files: `services/trend_classification_service.py`, `services/action_recommendation_service.py`

### Likely Logic Bugs
- **Boundary condition off-by-one:** "below_expected if < 95%" should be "<=95%"? 
- **Direction detection wrong:** recent > prior should be "improving", not "declining"
- **Edge case sequences:** One spike then stable = what? (Not "improving", should be "stable" or "inconsistent"?)
- **Repeat count logic:** Same issue twice = 2 repeats or 1 repeat + baseline?
- **NaN/NULL in sequences:** [50, 48, NULL, 47, 46] → should still detect declining?

### Specific Checks

#### 7.1: Boundary Condition Verification
```
Check: services/trend_classification_service.py

Exact thresholds:
  - below_expected: recent_avg < (expected * 0.95)  [i.e., 5% below]
    or recent_avg <= (expected * 0.95)?
  - inconsistent: coefficient_of_variation > 0.15  [15% CV]
    or >= 0.15?

Test boundary cases:
  expected_uph = 100
  
  Test 1: recent_avg = 94.9
    → 94.9 < 95 → below_expected ✓
  
  Test 2: recent_avg = 95.0
    → 95.0 < 95? NO → not below_expected
    → Should this be "95.0 <= 95" → below_expected? (Clarify with product)
  
  Test 3: recent_avg = 95.1
    → 95.1 < 95? NO → not below_expected ✓

For each threshold, document:
  - Exact comparison operator (<, <=, >, >=)
  - Why that operator chosen
  - Effect of ±0.1 change
```

#### 7.2: Direction Detection
```
Check: Improving vs Declining vs Stable

Logic:
  if avg(recent) > avg(prior):
    trend = "improving"
  elif avg(recent) < avg(prior):
    trend = "declining"
  else:
    trend = "stable"

Test cases:
  Test 1: recent_avg = 55, prior_avg = 50
    → 55 > 50 → improving ✓
  
  Test 2: recent_avg = 45, prior_avg = 50
    → 45 < 50 → declining ✓
  
  Test 3: recent_avg = 50, prior_avg = 50
    → 50 == 50 → stable ✓
  
  Test 4: recent_avg = 50.001, prior_avg = 50.000
    → Should this be "improving" or "stable" (rounding error)?
```

#### 7.3: Edge Case Sequences
```
Check: How does trend classifier handle unusual patterns?

Scenario A: Single spike then return to normal
  [50, 50, 50, 80, 50, 50] → ?
  Expected: "stable" with note "outlier detected"
  Bad result: "improving" (only because single value is high)

Scenario B: Gradual rise
  [50, 52, 54, 56, 58] → "improving" ✓

Scenario C: High variance, flat mean
  [50, 30, 70, 50, 70, 30] → "inconsistent" ✓

Scenario D: One day of data (new employee)
  [55] → "early_signal" ✓

Check code:
  - Does classifier detect outliers (spike)?
  - Does it weight recent more than old?
  - Does it handle single-value sequences?
```

#### 7.4: Repeat Pattern Count
```
Check: services/action_recommendation_service.py:get_repeat_offenders()

Question: What's counted as a "repeat"?

Scenarios:
  A. Same issue 3 times in different actions → repeat_count = 3 or 2?
  B. Issue appears in weeks 1, 2, 3 → is week 3 a "repeat" of weeks 1&2?
  C. Issue "performance below expected" for 3 days → 3 repeats or 1 pattern?

Audit:
  - How is repeat_count computed?
  - Is it # times appeared or # times after initial?
  - What's the time window (days, weeks)?
  
Test:
  1. Create actions for EMP001:
     - 2026-04-10: "Performance below 95%"
     - 2026-04-15: "Performance below 95%"
     - 2026-04-18: "Performance below 95%"
  2. Query repeat_offenders
  3. Verify EMP001.repeat_count = 3 (or 2, depending on definition)
  4. Verify consistent with attention scoring weights
     (if repeat_count=2 weights 10 points, verify 3 repeats still only +10, not +15)
```

#### 7.5: NULL/Missing Value Handling
```
Check: Trend calculated even if some values missing

Test:
  Activity records: [50, 48, NULL, 47, 46]  (one day missing shift)
  
  Should classifier:
  A. Ignore NULL, compute trend on [50, 48, 47, 46]
  B. Reject, return "insufficient_data"
  C. Treat NULL as 0, compute trend on [50, 48, 0, 47, 46]
  
  Expected: Option A (ignore missing)
  
Verify:
  - NULL values not included in avg()
  - Variance not inflated by NULL
  - Trend still computed if 2+ non-NULL values
```

### Highest-Risk Areas
- **Boundary off-by-one** — 94.9 vs 95.0 classification flips
- **Direction backward** — "improving" when should be "declining"
- **Outlier handling** — single spike classified as trend instead of anomaly

### Manual Test
```
1. Import data with known pattern:
   - Days 1-7: UPH 50-52 (stable)
   - Days 8-14: UPH 48-50 (declining)
   - Days 15-19: UPH 51-53 (improving)

2. Recompute snapshots
3. Verify each segment:
   - EMP at day 7: trend = "stable"
   - EMP at day 14: trend = "below_expected" or "declining"
   - EMP at day 19: trend = "improving"

4. Create duplicate action for EMP001
5. Verify repeat_count increments correctly
```

---

## **STEP 8: Attention Scoring & Prioritization (HIGH)**

### Scope
Files: `services/attention_scoring_service.py`, `domain/risk_scoring.py`

### Likely Logic Bugs
- **Weight formula wrong:** Base 50, add factors, but what if sum > 100? (Capped? Scaled?)
- **Negative scores not applied:** Low confidence -20 points, but could leave score < 0?
- **Double-counting factors:** Trend + variance might both add for same data
- **Tier threshold off-by-one:** high ≥ 75 vs > 75 produces different results
- **Suppression floor logic:** < 30 suppressed, but what about exactly 30?
- **Tie-breaking:** Two employees both score 75 (high tier) — which shown first?

### Specific Checks

#### 8.1: Score Calculation & Bounds
```
Check: services/attention_scoring_service.py:score_attention_item()

Expected model (from docstring):
  base = 50
  trend_declining: +25
  trend_below_expected: +15
  trend_inconsistent: +10
  trend_improving: +5
  repeat_3_or_more: +20
  repeat_2: +10
  repeat_1: +5
  overdue_follow_up: +20
  due_today_follow_up: +10
  open_exception: +15
  variance_gt_20: +15
  variance_10_19: +8
  confidence_high: +10
  confidence_low: -20
  completeness_complete: +5
  completeness_partial: -5
  completeness_limited: -15
  
  final_score = clamp(0, base + sum(factors), 100)

Test:
  1. Employee with all positive factors:
     base(50) + declining(25) + repeat_3(20) + overdue(20) + variance_gt20(15) + 
     high_conf(10) + complete(5) = 145 → clamp to 100 ✓
  
  2. Employee with all negative factors:
     base(50) + improving(5) + no_repeat(0) + no_due(0) + low_variance(0) +
     low_conf(-20) + limited(-15) = 20 → clamp to 0? or stays 20?

Check code:
  - Is score clamped to [0, 100]?
  - What's minimum possible score?
  - What's maximum possible score?
```

#### 8.2: Tier Thresholds
```
Check: Tier assignment

Expected:
  score >= 75: high
  50 <= score < 75: medium
  30 <= score < 50: low
  score < 30: suppressed

Edge cases:
  score = 75 → high ✓
  score = 74 → medium ✓
  score = 50 → medium ✓
  score = 49 → low ✓
  score = 30 → low ✓
  score = 29 → suppressed ✓

Verify exact operators (< vs <=) in code.
```

#### 8.3: Double-Counting Detection
```
Check: Could same data point contribute twice to score?

Example:
  Employee has:
    - Trend: below_expected (+15)
    - Variance: 18% (+8)
    
  Both indicate low performance, but counted separately (not double-counted)
  
  But check:
    - Repeat pattern from trend classification
    - Repeat pattern from action_recommendation_service
    
  If both added, that's double-counting!

Verify:
  - Repeat count comes from single source
  - Variance computed once, not added twice
  - Confidence applied once per item
```

#### 8.4: Tie-Breaking
```
Check: When two employees have identical score, how ordered?

Test:
  EMP001: score = 75 (high), confidence = high, last_event = 2026-04-18
  EMP002: score = 75 (high), confidence = high, last_event = 2026-04-16
  
  Expected order: EMP001 first (more recent event)
  
Verify in code:
  - Secondary sort by last_event_at (descending)
  - Or by employee_id (alphabetical)
  - Or random (NOT acceptable)

Test:
  1. Import data with two employees having identical metrics
  2. Score both
  3. Run scoring again
  4. Verify same order (not random shuffle)
```

### Highest-Risk Areas
- **Score clamping logic** — score goes negative but not capped = wrong tier assignment
- **Tier thresholds** — off-by-one pushes employee from low→medium→high
- **Double-counting factors** — same reason added twice = inflated score

### Manual Test
```
1. Create two employees with known data:
   - EMP_HIGH: improving trend, repeat issues, overdue follow-up
   - EMP_LOW: stable trend, no repeats, on-time

2. Score both
3. Verify EMP_HIGH score > EMP_LOW score
4. Verify EMP_HIGH tier = "high", EMP_LOW tier = "low"
5. Create EMP_MID with score exactly at boundary (75, 50, 30)
6. Verify tier assignment matches threshold exactly

7. Create two identical employees
8. Score both
9. Refresh multiple times
10. Verify same order (deterministic, not random)
```

---

## **STEP 9: Decision Engine & Ranking (HIGH)**

### Scope
Files: `services/decision_engine_service.py`, `services/decision_surfacing_policy_service.py`

### Likely Logic Bugs
- **Combining scores wrong:** How to weight attention_score + action_score?
- **Primary reason missing:** Empty reason string = poor UX
- **Confidence downgrade:** Should confidence degrade if action is due?
- **State transitions:** Can resolved action appear in decision items? (Should not)
- **Ordering unstable:** Same data produces different final ranking on reruns

### Specific Checks

#### 9.1: Score Combination Formula
```
Check: services/decision_engine_service.py:build_decision_items()

Question: How are attention_score + action_score combined for final_score?

Expected logic:
  attention_score: 0-100 (urgency based on trends)
  action_score: 0-100 (urgency based on open actions)
  
  final_score = weighted_avg(attention_score, action_score)
               or max(attention_score, action_score)
               or attention_score if action else action_score
               
Check code:
  - Is formula documented?
  - Is it deterministic?
  - Does action_score override attention_score or blend?

Test:
  EMP001: attention_score = 60, action_score = 80
  → final_score should be ~70 (if average), or 80 (if max), or 60 (if attention takes precedence)
  
  Verify which logic is implemented.
```

#### 9.2: Primary Reason Generation
```
Check: services/decision_engine_service.py:_get_primary_reason()

Question: Can reason be empty/NULL?

Expected:
  - Always populate primary_reason (never NULL)
  - Reason reflects top factor (e.g., "overdue follow-up", "declining trend + repeat issue")
  - Reason is user-friendly ("performance below expected")

Test:
  1. Score employee with multiple factors
  2. Verify decision_item.primary_reason is non-empty
  3. Verify reason matches top factor (not random reason)
```

#### 9.3: State Filtering
```
Check: Do resolved actions appear in decision items?

Expected:
  - Only open/follow_up_pending actions included
  - Resolved actions excluded
  - Actions with past due dates don't disappear

Verify:
  action.status in ["open", "follow_up_pending"] → include
  action.status = "resolved" → exclude
  
Test:
  1. Create action, resolve it
  2. Recompute decision items
  3. Verify: employee NOT in decision items (or action_score = 0)
```

#### 9.4: Final Ordering Stability
```
Check: Does final_score determine order consistently?

Test:
  1. Compute decision_items
  2. Record order: [EMP001, EMP002, EMP003]
  3. Recompute decision_items (same data)
  4. Verify: Same order [EMP001, EMP002, EMP003]
  5. Run 5+ times
  6. Verify: Always same order (not random shuffle)

If different orders, check:
  - Tie-breaking order deterministic?
  - Secondary sort stable?
```

### Highest-Risk Areas
- **Score combination formula** — if additive and unbounded, scores inflation
- **Primary reason empty** — users see blank explanation
- **Ordering unstable** — supervisors see different queue on each refresh

### Manual Test
```
1. Create scenario: 3 employees
   - A: high attention_score, no action
   - B: low attention_score, overdue action
   - C: medium attention_score, due_today action

2. Compute decision_items
3. Verify order: should reflect combined urgency
4. Verify each has non-empty primary_reason
5. Run decision engine 3x
6. Verify consistent order each time
```

---

## **STEP 10: UI State & Navigation (HIGH)**

### Scope
Files: `core/navigation.py`, `core/page_router.py`, `pages/today.py`, `pages/employees.py`, all page files

### Likely Logic Bugs
- **Page transition state pollution:** Drill-down to employee, go back to Today, employee filter still active (should reset)
- **Session state not cleared:** User A selects employee; logs out; User B logs in, sees User A's selected employee
- **Stale drill-down context:** Click drill-down from signal, navigate away, context lost
- **Lost form data:** User fills form, page reloads, form data cleared (not saved)
- **Back button confusion:** Browser back button doesn't match app navigation

### Specific Checks

#### 10.1: Page Transition State Reset
```
Check: When navigating from Today → Team → Productivity, is state reset?

Expected:
  - Today: queue_filter = "all" (reset on each entry)
  - Team: emp_view = "Overview" (reset on each entry)
  - Productivity: date_range = "7_days" (reset on each entry)

Verify:
  1. View Today, set queue_filter = "overdue"
  2. Navigate to Team page
  3. Navigate back to Today
  4. Verify: queue_filter reset to "all" (not still "overdue")

Check code:
  pages/today.py: if "today_queue_filter" not in st.session_state: ...
  (should reset on page entry, not remember across navigations)
```

#### 10.2: Drill-Down Context Preservation & Cleanup
```
Check: Drill-down drill-down keeps context, but cleanup on exit

Pattern:
  Today page → click "View details" → set cn_selected_emp = "EMP001"
  → Drill-down shows EMP001 detail
  → Click back or navigate away → cleanup cn_selected_emp?

Expected:
  - Context preserved while viewing detail
  - Context cleared when leaving detail page
  - Not reused for wrong employee if navigate back

Verify:
  pages/today.py: sets st.session_state["cn_selected_emp"] = employee_id
  pages/employees.py: reads st.session_state["cn_selected_emp"]
  
  After viewing detail, check:
  - Click "back" → cn_selected_emp cleared or reset to None
  - Navigate to different page → cn_selected_emp cleared
```

#### 10.3: Form Data Persistence
```
Check: Multi-step forms don't lose data on page refresh

Example: Import page
  Step 1: Upload CSV (file_path saved)
  Step 2: Confirm mapping (mapping_profile saved)
  Step 3: Click "next"
  → Page reloads (Streamlit rerun)
  Step 4: Verify: file_path + mapping_profile still available

Expected:
  - All form data stored in st.session_state
  - Survives page reruns
  - Cleared only when form submitted or cancelled

Check code:
  pages/import_page.py: save state in session_state before buttons
```

#### 10.4: Session State Multiuser Isolation
```
Check: User A's selections not visible to User B

Test:
  1. User A logs in, opens Today
  2. User A sets queue_filter = "overdue"
  3. User A logs out
  4. User B logs in
  5. User B opens Today
  6. Verify: queue_filter = "all" (not "overdue" from User A)

Expected:
  - Each user gets fresh session_state
  - No cross-user pollution

This should be automatic with Streamlit, but verify:
  - Session state not stored in module-level globals
  - No shared cache with user-specific data
```

### Highest-Risk Areas
- **State not reset on page entry** — users see stale filters/selections
- **Drill-down context leak** — showing wrong employee detail
- **Form data loss** — user fills form, page reloads, data gone

### Manual Test
```
1. View Today, set queue_filter = "repeat"
2. Click employee drill-down
3. View employee detail page
4. Click back to Today
5. Verify: queue_filter is "all" (reset), not "repeat" (stale)

6. Fill import form, map columns, preview
7. Refresh browser
8. Verify: form state preserved (still on preview, not back to upload)

9. Open incognito window, log in as different user
10. Verify: No state from User A visible
```

---

## PHASE 3: MEDIUM RISK (Steps 11-15)

These components have moderate impact if buggy. Issues are usually visible but may cause silent failures.

---

## **STEP 11: Action Lifecycle Management (MEDIUM)**

**Scope:** `services/action_lifecycle_service.py`, `repositories/actions_repo.py`, `services/action_query_service.py`

**Likely Bugs:**
- State transitions not enforced (resolved action can be reopened?)
- Event timestamps not ordered (event_at in future?)
- Outcome recorded but action status not updated
- Null owner (recorded_by empty)

**Key Checks:**
1. State transitions: open → follow_up_pending → resolved (only valid paths)
2. Event ordering: event_at <= now, no future timestamps
3. Consistency: action.status matches last event.event_type
4. Required fields: All action events have recorded_by, event_at, event_type

**Manual Test:** Create action → log event → verify status changed; try invalid state transition → should fail or no-op

---

## **STEP 12: Business Logic & Heuristics (MEDIUM)**

**Scope:** `domain/benchmarks.py`, `services/target_service.py`, `services/activity_comparison_service.py`

**Likely Bugs:**
- Benchmark values hardcoded incorrectly (expected_uph = 100 for all roles?)
- Variance thresholds not matching product spec
- Risk scoring weights not calibrated to domain knowledge
- Threshold inconsistencies (one place "high" is >80, another is >75)

**Key Checks:**
1. Expected UPH values: Do they match actual data distribution?
2. Variance thresholds: Is 10% significant change or noise?
3. Risk scoring: Are weights proportional to business impact?
4. Consistency: Same threshold used everywhere, not duplicated differently

**Manual Test:** Check benchmark for each department; compare to actual average UPH; verify "below expected" triggers when actual < target

---

## **STEP 13: Employee & Roster Management (MEDIUM)**

**Scope:** `services/employees_service.py`, `repositories/employees_repo.py`, `pages/employees.py`

**Likely Bugs:**
- Archived employees shown in active list
- Duplicate employees created (same emp_id imported twice)
- Employee cache not updated after import
- Employee name changes not reflected in actions

**Key Checks:**
1. List active employees filters: status = "active"
2. Archived employees: status = "archived", hidden from UI
3. Duplicate detection: Unique constraint on (tenant_id, emp_id)
4. Cache invalidation: After import, employee cache cleared

**Manual Test:** Archive employee A; view Today → should not appear; reimport employee A; verify count correct (not 2)

---

## **STEP 14: External Integrations (MEDIUM)**

**Scope:** `services/email_service.py`, `services/billing_service.py`, `auth.py`

**Likely Bugs:**
- Email send fails silently (no error logged)
- Billing check gates wrong feature (pro feature in free tier)
- Auth token expiry not handled (login persists after expiry)
- Rate limiting ignored (bulk emails sent without delay)

**Key Checks:**
1. Email failures logged and visible
2. Feature gates match tier definitions
3. Auth token validation on each request
4. Rate limiting implemented for external calls

**Manual Test:** Send email; verify in logs; disable email API; verify error logged; check billing tier gates; verify free user can't access pro features

---

## **STEP 15: Background Jobs & Scheduling (MEDIUM)**

**Scope:** `services/import_pipeline/job_service.py`, `jobs/entrypoints.py`, scheduler setup

**Likely Bugs:**
- Failed jobs not retried (stuck forever)
- Scheduler doesn't fire (cron job misconfigured)
- Job queue has orphaned locks (job failed but lock not released)
- Job output not logged (hard to debug failure)

**Key Checks:**
1. Job failures logged with error details
2. Retry logic: Failed jobs retried N times with backoff
3. Lock release: On failure, lock cleared (not orphaned)
4. Scheduler verification: Jobs fire at expected times

**Manual Test:** Trigger snapshot recompute; simulate failure (e.g., DB connection error); verify retry happens; check logs for error

---

## Execution Checklist

### Before You Start
- [ ] Clone repo to clean environment
- [ ] Set up test database (isolated from production)
- [ ] Activate venv
- [ ] Have access to codebase search tools

### Per Step Execution
- [ ] Read scope section
- [ ] Run code searches for files mentioned
- [ ] Check each "Specific Checks" subsection
- [ ] Execute "Manual Test" if possible
- [ ] Log findings: PASS / FAIL / INCONCLUSIVE / NEEDS INVESTIGATION

### Documentation
- [ ] For each FAIL: Note exact line of code, expected vs actual behavior
- [ ] For NEEDS INVESTIGATION: Document unclear areas for follow-up
- [ ] For PASS: Brief note (e.g., "Tenant filters present on all 12 queries in actions_repo")

---

## Risk Prioritization Summary

**Run in this order:**
1. Database (data isolation)
2. Activity Records (aggregation correctness)
3. Snapshots (foundation for all signals)
4. Signals (what users see)
5. Caching/State (system stability)
6-10. Logic/Ranking (algorithmic correctness)
11-15. Integrations (visible failures)

**Expected time per step:** 15-30 min (code review) + 10-20 min (manual test if possible)
