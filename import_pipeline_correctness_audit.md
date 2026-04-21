# Import Pipeline Correctness Audit

Date: 2026-04-21
Scope: read-only audit of current import pipeline behavior (no code changes)

## A. Full Data Path

### 1) Upload -> Parse -> Initial Mapping
- Entry point: `pages/import_page.py` in `_import_step1` and `_import_step2`.
- File parsing:
  - CSV: `data_loader.parse_csv_bytes`
  - Excel: `pandas.read_excel` path in `_import_step1`
- Auto-detection:
  - `data_loader.auto_detect` using `FIELD_ALIASES`
- Manual mapping fallback:
  - `_import_step2` allows explicit mapping per file/session.
- Required field gating:
  - UI Step 2 requires `EmployeeID` + `EmployeeName` + either:
    - UPH mode: `UPH`, or
    - Calculated mode: `Units` + `HoursWorked`

### 2) Preview -> Candidate Rows -> Duplicate/Overlap Signals
- Preview runner:
  - `jobs.entrypoints.run_import_preview_job`
  - `services.import_pipeline.orchestrator.preview_import`
- Preview parse/validate stack:
  - `services.import_pipeline.parser.parse_sessions_to_rows`
  - `services.import_pipeline.validator.validate_rows`
- Preview candidate aggregation key:
  - `(emp_id, work_date, department)`
- File-level exact duplicate detection:
  - `orchestrator._build_import_fingerprint`
  - `orchestrator._find_matching_upload_by_fingerprint`
- Import page also computes legacy candidate rows and overlap estimates using:
  - `services.import_service._build_candidate_uph_rows`
  - existing `uph_history` lookup by employee/date key

### 3) Write Path (Authoritative Current Import Write)
- Triggered in `pages/import_page.py` `_import_step3` under Run pipeline action.
- Employee sync first:
  - `database.batch_upsert_employees`
- UPH batch build from session rows:
  - Aggregates to one daily row per employee/dept in `_import_step3`
- Exact duplicate import check:
  - `services.import_service._build_import_fingerprint`
  - `services.import_service._find_matching_upload_by_fingerprint`
  - If matched: entire batch skipped (`uph_batch=[]`)
- Overlap replacement behavior:
  - Existing `uph_history` rows matched by employee/date (dept-aware cleanup)
  - Write operation: `database.batch_store_uph_history`
  - Repository upsert conflict key: `tenant_id,emp_id,work_date,department`
- Upload event log:
  - `services.import_service._record_upload_event`
  - Metadata includes stats, trust summary, undo snapshot fragments, and postprocess state later

### 4) Postprocess (Deferred)
- Scheduled from import page via:
  - `jobs.entrypoints.run_import_postprocess_job_deferred`
- Postprocess does:
  - Activity ingest: `services.activity_records_service.ingest_activity_records_from_import`
  - Snapshot recompute: `services.daily_snapshot_service.recompute_daily_employee_snapshots` (only when `from_date` and `to_date` are non-empty)
- Persisted state machine in uploaded file metadata:
  - `queued`, `running`, `completed`, retry/failure states in `header_mapping.postprocess`

### 5) Today/Team Eligibility
- Team and Supervisor goal-status data source:
  - `services.daily_snapshot_service.get_latest_snapshot_goal_status`
  - underlying table: `daily_employee_snapshots`
- Today primary signal payload source:
  - `services.daily_signals_service.read_precomputed_today_signals`
  - underlying table: `daily_signals`
  - fallback: transient compute path when table unavailable
- Import completion state:
  - import page sets `_post_import_refresh_pending=True`
  - Today recovery path computes signals and flips to `False` only after successful compute/recovery

## B. Scenario Table

| Scenario | Expected behavior | Current actual behavior from code | Risk | Likely user-visible symptom | UI clarity today |
|---|---|---|---|---|---|
| Clean import with all-new rows | Rows parse, validate, write; downstream snapshots/signals become available shortly | Works in normal path. Writes `uph_history`, schedules deferred postprocess, then Today recovery computes signals | Low | Import succeeds, Today/Team populate after processing | Medium: messaging says saved vs ready, but readiness still depends on visiting Today/recovery cycle |
| Exact duplicate rows (same prior dataset fingerprint) | No net new writes; clearly shown as duplicate import | Implemented: fingerprint match causes full skip (`uph_batch=[]`), warning shown, stats mark exact duplicate | Low | "No new rows uploaded" | High |
| Overlap replacement rows | Existing employee/day rows replaced, stale dept variants removed, new values retained | Implemented via overlap detection + upsert + selective delete of stale dept rows | Low-Med | Existing values change after reimport; row counts may not equal inserted count | Medium |
| Mixed new + replacement + excluded rows | New rows inserted, overlapping keys replaced, invalid/excluded rows not written | Works, but preview and write paths are not fully symmetric (see UPH-mode bug below) | Medium | Preview counts may differ from actual write counts in edge modes | Medium-Low |
| Missing employee IDs | Row rejected from candidate/write | In write path, rows with blank `emp_id` are skipped (`continue`). In preview validator they are errors | Medium | Fewer rows written than uploaded | Medium |
| Missing/invalid dates | Should parse common formats or clearly reject; not silently remap date unless explicit | **Provable bug**: parser/write only accept `%Y-%m-%d`; common formats like `04/10/2026` fallback to selected work date, changing day semantics | High | Rows appear on wrong day; overlap/duplicate behavior and trend windows become misleading | Low-Medium: warning may appear in preview path, but write path also silently fallbacks |
| Invalid numeric values | Should reject or normalize deterministically with clear accounting | Units/hours invalid become `0` in write path; preview validator rejects `None` and negatives. Behavior is not fully aligned | Medium | Accepted rows may have `0` hours/units unexpectedly; UPH becomes 0 or from raw UPH only | Medium |
| Missing department | Should still write but be consistently categorized | Missing dept allowed; write attempts employee dept fallback, else blank. Snapshot layer normalizes process names | Low-Med | Rows can land under unassigned-like process grouping | Medium |
| Rows outside active date window | Written data should still be eligible when relevant date windows are recomputed | Postprocess recompute window uses min/max imported dates, so imported historical-only windows may not affect today snapshot immediately | Medium | Import succeeds but Today still appears unchanged if no current-date impact | Medium |
| Rows write successfully but do not produce Today/Team visibility | Should either become visible quickly or report pending/deferred state clearly | Possible when postprocess fails/deferred/retrying, when snapshots not current, or when Today signal payload not yet recomputed | High | "Import saved" but Team/Today still stale or empty | Medium: partial, but not fully state-driven from persisted postprocess metadata |
| Multi-file / repeat import of same file | Deterministic dedupe/replace behavior across repeated runs | Fingerprint dedupe works for exact repeat; overlap replacement works by key. Repeated imports can show varying preview/write counts in edge mapping modes | Medium | Confusing row-count deltas between preview and final stats | Medium-Low |
| Sample data path (demo) | Same pipeline semantics with demo labeling, no hidden behavior differences that affect correctness | Uses same import flow with `source_mode=demo`, plus demo seed actions/events and demo-specific redirects | Low-Med | Demo can appear immediately reusable/redirected even without rerun of full import | High for demo context, not for production correctness |

## C. Ranked Top Import Correctness Risks

1. High: Date parsing mismatch causes silent day reassignment
- Evidence:
  - `services.import_pipeline.parser.parse_sessions_to_rows` accepts only ISO `%Y-%m-%d` after truncation.
  - `pages/import_page.py` write path also parses only `%Y-%m-%d` and otherwise falls back to selected work date.
  - `data_loader.parse_date` supports many real-world formats but is not used by parser/write path.
- Impact:
  - Imported rows can be shifted to the wrong day, affecting overlap replacement, trends, and downstream eligibility.

2. High: Preview pipeline and write pipeline are not equivalent for UPH-only mapping
- Evidence:
  - UI Step 2 allows UPH-only mode (no Units/HoursWorked mapping required).
  - `validator.validate_rows` requires units and hours to be numeric and non-None; rows with missing units/hours are rejected.
  - `_import_step3` write path still writes rows in UPH-only mode (units/hours can be 0; UPH retained from raw column).
- Impact:
  - Preview can indicate low/zero valid rows while write still persists rows, creating correctness and trust mismatches.

3. High: "Write succeeded" does not guarantee Today/Team readiness
- Evidence:
  - Import sets `_post_import_refresh_pending=True` and defers postprocess.
  - Today/Team rely on snapshot/signal materialization (`daily_employee_snapshots`, `daily_signals`).
  - Readiness can lag or fail independently of write completion.
- Impact:
  - Users can see successful import but stale/no downstream signal visibility.

4. Medium: Numeric normalization differs across preview and write paths
- Evidence:
  - Preview validator rejects `None` and negatives as invalid row issues.
  - Write path coerces invalid/non-finite to 0 and may still include row.
- Impact:
  - Preview rejection counts and final write outcomes can diverge.

5. Medium: Department fallback behavior can create process attribution drift
- Evidence:
  - Missing dept resolved via employee cache fallback or left blank in write payload.
  - Snapshot processing normalizes process names; blank may collapse to unassigned-like buckets.
- Impact:
  - Team/process drilldowns may not match source-file expectations.

## D. Exact Files / Functions Involved

### Ingestion and mapping
- `pages/import_page.py`
  - `_import_step1`, `_import_step2`, `_import_step3`
- `data_loader.py`
  - `parse_csv_bytes`, `auto_detect`, `parse_date`
- `services/import_pipeline/mapper.py`
  - `review_mapping`
- `services/import_pipeline/parser.py`
  - `parse_sessions_to_rows`
- `services/import_pipeline/validator.py`
  - `validate_rows`
- `services/import_pipeline/orchestrator.py`
  - `preview_import`, duplicate fingerprint helpers

### Candidate row, duplicate, write
- `services/import_service.py`
  - `_build_candidate_uph_rows`, `_build_import_fingerprint`, `_find_matching_upload_by_fingerprint`, `_record_upload_event`
- `pages/import_page.py`
  - overlap detection/replacement block in `_import_step3`
- `repositories/import_repo.py`
  - `batch_store_uph_history` (upsert conflict key)

### Postprocess and downstream materialization
- `jobs/entrypoints.py`
  - `run_import_postprocess_job`, `run_import_postprocess_job_deferred`
- `services/activity_records_service.py`
  - `ingest_activity_records_from_import`
- `services/daily_snapshot_service.py`
  - `recompute_daily_employee_snapshots`, `get_latest_snapshot_goal_status`
- `repositories/daily_employee_snapshots_repo.py`
  - snapshot upsert/delete/list
- `services/daily_signals_service.py`
  - `compute_daily_signals`, `read_precomputed_today_signals`
- `services/today_home_service.py`
  - `get_today_signals`
- `pages/today.py`
  - `_attempt_signal_payload_recovery` and `_post_import_refresh_pending` handling
- `pages/team.py`
  - Team data load via `get_latest_snapshot_goal_status`
- `pages/common.py`
  - `load_goal_status_history` snapshot-first load path

### Existing tests covering parts of flow
- `tests/test_import_pipeline.py`
- `tests/test_jobs_scaffolding.py`

## E. Smallest Safe Fixes (Highest-Risk First)

1. Unify date parsing across preview and write paths (small, high value)
- Reuse `data_loader.parse_date` in:
  - `services/import_pipeline/parser.parse_sessions_to_rows`
  - `_import_step3` date extraction in `pages/import_page.py`
- Preserve fallback-date behavior only when parse fails, but log explicit row-level warning counts consistently.

2. Make preview validator semantics match supported UPH-only mode
- If UPH is mapped and valid, allow rows even when Units/HoursWorked are missing.
- Keep warnings when units/hours are absent, but do not reject rows that are valid via UPH source.
- This aligns preview candidate counts with actual write behavior.

3. Add explicit import-state boundary from write-complete to downstream-ready
- On import completion screen, source readiness from persisted postprocess state (`header_mapping.postprocess.state`) when available.
- Reserve "ready" messaging for completed downstream state; otherwise show running/queued/deferred truthfully.

4. Align numeric coercion policy between preview and write
- Decide policy once (reject vs coerce-to-zero), apply in both validator and write aggregation.
- Recommended minimal path: preserve write coercion, but preview should mark same rows as accepted-with-warning rather than rejected where feasible.

5. Add targeted tests for the high-risk mismatches
- Date format coverage (`MM/DD/YYYY`, `DD/MM/YYYY`, ISO)
- UPH-only mapping end-to-end preview-vs-write parity
- Import success but postprocess pending/failure state surfaces as non-ready

## Clearly Provable Bug Callout

Bug: Date values in common non-ISO formats are silently remapped to fallback work date in active import paths.
- Proof points:
  - Parser accepts only `YYYY-MM-DD` pattern in `parse_sessions_to_rows`.
  - Write path date parsing in `_import_step3` also only accepts `YYYY-MM-DD`.
  - A broader date parser already exists (`data_loader.parse_date`) but is not used in these two core paths.
- Why this is correctness-critical:
  - Day assignment drives dedupe/overlap replacement and downstream trend/snapshot windows.

## Validation Performed During Audit
- Ran focused tests:
  - `tests/test_import_pipeline.py`
  - `tests/test_jobs_scaffolding.py`
- Result: 16 passed, 0 failed.
- Note: passing tests confirm some intended mechanics but do not currently cover the preview/write parity mismatch for UPH-only mapping.
