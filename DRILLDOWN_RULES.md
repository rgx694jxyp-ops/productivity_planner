# Drill-Down Rules

Last updated: 2026-04-09
Status: Design standard for explainable signal rendering
Aligned with: INSIGHT_CARD_CONTRACT.md, UI_SCREEN_MAP.md, NAVIGATION_MODEL.md

## Goal

Define one consistent progressive disclosure model for all major signal types so users can move from:

1. top-level summary (fast scan)
2. expanded inline explanation (quick understanding)
3. full drill-down evidence (verification)

This document prioritizes:
- explainability
- progressive disclosure
- low cognitive load

## Universal Disclosure Pattern

For every signal card, use this exact order:

1. Top-level summary shown on card
- One sentence, plain language, no jargon, no recommendation.
- Must include signal direction/state and scope (who/how many).

2. Expanded explanation shown inline
- Short expandable section with:
  - what happened
  - compared to what
  - why flagged
  - confidence + caveat
  - freshness + time window
  - workload/volume context
  - completeness note

3. Full drill-down evidence on destination screen
- Full chart/timeline plus raw supporting rows.
- Preserved source context from prior screen.
- Breadcrumb and back behavior per navigation model.

4. Source/context details available to user
- Data sources used
- Key fields and thresholds
- Included vs excluded data
- Last updated timestamp
- Signal id and source references (for traceability)

## Cognitive Load Rules

- Keep card summary to one line and one numeric anchor.
- Keep inline expansion to max 7 bullets.
- Hide raw tables by default behind Evidence expander.
- Use the same labels everywhere: What happened, Compared to what, Why flagged, Confidence, Data quality.
- Never require users to open drill-down just to understand why they are seeing the signal.

## Signal-Type Rules

## 1) Below Expected Performance

Top-level summary shown on card:
- X people are below expected output in current shift.

Expanded explanation shown inline:
- What happened: Number and identity scope of affected employees.
- Compared to what: Personal baseline and/or role target.
- Why flagged: Stayed below threshold for N consecutive shifts.
- Confidence: Level + sample size (for example, 4 shifts observed).
- Volume/workload context: Units handled by affected group and share of total workload.
- Time context: Current shift window and comparison horizon.
- Data completeness note: Missing hours/units percentage and impact.

Full drill-down evidence shown on destination screen:
- Destination: Employee Detail (single person) or Team / Process (group view).
- Evidence view:
  - Per-shift trend line
  - Baseline/goal overlay
  - Shift row details (expandable)
  - Recent activity/notes timeline

Source/context details available to user:
- Sources: productivity history, goals snapshot, employee metadata.
- Threshold metadata: expected output threshold and minimum points rule.
- Exclusions: rows filtered due to missing key fields.

## 2) Changed From Normal

Top-level summary shown on card:
- Department performance changed from its normal range this week.

Expanded explanation shown inline:
- What happened: Direction and magnitude of shift from normal.
- Compared to what: Prior window median/mean and normal variability band.
- Why flagged: Change exceeded configured deviation threshold.
- Confidence: Stability of the pattern across observed windows.
- Volume/workload context: Workload level compared to usual volume.
- Time context: Current period vs matched prior period.
- Data completeness note: Coverage sufficiency for comparison.

Full drill-down evidence shown on destination screen:
- Destination: Team / Process.
- Evidence view:
  - Trend chart with normal band
  - Department/segment breakdown
  - Expandable raw period rows

Source/context details available to user:
- Sources: aggregated shift metrics, trend calculation event.
- Baseline metadata: how normal was computed and window size.
- Freshness metadata: last aggregation run timestamp.

## 3) Repeated Decline

Top-level summary shown on card:
- Repeated decline detected for this employee over recent shifts.

Expanded explanation shown inline:
- What happened: Decline sequence (example: 58 -> 55 -> 52 -> 49).
- Compared to what: Personal recent baseline and role target.
- Why flagged: Decline persisted across N consecutive observations.
- Confidence: Consecutive pattern confidence and data count.
- Volume/workload context: Volume handled across the decline period.
- Time context: Exact shift/day sequence and last update.
- Data completeness note: Any excluded shifts and why.

Full drill-down evidence shown on destination screen:
- Destination: Employee Detail.
- Evidence view:
  - Multi-day trend with annotations
  - Prior logged activities and outcomes
  - Shift-level details in expandable evidence table

Source/context details available to user:
- Sources: shift metrics, prior notes/events, risk pattern records.
- Pattern metadata: consecutive decline threshold and detection time.

## 4) Unresolved Issue

Top-level summary shown on card:
- Issue has remained open past typical resolution window.

Expanded explanation shown inline:
- What happened: Current open duration and status.
- Compared to what: Typical closure duration for similar issue type.
- Why flagged: Open duration exceeded unresolved threshold.
- Confidence: Reliability of issue timestamps/state history.
- Volume/workload context: Open issue count within active caseload.
- Time context: Opened at, expected follow-up window, now overdue duration.
- Data completeness note: Any missing lifecycle events.

Full drill-down evidence shown on destination screen:
- Destination: Employee Detail.
- Evidence view:
  - Issue lifecycle timeline
  - Prior related notes/events
  - Status-change audit trail (expandable)

Source/context details available to user:
- Sources: action lifecycle records, notes, follow-up logs.
- Rule metadata: unresolved threshold by issue type.

## 5) Overdue Follow-Up

Top-level summary shown on card:
- Follow-up is overdue for one or more active items.

Expanded explanation shown inline:
- What happened: Due date passed while status remained open.
- Compared to what: Planned due date vs current date/time.
- Why flagged: Due-state rule triggered (open + past due).
- Confidence: Due-time certainty and status consistency.
- Volume/workload context: Overdue count out of total active follow-ups.
- Time context: Days/hours overdue and last status update.
- Data completeness note: Missing due date or status caveats.

Full drill-down evidence shown on destination screen:
- Destination: Today (overdue filter) and optionally Employee Detail.
- Evidence view:
  - Overdue queue list sorted by age
  - Per-item timeline and prior logged activity

Source/context details available to user:
- Sources: follow-up schedule, action status history.
- Rule metadata: overdue ordering logic and tie-breakers.

## 6) Suspicious or Incomplete Data

Top-level summary shown on card:
- Data quality issue detected that may affect signal reliability.

Expanded explanation shown inline:
- What happened: Missing fields, outliers, or import anomalies detected.
- Compared to what: Expected schema/ranges and prior import profile.
- Why flagged: Validation/anomaly rules crossed threshold.
- Confidence: Confidence in anomaly detection and affected scope.
- Volume/workload context: Affected rows/entities as share of import.
- Time context: Import run time and relevant historical comparison window.
- Data completeness note: Explicitly state incomplete/partial status.

Full drill-down evidence shown on destination screen:
- Destination: Import / Data Trust.
- Evidence view:
  - Validation issue summary
  - Field-level anomaly breakdown
  - Row-level issue samples (expandable)
  - Import run diagnostics and mapping context

Source/context details available to user:
- Sources: import preview result, commit summary, schema checks.
- Validation metadata: failing checks, thresholds, exclusion policy.

## 7) Improvement After Prior Logged Activity

Top-level summary shown on card:
- Measurable improvement observed after prior logged activity.

Expanded explanation shown inline:
- What happened: Post-activity performance improved by defined amount.
- Compared to what: Pre-activity baseline window vs post-activity window.
- Why flagged: Outcome window elapsed and positive delta exceeded threshold.
- Confidence: Outcome confidence based on number of post-activity observations.
- Volume/workload context: Workload in pre vs post windows.
- Time context: Activity timestamp and evaluation windows.
- Data completeness note: Any excluded observations.

Full drill-down evidence shown on destination screen:
- Destination: Employee Detail (coaching impact section).
- Evidence view:
  - Before/after comparison chart
  - Prior logged activity timeline
  - Shift-level before/after evidence rows (expandable)

Source/context details available to user:
- Sources: coaching/activity logs, productivity history, outcome evaluator output.
- Evaluation metadata: delta threshold, window size, exclusion rules.

## Cross-Signal Destination Rules

- Today screen holds actionable queue-level evidence for due/overdue state.
- Employee Detail holds person-level evidence for performance, decline, unresolved, and outcome signals.
- Team / Process holds aggregate evidence for changed-from-normal and multi-person patterns.
- Import / Data Trust holds evidence for suspicious/incomplete data signals.

## Drill-Down Context Payload (required)

Every drill-down action should carry:
- source_screen
- source_reason (human-readable)
- source_filter
- signal_type
- signal_id
- entity_id or group_id
- observed_window_label

This preserves explanation continuity and keeps back navigation low-friction.

## Copy Standards (Low Cognitive Load)

Use:
- below expected
- changed from normal
- repeated decline
- unresolved
- overdue follow-up
- data quality concern
- improvement observed

Avoid:
- anomaly score language without explanation
- predictive/risk jargon without baseline context
- prescriptive instructions

## Acceptance Checklist

A signal implementation is compliant only if all are true:

1. Card summary explains the signal in one sentence.
2. Inline expansion answers what happened, compared to what, and why flagged.
3. Confidence, time, workload, and completeness are visible without leaving the card.
4. Drill-down destination shows both interpreted evidence and raw supporting rows.
5. Source/context metadata is available in an expandable detail block.
6. Wording is observational, not prescriptive.
