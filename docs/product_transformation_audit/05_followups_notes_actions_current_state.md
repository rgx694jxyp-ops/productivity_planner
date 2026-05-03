# 05 — Follow-ups, Notes & Actions: Current State

> Assessment of the workflow objects: `actions`, `action_events`, `coaching_followups`, `coaching_notes`, `operational_exceptions`.

---

## Overview

The app contains **two parallel follow-up systems** that evolved at different times:

1. **Legacy:** `coaching_followups` table + `followup_manager.py` — simple date-keyed reminders
2. **Current:** `actions` + `action_events` tables + service layer — full workflow objects with lifecycle, history, and state machine

Both are still in use. The legacy system has not been retired.

---

## Actions System (Migrations 008–013)

### `actions` Table (was `supervisor_actions`, renamed in migration 009)

The core workflow object. One `action` = one intervention or observation record for an employee.

**Key columns:**
```
id, tenant_id, employee_id, employee_name, department
issue_type          -- e.g. 'performance', 'absence', 'quality', 'recognition'
trigger_source      -- 'signal', 'manual', 'import', 'exception'
status              -- 'open' | 'in_progress' | 'resolved' | 'deferred' | 'no_action'
priority            -- 'high' | 'medium' | 'low'
action_type         -- 'follow_up' | 'note' | 'recognition' | 'exception'
note                -- free-form text
follow_up_due_at    -- timestamp
last_event_at       -- updated on every event
resolved_at         -- set when status → 'resolved'
created_by          -- user_id of creator
```

### `action_events` Table (Migration 011)

Immutable append-only log of every state change on an action.

```
id, tenant_id, action_id, employee_id
event_type    -- 'created' | 'status_changed' | 'note_added' | 'follow_up_set' |
               --  'follow_up_completed' | 'resolved' | 'deferred' | 'auto_resolved'
event_at      -- timestamp
performed_by  -- user_id
notes         -- event-level notes
outcome       -- 'completed' | 'no_show' | 'deferred' | null
next_follow_up_at  -- if follow-up was rescheduled
```

Migration 013 (`action_events_follow_through.sql`) added columns for tracking follow-through: whether a scheduled follow-up was actually completed.

### State Machine

From `services/action_state_service.py` (1,095 lines):

```
open → in_progress → resolved
     → deferred
     → no_action
in_progress → resolved
in_progress → deferred
```

Auto-resolution: if a signal that generated an action is no longer present on the next import (employee returned to target), the action can be automatically transitioned to `resolved` with `event_type = 'auto_resolved'`.

### Service Layer

| Service | Role |
|---------|------|
| `action_service.py` | High-level: `create_or_update_action()`, `resolve_action()` |
| `action_lifecycle_service.py` | Status transition validation and execution |
| `action_state_service.py` (1,095 lines) | State read: per-employee current action state, bulk state lookup |
| `action_query_service.py` | Read queries: list by employee, by status, by date range |
| `action_metrics_service.py` | Metrics: completion rate, follow-through rate, open count |
| `action_recommendation_service.py` | Suggests action type based on signal context |
| `follow_through_service.py` | Follow-through tracking (was follow-up completed?) |

### Repositories

`repositories/action_events_repo.py`, `repositories/actions_repo.py` — typed query wrappers.

---

## Legacy Follow-ups System (Migration 007)

### `coaching_followups` Table

Simpler, date-keyed reminder system:

```
id, tenant_id, emp_id, followup_date, name, dept, note_preview
```

Managed by `followup_manager.py` (~130 lines):

```python
add_followup(emp_id, name, dept, followup_date, note_preview, tenant_id)
get_followups_for_employees(emp_ids, from_date, to_date, tenant_id)
get_followups_due_today(tenant_id)
count_due_today(tenant_id)
```

**Status:** The legacy system is still queried in some UI contexts for "due today" badge counts, but new follow-up creation now goes through the `actions` system. No migration or cleanup path has been defined.

---

## Coaching Notes

### `coaching_notes` Table (Migration 001)

Free-form notes per employee, not linked to the actions workflow:

```
id, tenant_id, emp_id, note, created_by, created_at, archived (bool)
issue_type (text), tags (jsonb)
```

Managed via `database.py`:
- `add_coaching_note(emp_id, note, created_by)`
- `get_coaching_notes(emp_id, include_archived)`
- `archive_coaching_notes(emp_id)` — bulk archive on action resolution
- `update_coaching_note_tags(note_id, issue_type, tags)`

`services/coaching_service.py` and `services/coaching_intel_service.py` provide aggregation:
- `coaching_intel_service` — surfaces patterns across notes for the Coaching Intel page
- `pages/coaching_intel.py` — dedicated coaching intelligence view (plan-gated: pro/business)

---

## Operational Exceptions (Migration 012)

Context-recording objects that are not tied to an employee signal — e.g., equipment down, short-staffed, power outage:

```
id, tenant_id, employee_id (nullable), exception_date
category    -- 'absence' | 'equipment' | 'staffing' | 'quality' | 'other'
summary     -- one-line description
notes       -- extended notes
status      -- 'open' | 'resolved'
created_by, resolved_at
```

Surfaced on the Today page as a collapsible section below the attention queue (`_render_open_exceptions()`). New exceptions can be created from the Today page via `_render_exception_create_form()`.

Managed by `services/exception_tracking_service.py` and `repositories/operational_exceptions_repo.py`.

---

## Today Page Integration

The Today page is the primary interaction surface for actions and follow-ups:

- **Card completion flow:** Clicking "mark as complete" on an attention card creates or updates an `action` and appends an `action_event`
- **Action state lookup:** `_cached_today_action_state_lookup()` queries the current action state for all employees in the queue (capped at `_TODAY_ACTION_STATE_LOOKUP_MAX_EMPLOYEE_IDS = 24`)
- **Action context enrichment:** `enrich_today_queue_card_action_context()` adds prior action history to cards for display
- **Exceptions:** `_render_open_exceptions()` shows today's open exceptions

---

## Current Gaps

| Gap | Impact |
|-----|--------|
| Two parallel follow-up systems with no defined migration path | Inconsistent follow-up counts; legacy `coaching_followups` badge count may diverge from `action_events` |
| Actions not mobile-optimized | No dedicated mobile UI; full Streamlit desktop layout only |
| No notifications / push alerts for due follow-ups | Users must navigate to the app to see due follow-ups |
| Action metrics (`action_metrics_service`) exist but have no dedicated UI surface | Completion rate, follow-through rate not visible in any dashboard |
| `coaching_notes` tags/issue_type not surfaced in Today queue context | Rich note metadata is captured but not displayed on cards |
| No bulk action creation from import (e.g., auto-create actions for all below-target employees) | Each card must be completed individually |
