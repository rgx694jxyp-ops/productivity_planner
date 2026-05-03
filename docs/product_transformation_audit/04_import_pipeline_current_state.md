# 04 — Import Pipeline: Current State

> Assessment of the CSV/Excel ingestion system: `pages/import_page.py` + `services/import_pipeline/`.

---

## Overview

The import pipeline is the **only data entry path** for productivity data. There are no API connectors, no WMS integrations, and no automated data feeds. Every signal the Today page renders originates from a manually uploaded CSV or Excel file.

---

## Supported File Formats

| Format | Notes |
|--------|-------|
| CSV (UTF-8, comma-delimited) | Primary format |
| Excel (.xlsx, .xls) | Parsed via pandas/openpyxl |

---

## Required & Optional Fields

Defined in `services/import_pipeline/mapper.py`:

```python
REQUIRED_FIELDS = ["EmployeeID", "Units", "HoursWorked"]
OPTIONAL_FIELDS = ["EmployeeName", "Department", "Date", "UPH"]
```

Columns are matched by **header fingerprint** — normalized (lowercase, stripped) column name matching with fuzzy alias support. If an exact match isn't found, the user is shown a column mapping UI.

---

## Import Page Flow (3,236 lines: `pages/import_page.py`)

```
Step 1: File Upload
    └── User uploads CSV or Excel
    └── parser.parse_sessions_to_rows() → raw rows

Step 2: Column Mapping
    └── mapper.review_mapping() → MappingReview object
    └── Check mapping_profiles for recent profile match (header fingerprint)
    └── Show mapping UI if columns need user assignment
    └── User confirms mapping

Step 3: Preview & Validation
    └── orchestrator.preview_import() →
            ├── validator.validate_rows() → issues list
            ├── import_quality_service → quality summary
            ├── import_trust_service → trust score
            └── ImportPreviewResult (summary, issues, trust)
    └── Show preview: row count, issue summary, trust score, sample rows

Step 4: Confirm & Commit
    └── orchestrator.commit_import() →
            ├── importer.build_upload_payload()
            ├── Fingerprint dedup check (source_record_hash)
            ├── importer.persist_import_rows() → activity_records
            ├── importer.record_upload_event() → uploaded_files
            └── job_service.complete_job()
    └── Trigger downstream: daily_snapshot_service.recompute()
    └── Clear Today page caches
```

---

## Import Pipeline Package: `services/import_pipeline/`

| File | Purpose |
|------|---------|
| `orchestrator.py` (332 lines) | Entry points: `preview_import()`, `commit_import()`. Fingerprint-based dedup. |
| `parser.py` | `parse_sessions_to_rows()` — file → raw dict list |
| `mapper.py` | `review_mapping()` — header normalization + required field detection |
| `validator.py` | `validate_rows()` — per-row validation: numeric ranges, missing values, date formats |
| `importer.py` | `build_upload_payload()`, `persist_import_rows()`, `record_upload_event()` |
| `job_service.py` | Import job lifecycle: `create_import_job()`, `complete_job()`, `mark_stage_*()`, `serialize_job()` |
| `mapping_profiles.py` | `get_recent_mapping_profile()` — header fingerprint lookup; `build_mapping_profile_payload()` — persist new profile |

---

## Deduplication Logic

From `orchestrator.py`:

- Each activity record has a `source_record_hash` — SHA fingerprint of (tenant_id + employee_id + date + process_name + units + hours)
- On `commit_import()`, existing hashes are queried from `activity_records` for the date range in the file
- Duplicate rows are silently skipped (not double-inserted)
- Entire file duplicate detection: `uploaded_files.header_mapping` stores a file-level fingerprint; uploading the same file twice is caught at the preview stage

---

## Data Quality & Trust Assessment

`import_quality_service.py` and `import_trust_service.py` provide:

| Service | Output |
|---------|--------|
| `import_quality_service` | `ImportQualitySummary`: row counts by quality status (ok, low_hours, zero_units, estimated), overall quality score |
| `import_trust_service` | `ImportTrustSummary`: trust tier (high/moderate/low), confidence flags, issues affecting downstream signal reliability |

Quality status values (written to `activity_records.data_quality_status`):
- `ok` — clean row
- `low_hours` — hours < threshold (affects UPH reliability)
- `zero_units` — zero productivity (may be absence, downtime, or error)
- `estimated` — hours or units were inferred/defaulted
- `suspicious` — value outside expected range

Trust score is surfaced on the Today page confidence label per employee.

---

## Mapping Profile Persistence

From `mapping_profiles.py`:

- Header fingerprint = SHA-256 of sorted, normalized column names
- On commit, the confirmed column mapping is stored as `uploaded_files.header_mapping.mapping_profile`
- On next upload with matching headers, the saved profile is auto-applied — user skips the mapping step
- Profile lookup window: last 50 uploads within 30 days

---

## Plan-Gated Employee Limits

From `plan_service.py`:

| Plan | Max import employees |
|------|---------------------|
| starter | 25 |
| pro | 100 |
| business | unlimited |

If a file contains more employee IDs than the plan allows, the import is blocked at validation with a plan upgrade prompt.

---

## What the Import Pipeline Does NOT Cover

| Gap | Current State |
|-----|--------------|
| Order/shipment data | Not supported — import is productivity-only |
| Labor cost / hourly rate | Not a supported column |
| Time-tracking (clock-in/clock-out) | Not supported |
| Inventory / pick/pack counts by SKU | Not supported |
| API-based automated ingestion | Not supported |
| SFTP drop / folder watch | Not supported |
| WMS, ERP, TMS connectors | Not supported |
| Real-time streaming | Not supported |

All integration work for a "warehouse operating clarity" expansion will require extending or replacing the import pipeline with an API ingestion layer.

---

## Demo Data

`demo_data/` contains seeded CSV/JSON files for testing and demo flows:

| File | Purpose |
|------|---------|
| `demo_full_week.csv` | Clean 5-day dataset |
| `demo_messy_import.csv` | Data quality test (low hours, zero units, bad dates) |
| `demo_day_one_thin_data.csv` | New customer / sparse data state |
| `demo_new_customer_limited_data.csv` | Onboarding demo state |
| `demo_recovery_after_reset.csv` | Recovery scenario |
| `demo_supervisor_history.csv` | Multi-week history |
| `demo_variety_issues_clean.csv` | Multiple issue types |
| `demo_storytelling.json` | Pre-built signal payloads for demo mode |
| `demo_action_events_seed.json` | Pre-built action events |
| `demo_actions_seed.json` | Pre-built actions |
