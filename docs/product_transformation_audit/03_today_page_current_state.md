# 03 — Today Page: Current State

> Deep dive on `pages/today.py` — the central product surface and the largest single file in the codebase.

---

## File Vital Statistics

| Attribute | Value |
|-----------|-------|
| File | `pages/today.py` |
| Line count | **5,817 lines** |
| Function count | **~110 functions** |
| Rendering CSS | ~500 lines inline (via `_apply_today_styles()`) |
| Also routed from | `"supervisor"` page key (identical handler) |

---

## What This Page Does

The Today page is the primary daily operating surface. It answers: *"What happened today, who needs attention, and why?"*

It renders:

1. **Attention queue** — ranked cards, one per employee signal, organized into sections (needs attention / doing well / notable)
2. **Summary strip** — metric tiles: total signals surfaced, completion rate, avg confidence, etc.
3. **Value strip** — quick-read summary cards (top output, most improved, consistency, etc.)
4. **Copy summary block** — clipboard-copyable standup/summary text
5. **Open exceptions** — operational exceptions for the day (floor issues, absences, etc.)
6. **Return-from-Team trigger** — navigation back from team drilldown

---

## Execution Flow

```
page_today()
    └── _page_today_impl()
            ├── _today_log_milestone("cold_start")
            ├── _run_today_auto_refresh()           # 60-second timer check
            ├── Phase 1: _render_today_loading_shell()    # First paint (skeleton)
            │           st.rerun() if data not ready
            ├── Phase 2: _attempt_signal_payload_recovery()
            │           ├── Check daily_employee_snapshots (exist for today?)
            │           ├── If not: _schedule_today_snapshot_recompute_async()
            │           │           └── threading.Thread → recompute pipeline
            │           └── Compute daily_signals from snapshots
            └── Phase 3: Full render
                        ├── _render_queue_orientation_block()
                        ├── _render_attention_summary_strip()
                        ├── _render_unified_attention_queue()
                        │       └── _render_attention_card() × N
                        │               └── _render_guided_completion_controls()
                        ├── _render_today_value_strip()
                        ├── _render_today_copy_summary_block()
                        ├── _render_open_exceptions()
                        └── _render_return_trigger()
```

---

## Key Constants

```python
_READ_CACHE_TTL_SECONDS          = 300    # 5-minute signal cache
_TODAY_QUEUE_DEFAULT_VISIBLE_CARDS = 3    # Cards shown before "show more"
_TODAY_ACTION_STATE_LOOKUP_MAX_EMPLOYEE_IDS = 24  # Max IDs for action state query
_TODAY_AUTO_REFRESH_MIN_SECONDS  = 60    # Auto-refresh interval
```

---

## Caching Architecture

Three `@st.cache_data` functions within today.py, all keyed by `(tenant_id, date)`:

| Function | Purpose | TTL |
|----------|---------|-----|
| `_cached_today_signals_payload()` | Full signal list + metadata from `daily_signals` | 300s |
| `_cached_today_action_state_lookup()` | Action state per employee (open, in_progress, resolved) | 300s |
| `_cached_today_signal_status_map()` | Completion status per signal | 300s |

Cache invalidation after any write: `_invalidate_today_write_caches()` calls `st.cache_data.clear()` for all three functions.

---

## Card Completion Flow

The attention queue supports a "mark as complete" interaction:

```
User clicks complete →
    _render_guided_completion_controls()      # Note entry + follow-up scheduling UI
        └── _save_today_card_completion()     # Validates + builds write payload
                └── _optimistically_complete_today_card()   # Immediate UI update
                └── _start_today_completion_write_async()   # threading.Thread write
                        └── action_service.create_or_update_action()
                        └── _invalidate_today_write_caches()
On next rerun:
    _drain_today_async_completion_results()  # Checks thread results, surfaces errors
```

**Thread safety risk:** `st.session_state["_today_async_write_threads"]` is appended to from background threads while the main thread may be re-running. See file 10 for full risk assessment.

---

## Signal Payload Recovery

On cold start, if `daily_signals` has no rows for today:

1. Checks `daily_employee_snapshots` for today's data
2. If snapshots exist → calls `daily_signals_service.compute_signals_from_snapshots()`
3. If snapshots don't exist → spawns background thread to run `daily_snapshot_service.recompute_snapshots()` → then re-runs signal compute
4. Updates `st.session_state["_today_signal_payload"]` and triggers `st.rerun()`

This recovery path runs in a background thread, which means the UI shows a loading state while recompute is in flight.

---

## Function Inventory (selected)

| Function | Lines (approx) | Role |
|----------|---------------|------|
| `page_today()` | 10 | Entry point |
| `_page_today_impl()` | ~100 | Orchestration |
| `_attempt_signal_payload_recovery()` | ~80 | Cold-start data init |
| `_schedule_today_snapshot_recompute_async()` | ~40 | Background recompute thread |
| `_render_unified_attention_queue()` | ~200 | Queue container + card loop |
| `_render_attention_card()` | ~300 | Individual card render |
| `_render_guided_completion_controls()` | ~200 | Completion UI: note + follow-up |
| `_save_today_card_completion()` | ~80 | Completion payload build + validate |
| `_optimistically_complete_today_card()` | ~40 | Immediate session_state update |
| `_start_today_completion_write_async()` | ~60 | Async write thread |
| `_drain_today_async_completion_results()` | ~50 | Async result handler |
| `_cached_today_signals_payload()` | ~30 | `@st.cache_data` signal read |
| `_cached_today_action_state_lookup()` | ~30 | `@st.cache_data` action state |
| `_cached_today_signal_status_map()` | ~20 | `@st.cache_data` status read |
| `_invalidate_today_write_caches()` | ~15 | Cache clear |
| `_run_today_auto_refresh()` | ~30 | 60s refresh timer |
| `_render_today_loading_shell()` | ~80 | Phase 1 skeleton |
| `_render_queue_orientation_block()` | ~40 | Queue header framing |
| `_render_attention_summary_strip()` | ~120 | Metric tiles (st.metric) |
| `_render_today_value_strip()` | ~150 | Quick-read summary cards |
| `_render_today_copy_summary_block()` | ~80 | Clipboard copy |
| `_render_open_exceptions()` | ~200 | Exception list + create form |
| `_render_exception_create_form()` | ~100 | New exception form |
| `_render_return_trigger()` | ~30 | Team nav back |
| `_go_to_drill_down()` | ~20 | Navigate to team/employee |
| `_today_log_milestone()` | ~20 | Cold-load timeline logging |
| `_apply_today_styles()` | ~500 | **Inline CSS block** |

---

## View Model Dependencies

`pages/today.py` depends on `services/today_view_model_service.py` (2,486 lines) for all view model assembly:

| View Model Type | Purpose |
|----------------|---------|
| `TodayQueueCardViewModel` | Per-card: employee, signal_type, label, values, confidence, flags, action_context |
| `TodayAttentionStripViewModel` | Summary strip metrics |
| `TodayManagerLoopStripViewModel` | Manager loop section |
| `TodayWeeklySummaryViewModel` | Weekly summary block |
| `TodayLowDataFallbackViewModel` | Low-data / new tenant state |
| `TodayTeamRiskViewModel` | Team-level risk rollup |
| `TodayReturnTriggerViewModel` | Team-drill return state |
| `TodayValueStripViewModel` | Quick-read value tiles |

Key builders: `build_today_queue_card_from_insight_card()`, `build_today_attention_strip()`, `build_today_manager_loop_strip()`, `enrich_today_queue_card_action_context()`.

---

## Design Posture (Product Contract)

From `INSIGHT_CARD_CONTRACT.md` and `PRODUCT_GUARDRAILS.md`:

- Cards must surface **why** a signal appeared ("surfaced because…", "data suggests…", "compared with…")
- No prescriptive directives: cards do not say "coach this employee" or "take action"
- Confidence and data quality are always visible on cards
- Drill-down support: cards link to employee detail or team view

---

## Refactor Readiness

The file violates single-responsibility at every level:

| Concern | Status |
|---------|--------|
| CSS | Inline, ~500 lines, no separation |
| Caching logic | Embedded in page file |
| Thread management | Embedded in page file |
| Signal recovery orchestration | Embedded in page file |
| View model assembly | Delegated to today_view_model_service ✓ |
| DB access | Via service layer ✓ (mostly) |
| Business rules | Partially in page, partially in service layer |

**Refactor path:** Extract CSS to `ui/today_styles.py`; extract cache + async write logic to `services/today_write_service.py`; extract signal recovery to `services/today_init_service.py`; reduce today.py to a thin render orchestrator (~500 lines target).

The `services/today_view_model_service.py` (2,486 lines) is also a candidate for decomposition into per-section services.
