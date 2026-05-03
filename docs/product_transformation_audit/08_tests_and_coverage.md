# 08 — Tests & Coverage: Current State

> Inventory and assessment of the test suite: 97 test files, 683 test functions.

---

## Overview

| Metric | Value |
|--------|-------|
| Total test files | 97 |
| Total test functions | 683 |
| Test framework | pytest ≥8.0 |
| Test directory | `tests/` |
| Integration tests (require DB) | Minimal — most tests are unit/logic tests with mocks |
| UI/rendering tests | Present via Streamlit session_state mocking patterns |
| Coverage tooling | Not configured (no `.coveragerc`, no `pytest-cov` in requirements.txt) |

---

## Test Distribution by Domain

### Today Page (highest concentration)

| File | Tests | Focus |
|------|-------|-------|
| `test_today_write_cache_invalidation.py` | 50 | Cache invalidation after completion writes |
| `test_today_card_pattern.py` | 24 | Card render pattern contracts |
| `test_today_auto_resolve.py` | 21 | Signal auto-resolution logic |
| `test_today_attention_strip.py` | 14 | Attention summary strip |
| `test_today_attention_strip_render.py` | — | Render contract for strip |
| `test_today_summary.py` | 13 | Summary block content |
| `test_today_priority_ranking.py` | 9 | Queue ranking order |
| `test_today_queue_display_eligibility.py` | 10 | Card display eligibility rules |
| `test_today_first_run_flow.py` | — | Cold-start / first session |
| `test_today_first_value_screen.py` | — | First-value empty state |
| `test_today_low_data_fallback.py` | — | Low/no data state |
| `test_today_return_trigger.py` | — | Team drill-down return |
| `test_today_team_handoff_loop.py` | — | Today → Team navigation |
| `test_today_team_risk.py` | — | Team risk view model |
| `test_today_decision_view_model.py` | — | Decision surface view model |
| `test_today_hierarchy_contract.py` | — | Section ordering contract |
| `test_today_render_order_contract.py` | — | Render order contract |
| `test_today_inline_renderer_contract.py` | — | Inline renderer contract |
| `test_today_header_return_trigger_gate.py` | — | Return trigger gate logic |
| `test_today_top_status_area.py` | — | Top status area |
| `test_today_trust_surface.py` | — | Trust score display |
| `test_today_interpretation_strip.py` | — | Interpretation copy |
| `test_today_signal_status_service.py` | — | Signal status resolution |
| `test_today_action_state_instrumentation.py` | — | Action state instrumentation |
| `test_today_action_state_lookup_cache.py` | — | Action state cache behavior |
| `test_today_action_state_surface.py` | — | Action state UI surface |
| `test_today_last_action_lookup.py` | — | Last-action per employee lookup |
| `test_today_pre_action_render_plan_cache.py` | — | Pre-action render plan caching |
| `test_today_enriched_render_plan_cache.py` | — | Enriched render plan caching |
| `test_today_weekly_activity_cache.py` | — | Weekly activity cache |
| `test_today_quick_note_flow.py` | — | Quick-note completion flow |
| `test_today_home_service.py` | — | Home service helpers |
| `test_today_page_meaning_service.py` | — | Meaning service copy |
| `test_today_demo_reset.py` | — | Demo mode reset |

### Signal Pipeline

| File | Tests | Focus |
|------|-------|-------|
| `test_attention_scoring_service.py` | 24 | Priority scoring logic |
| `test_signal_interpretation_service.py` | 14 | Natural-language signal text |
| `test_signal_formatting_service.py` | 19 | Display formatting |
| `test_signal_edge_cases.py` | 10 | Edge cases (zero hours, partial days) |
| `test_signal_quality_service.py` | — | Completeness/confidence scoring |
| `test_signal_traceability_payload.py` | — | Traceability payload contract |
| `test_signal_pattern_memory_service.py` | — | Pattern history |
| `test_daily_signals_service.py` | — | daily_signals compute |
| `test_daily_snapshot_service.py` | — | daily_employee_snapshots compute |
| `test_display_signal_factory.py` | 15 | DisplaySignal object construction |
| `test_trend_classification_service.py` | — | Trend state classification |
| `test_decision_engine_service.py` | — | Signal → decision rules |
| `test_decision_surfacing_policy_service.py` | — | When to surface signals |

### Import Pipeline

| File | Tests | Focus |
|------|-------|-------|
| `test_import_pipeline.py` | 11 | Orchestrator end-to-end |
| `test_import_page.py` | 19 | Import page UI flow |
| `test_import_quality_service.py` | — | Quality scoring |
| `test_import_trust_service.py` | — | Trust scoring |
| `test_import_repo.py` | — | Import repository queries |
| `test_import_job_service.py` | — | Job lifecycle |
| `test_import_first_insight_renderer.py` | — | First-import signal render |

### Actions & Follow-ups

| File | Tests | Focus |
|------|-------|-------|
| `test_action_state_service.py` | 17 | State machine logic |
| `test_action_service.py` | — | Action CRUD |
| `test_action_feedback.py` | — | Feedback / outcome recording |
| `test_follow_through_service.py` | — | Follow-through tracking |
| `test_followup_manager.py` | — | Legacy follow-up manager |
| `test_exception_tracking_service.py` | — | Operational exceptions |
| `test_domain_actions.py` | — | Action domain object |
| `test_employees_action_state_surface.py` | — | Employee page action state |
| `test_employees_open_actions_guard.py` | — | Open action guard logic |
| `test_action_state_write_routing_surface.py` | — | Write routing |

### Team Page

| File | Tests | Focus |
|------|-------|-------|
| `test_team_page.py` | 22 | Team page rendering |
| `test_team_page_language_service.py` | 27 | Copy generation |
| `test_team_today_bridge.py` | 29 | Team ↔ Today navigation |
| `test_team_process_service.py` | — | Team process aggregation |

### Access Control & Billing

| File | Tests | Focus |
|------|-------|-------|
| `test_access_control_service.py` | 22 | RBAC: viewer/manager/admin |
| `test_billing_service.py` | — | Entitlement logic |
| `test_entitlements.py` | — | Plan feature gates |
| `test_plan_service.py` | 10 | Plan limit enforcement |
| `test_upgrade_prompt_service.py` | — | Upgrade prompt logic |
| `test_upgrade_telemetry_service.py` | — | Upgrade telemetry |

### Infrastructure & Cross-cutting

| File | Tests | Focus |
|------|-------|-------|
| `test_app_logging.py` | — | JSONL logging + redaction |
| `test_audit_logging_service.py` | — | Audit log output |
| `test_repository_logging.py` | — | Repository query logging |
| `test_tenant_isolation.py` | — | Cross-tenant data isolation |
| `test_tenant_operational_reset.py` | — | Operational data reset |
| `test_module_ownership.py` | — | Module boundary contract |
| `test_page_router_smoke.py` | — | Routing smoke test |
| `test_jobs_scaffolding.py` | — | Background job runner |
| `test_sample_intent_flow.py` | — | Sample intent simulation |
| `test_demo_entry_path.py` | — | Demo mode entry |

### Other

| File | Tests | Focus |
|------|-------|-------|
| `test_activity_comparison_service.py` | — | Period-over-period comparison |
| `test_activity_records_service.py` | — | Activity records CRUD |
| `test_employee_detail_service.py` | — | Employee detail view model |
| `test_plain_language_service.py` | — | Natural language generation |
| `test_target_service.py` | — | Per-process targets |
| `test_ranker.py` | — | Top/bottom ranking |
| `test_domain_logic.py` | — | General domain logic |
| `test_traceability_panel_contract.py` | — | Traceability panel contract |
| `test_weekly_manager_activity_summary.py` | — | Weekly summary |
| `test_attention_priority_confidence_contract.py` | — | Priority × confidence contract |

---

## Coverage Assessment

### Well-Tested Areas

- **Today page logic** — highest test density; cache invalidation, card patterns, queue ranking, action state, attention strip all have dedicated test files
- **Signal pipeline** — attention scoring, signal interpretation, signal formatting all have dedicated coverage
- **Access control** — 22 tests verifying viewer/manager/admin permission boundaries
- **Import pipeline** — orchestrator, quality, trust, job lifecycle all covered
- **Team page** — page rendering, language service, Today bridge all tested

### Weakly-Tested Areas

| Area | Gap |
|------|-----|
| `database.py` (~90 functions) | No dedicated `test_database.py` — the largest file has no direct test file |
| `auth.py` (721 lines) | No `test_auth.py` — session management, lockout, cookie injection untested |
| `billing.py` (624 lines) | `test_billing_service.py` covers service layer; Stripe verification flow in `billing.py` itself is untested |
| Email sending (`email_engine.py`) | No `test_email_engine.py` — SMTP send path untested |
| Export (`export_manager.py`, `exporter.py`) | No export tests — Excel/PDF output untested |
| `pages/today.py` async thread path | Thread safety and `_drain_today_async_completion_results()` not directly tested |
| `pages/employees.py` (1,799 lines) | No dedicated page test |
| End-to-end / integration tests | No tests require a live Supabase connection |

### No Coverage Tooling

`requirements.txt` does not include `pytest-cov`. No `.coveragerc` exists. Coverage percentage is unknown.

---

## Testing Infrastructure Notes

- Tests use mocking (likely `unittest.mock` / `pytest-mock`) to avoid Supabase dependency
- `demo_data/` provides seed fixtures for tests that need realistic data shapes
- `conftest.py` or shared fixtures not confirmed — each test file appears to define its own setup
- No CI configuration file (`.github/workflows/`, `Makefile`, `tox.ini`) found in root
