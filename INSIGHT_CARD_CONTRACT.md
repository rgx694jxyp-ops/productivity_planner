# Insight Card Contract

Last updated: 2026-04-09
Status: App-wide rendering contract and typed model definition
Model reference: [domain/insight_card_contract.py](domain/insight_card_contract.py)

## Goal

Render every important signal with a consistent, explainable structure.

This contract enforces:
- clear narrative (what happened, compared to what, why flagged)
- trust context (confidence, workload, time, completeness)
- navigation clarity (drill-down target)
- evidence traceability (source references)

This contract explicitly avoids prescriptive action recommendations.

## Contract Fields

Required fields for every insight card:

1. title
- Short plain-language signal title.
- Example: Picking throughput dropped over the last 3 shifts.

2. what happened
- Observable change or condition, no instruction.
- Example: 6 of 18 pickers are below expected output today.

3. compared to what
- Baseline, target, prior period, or peer reference.
- Example: Team average is 58 UPH today versus 64 UPH last week.

4. why it was flagged
- Trigger logic in explainable terms.
- Example: Flagged because decline persisted for 3 consecutive shifts.

5. confidence level
- High/Medium/Low plus optional numeric score and evidence basis.
- Include caveat when sample size is small.

6. volume/workload context
- Scope, exposure, or denominator for signal relevance.
- Example: 1200 units processed this shift, 22% handled by affected group.

7. time context
- Observed window, comparison window, freshness timestamp, staleness threshold.

8. data completeness note
- What is missing/excluded and impact on interpretation.
- Example: 9% of rows missing hours; trend uses complete rows only.

9. drill-down target
- Destination screen/section/entity where user can inspect evidence.

10. supporting metadata/source references
- Source table/event/upload IDs, field references, and optional evidence excerpts.

## Typed Code Structure

The reusable model is implemented in [domain/insight_card_contract.py](domain/insight_card_contract.py).

Primary type:
- InsightCardContract

Supporting nested types:
- ConfidenceInfo
- VolumeWorkloadContext
- TimeContext
- DataCompletenessNote
- DrillDownTarget
- SourceReference

Enumerated signal categories supported:
- below_expected_performance
- trend_change
- repeated_pattern
- unresolved_issue
- follow_up_due
- suspicious_import_data
- post_activity_outcome

Validation behavior:
- validate() returns errors when core explainability fields are missing.
- Validates confidence score and missing ratio ranges.
- Requires at least one source reference.

## Rendering Rules

All cards should render in this order:
1. Title
2. What happened
3. Compared to what
4. Why flagged
5. Confidence
6. Workload context
7. Time context
8. Data completeness note
9. Drill-down link
10. Expandable source references

Do not place raw evidence tables above sections 1-8.

## Non-Prescriptive Constraint

Cards must not include recommendation phrasing such as:
- You should coach...
- Escalate now...
- Do this next...

Allowed phrasing:
- Flagged because...
- Observed pattern...
- Follow-up is due since...
- No measurable improvement after prior logged activity...

## Generic Examples

### Example A: Below expected performance

- title: Picking output below expected baseline
- what happened: 4 employees are below expected output in today morning shift.
- compared to what: Affected employees are 8-14 UPH below personal 14-day baseline.
- why flagged: Flagged because each affected employee was below baseline for 3 consecutive shifts.
- confidence level: medium (sample size: 3 shifts)
- volume/workload context: 980 units in observed window, 38% handled by affected employees.
- time context: observed today 06:00-10:00, compared to prior 14 days, last updated 10:20.
- data completeness note: partial, 6% rows missing hours.
- drill-down target: employee_detail, section performance_timeline
- sources: productivity_history rows, goal status snapshot

### Example B: Trend change

- title: Packing throughput trend shifted down this week
- what happened: Department median UPH is trending down over 5 shifts.
- compared to what: Current median 52 UPH versus prior-week median 59 UPH.
- why flagged: Flagged because week-over-week delta exceeded configured threshold.
- confidence level: high (score 0.91, sample size 5)
- volume/workload context: 2400 units total this week, normal volume range.
- time context: observed last 5 shifts, compared to previous 5 shifts.
- data completeness note: complete.
- drill-down target: team_process, section department_trends
- sources: department_shift_metrics, trend_calculation event

### Example C: Repeated pattern

- title: Repeated speed issue pattern detected
- what happened: Same issue tag appears in 3 recent logged notes for one employee.
- compared to what: Typical issue-repeat count in peer group is 1 per 14 days.
- why flagged: Flagged because repeat threshold was met within rolling window.
- confidence level: medium
- volume/workload context: 3 notes over 10 days for one employee in high-volume lane.
- time context: rolling 14-day window, last updated now.
- data completeness note: complete for notes, partial for shift-level context.
- drill-down target: employee_detail, section notes_timeline
- sources: coaching_notes table, note_tag_extract event

### Example D: Unresolved issue

- title: Open issue unresolved past expected follow-up window
- what happened: One active issue remained open for 6 days.
- compared to what: Typical closure window is 2 days for similar issues.
- why flagged: Flagged because open duration exceeds unresolved threshold.
- confidence level: high
- volume/workload context: 1 unresolved issue among 7 active issues.
- time context: opened on 2026-04-03, current date 2026-04-09.
- data completeness note: complete.
- drill-down target: employee_detail, section active_issues
- sources: action_lifecycle records

### Example E: Follow-up due

- title: Follow-up due today
- what happened: Follow-up date reached for two active items.
- compared to what: Both items were scheduled 48 hours after prior logged activity.
- why flagged: Flagged because follow_up_due_at is today and status remains open.
- confidence level: high
- volume/workload context: 2 due out of 9 active follow-ups.
- time context: due today, last updated 07:55.
- data completeness note: complete.
- drill-down target: today, section due_today_queue
- sources: follow_up schedule table

### Example F: Suspicious import data

- title: Import quality anomaly detected
- what happened: Uploaded file contains abrupt shift-hour values for multiple rows.
- compared to what: 31 rows exceed 3x normal hour range compared with prior uploads.
- why flagged: Flagged by import anomaly checks for outlier magnitude and row concentration.
- confidence level: medium
- volume/workload context: 31 anomalous rows out of 412 uploaded rows.
- time context: current upload run, compared to prior 10 successful uploads.
- data completeness note: incomplete until mapping confirmation.
- drill-down target: import_data_trust, section anomaly_details
- sources: import_preview issues, upload profile baseline

### Example G: Improvement / no improvement after prior logged activity

- title: No measurable improvement after prior check-in
- what happened: Performance remained flat after follow-up note logged 2 days ago.
- compared to what: Current UPH differs by less than 1 UPH from pre-check-in baseline.
- why flagged: Flagged because post-activity outcome window elapsed with no positive delta.
- confidence level: medium
- volume/workload context: 4 shifts observed since prior logged activity.
- time context: compared pre-activity window vs post-activity window.
- data completeness note: partial, one shift excluded due to missing units.
- drill-down target: employee_detail, section coaching_impact
- sources: coaching_note event, productivity_history rows

## Adoption Notes

- Use this contract for all high-importance surfaces in Today, Team / Process, Employee Detail, and Import / Data Trust.
- Existing page-specific schemas can be adapted into this contract at render boundary.
- Keep metadata lightweight and machine-readable for analytics and auditing.
