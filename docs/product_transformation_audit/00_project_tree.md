# 00 — Project Tree

> Annotated directory map to 4 levels. Generated during the product/architecture review.

```
dpd_web/
│
├── app.py                              # Streamlit entry point — 50 lines
├── auth.py                             # Login/signup/session — 721 lines
├── billing.py                          # Stripe checkout verification — 624 lines
├── cache.py                            # Cross-module cache helpers
├── charts.py                           # Matplotlib chart helpers
├── data_loader.py                      # Legacy data load helpers
├── data_processor.py                   # Legacy processing helpers
├── database.py                         # Single DB layer (Supabase) — 2,700 lines, ~90 functions
├── email_engine.py                     # SMTP scheduling + encrypted credentials
├── error_log.py                        # Legacy error logger
├── export_manager.py                   # Excel export for order/employee data
├── exporter.py                         # Legacy Excel + PDF export (openpyxl/matplotlib)
├── followup_manager.py                 # coaching_followups table CRUD — 130 lines
├── goals.py                            # Tenant goal I/O helpers
├── history_manager.py                  # UPH history helpers
├── orders.py                           # Order progress helpers
├── ranker.py                           # Top/bottom performer ranking — 302 lines
├── requirements.txt                    # streamlit, supabase, pandas, openpyxl, matplotlib,
│                                       #   requests, cryptography, pytest
├── scheduler_logs.sh                   # Shell wrapper for scheduled log viewing
├── settings.py                         # Settings object (timezone, output dir, etc.)
├── styles.py                           # Legacy CSS helpers
├── trends.py                           # Legacy trend helpers
├── ui_improvements.py                  # Misc UI helper patches
│
├── core/                               # App bootstrap & cross-cutting
│   ├── app_flow.py                     # init_runtime() entry point
│   ├── billing_cache.py                # Billing TTL cache wrapper
│   ├── dependencies.py                 # Shared dependency helpers
│   ├── navigation.py                   # Sidebar nav, plan gating — 275 lines
│   ├── onboarding_intent.py            # First-run onboarding state detection
│   ├── page_router.py                  # dispatch_page() router — 54 lines
│   ├── runtime.py                      # Streamlit st handle + runtime init
│   └── session.py                      # SESSION_DEFAULTS, init_session_state()
│
├── pages/                              # Page-level Streamlit modules
│   ├── today.py                        # Today / daily clarity dashboard — 5,817 lines ⚠️ MONOLITH
│   ├── team.py                         # Team roster & status — 1,635 lines
│   ├── employees.py                    # Employee detail drilldown — 1,799 lines
│   ├── import_page.py                  # CSV/Excel upload + preview — 3,236 lines
│   ├── coaching_intel.py               # Coaching intelligence view
│   ├── cost_impact.py                  # Cost/efficiency impact view
│   ├── dashboard.py                    # Dashboard overview
│   ├── email_page.py                   # Email schedule config — 405 lines
│   ├── productivity.py                 # Productivity trends page
│   ├── settings_page.py                # Tenant settings page
│   ├── shift_plan.py                   # Shift planning page
│   ├── supervisor.py                   # Supervisor alias → today
│   └── common.py                       # Shared page utilities
│
├── services/                           # Business logic layer (~50 files)
│   ├── today_view_model_service.py     # Today page view model builder — 2,486 lines
│   ├── signal_interpretation_service.py  # Signal meaning text — 1,458 lines
│   ├── action_state_service.py         # Action workflow state machine — 1,095 lines
│   ├── daily_signals_service.py        # daily_signals table read/compute — 611 lines
│   ├── daily_snapshot_service.py       # daily_employee_snapshots compute — 519 lines
│   ├── attention_scoring_service.py    # Attention priority score — 374 lines
│   ├── billing_service.py              # get_subscription_entitlement() — 340 lines
│   ├── import_pipeline/                # 7-file import sub-package
│   │   ├── orchestrator.py             # preview_import() / commit_import()
│   │   ├── parser.py                   # parse_sessions_to_rows()
│   │   ├── mapper.py                   # review_mapping(), field normalization
│   │   ├── validator.py                # validate_rows()
│   │   ├── importer.py                 # persist_import_rows(), record_upload_event()
│   │   ├── job_service.py              # Import job lifecycle CRUD
│   │   └── mapping_profiles.py         # Header fingerprint + profile persistence
│   ├── access_control_service.py       # RBAC: viewer/manager/admin roles
│   ├── action_lifecycle_service.py     # Action status transitions
│   ├── action_metrics_service.py       # Action completion metrics
│   ├── action_query_service.py         # Action read queries
│   ├── action_recommendation_service.py # Action suggestion logic
│   ├── action_service.py               # High-level action orchestration
│   ├── activity_comparison_service.py  # Period-over-period comparison
│   ├── activity_records_service.py     # activity_records table helpers
│   ├── app_logging.py                  # Structured JSONL logging + redaction
│   ├── coaching_intel_service.py       # Coaching intelligence aggregation
│   ├── coaching_service.py             # Coaching notes service
│   ├── cost_service.py                 # Labor cost estimates
│   ├── decision_engine_service.py      # Signal → action decision rules
│   ├── decision_surfacing_policy_service.py  # When/how to surface signals
│   ├── demo_data_service.py            # Demo data seeding
│   ├── display_signal_factory.py       # display_signal domain object factory
│   ├── email_service.py                # Scheduled email orchestration
│   ├── employee_detail_service.py      # Single-employee view model
│   ├── employee_service.py / employees_service.py  # Employee CRUD wrappers
│   ├── exception_tracking_service.py   # Operational exception helpers
│   ├── follow_through_service.py       # Action follow-through tracking
│   ├── import_date_service.py          # Import date parsing/normalization
│   ├── import_quality_service.py       # Data quality assessment
│   ├── import_service.py               # High-level import entry point
│   ├── import_trust_service.py         # Data trust scoring
│   ├── observability.py                # log_app_error() / log_operational_event()
│   ├── onboarding_service.py           # First-run detection
│   ├── perf_profile.py                 # PerfProfile context manager
│   ├── plan_service.py                 # Plan limit enforcement
│   ├── plain_language_service.py       # Natural-language text generation
│   ├── productivity_service.py         # Period productivity report builder
│   ├── recommendation_service.py       # Cross-signal recommendations
│   ├── settings_service.py             # Settings read/write
│   ├── shift_service.py                # Shift plan helpers
│   ├── signal_formatting_service.py    # Signal display formatting
│   ├── signal_pattern_memory_service.py # Pattern history tracking
│   ├── signal_quality_service.py       # Signal completeness/confidence scoring
│   ├── signal_traceability_service.py  # Signal source tracing
│   ├── target_service.py               # Per-process target management
│   ├── team_page_language_service.py   # Team page copy generation
│   ├── team_process_service.py         # Team-level process aggregation
│   ├── today_home_service.py           # Today page home-section helpers
│   ├── today_page_meaning_service.py   # Today signal meaning
│   ├── today_queue_service.py          # Today queue card ordering
│   ├── today_signal_status_service.py  # Signal status resolution
│   ├── today_snapshot_signal_service.py # Snapshot → signal bridge
│   ├── trend_classification_service.py # Trend state classification
│   └── upgrade_prompt_service.py / upgrade_telemetry_service.py
│
├── repositories/                       # DB query layer (thin wrappers over supabase client)
│   ├── _common.py                      # get_client(), tenant_query()
│   ├── action_events_repo.py
│   ├── actions_repo.py
│   ├── activity_records_repo.py
│   ├── billing_repo.py
│   ├── daily_employee_snapshots_repo.py
│   ├── daily_signals_repo.py
│   ├── employees_repo.py
│   ├── import_repo.py
│   ├── operational_exceptions_repo.py
│   └── tenant_repo.py
│
├── domain/                             # Domain model objects
│   ├── actions.py
│   ├── activity_records.py
│   ├── benchmarks.py
│   ├── display_signal.py               # DisplaySignal: canonical view-ready signal object
│   ├── import_quality_models.py
│   ├── insight_card_contract.py        # InsightCard contract (Today card shape)
│   ├── operational_exceptions.py
│   ├── risk.py
│   └── risk_scoring.py
│
├── models/                             # Pydantic / dataclass models
│   └── import_quality_models.py
│
├── ui/                                 # Reusable UI components
│   ├── coaching_components.py
│   ├── components.py
│   ├── copy_patterns.py
│   ├── floor_language.py
│   ├── landing.py
│   ├── state_panels.py
│   ├── today_queue.py
│   └── traceability_panel.py
│
├── jobs/                               # Background/scheduled job runners
│   ├── entrypoints.py
│   ├── runner.py
│   └── types.py
│
├── email/                              # Email template rendering
│   └── templates.py
│
├── migrations/                         # 19 SQL migration files (Supabase)
│   ├── 001_setup.sql                   # Core schema: tenants, employees, orders, uph_history…
│   ├── 002_subscriptions.sql
│   ├── 003_*.sql (×3)                  # Missing columns, subscription_events, team_invites
│   ├── 004_pending_plan_changes.sql
│   ├── 005_operations_features.sql
│   ├── 006_stripe_webhook_events.sql
│   ├── 007_coaching_followups.sql
│   ├── 008_supervisor_actions.sql
│   ├── 009_rename_actions_table.sql
│   ├── 010_actions_core_object.sql
│   ├── 011_action_events.sql
│   ├── 012_operational_exceptions.sql
│   ├── 013_action_events_follow_through.sql
│   ├── 014_activity_records.sql
│   ├── 015_process_targets.sql
│   ├── 016_daily_employee_snapshots.sql
│   ├── 017_daily_snapshot_trend_states.sql
│   ├── 018_role_normalization.sql
│   └── 019_daily_signals.sql
│
├── supabase/
│   └── functions/
│       └── stripe-webhook/
│           └── index.ts                # Deno edge function: Stripe event → subscriptions table
│
├── tests/                              # 97 test files, 683 test functions
│   ├── test_today_write_cache_invalidation.py  (50 tests — largest)
│   ├── test_team_today_bridge.py               (29 tests)
│   ├── test_team_page_language_service.py      (27 tests)
│   ├── test_today_card_pattern.py              (24 tests)
│   ├── test_attention_scoring_service.py       (24 tests)
│   └── … (92 more files)
│
├── demo_data/                          # CSV/JSON seed files for demo mode
├── docs/                               # Markdown documentation
│   └── product_transformation_audit/  # ← THIS AUDIT
└── scripts/                            # Utility / migration scripts
```

## Key Size Indicators

| File | Lines | Role |
|------|-------|------|
| pages/today.py | 5,817 | Today dashboard — monolith |
| database.py | ~2,700 | Single DB access layer |
| services/today_view_model_service.py | 2,486 | Today view model builder |
| pages/import_page.py | 3,236 | Import page |
| pages/employees.py | 1,799 | Employee drilldown |
| pages/team.py | 1,635 | Team page |
| services/signal_interpretation_service.py | 1,458 | Signal text generation |
| services/action_state_service.py | 1,095 | Action state machine |

## Notable Absent Items

- No REST API layer (app is UI-only; no `/api/` routes)
- No mobile-native or PWA shell
- No integration adapters (QuickBooks, Shopify, ShipStation, WMS, TMS)
- No scheduled report template store (schedules live in DB as JSON config)
- No `docker-compose.yml` or local dev container config
- No `.env.example` in repo root (credentials flow via `.streamlit/secrets.toml` or env vars)
