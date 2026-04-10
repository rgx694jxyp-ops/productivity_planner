# Signal Interpretation Examples

Last updated: 2026-04-09
Status: Usage examples and integration points for centralized interpretation helpers
Source: [services/signal_interpretation_service.py](services/signal_interpretation_service.py)

## Purpose

Provide deterministic, manager-friendly interpretation patterns that convert raw operational signals into explainable cards.

Each interpreted signal includes:
- what happened
- compared to what
- why surfaced
- confidence/context note
- optional areas to review (non-prescriptive)
- drill-down metadata

## Core Helper Entry Points

Signal-type interpreters:
- interpret_below_expected_performance
- interpret_changed_from_normal
- interpret_repeated_decline
- interpret_unresolved_issue
- interpret_follow_up_due
- interpret_suspicious_or_incomplete_data
- interpret_outcome_after_logged_activity

View-level adapters:
- interpret_today_view_signals
- interpret_employee_detail_view_signals
- interpret_team_process_view_signals
- interpret_import_data_trust_view_signals

## Example: Below Expected Performance

Input shape (raw row):
```python
row = {
    "EmployeeID": "E14",
    "Employee": "Jordan",
    "Department": "Picking",
    "Average UPH": 46,
    "Target UPH": 58,
    "trend": "down",
    "goal_status": "below_goal",
}
```

Usage:
```python
from datetime import date
from services.signal_interpretation_service import interpret_below_expected_performance

card = interpret_below_expected_performance(row=row, today=date(2026, 4, 9))
```

Result highlights:
- card.what_happened: current value
- card.compared_to_what: target/baseline context
- card.why_flagged: deterministic non-prescriptive trigger text
- card.metadata["optional_review_areas"]: context to review
- card.drill_down: destination metadata

## Example: Follow-Up Due (Queue Item)

Input shape (raw action):
```python
action = {
    "id": "a-901",
    "employee_id": "E14",
    "employee_name": "Jordan",
    "department": "Picking",
    "follow_up_due_at": "2026-04-08",
    "_queue_status": "overdue",
    "status": "new",
}
```

Usage:
```python
from datetime import date
from services.signal_interpretation_service import interpret_follow_up_due

card = interpret_follow_up_due(action=action, today=date(2026, 4, 9))
```

Result highlights:
- overdue timing explained in what_happened
- confidence basis tied to due-date metadata
- drill-down points to Today queue details

## Example: Today View Sections

Usage:
```python
from datetime import date
from services.signal_interpretation_service import interpret_today_view_signals

sections = interpret_today_view_signals(
    queue_items=queue_items,
    goal_status=goal_status,
    import_summary=import_summary,
    today=date(2026, 4, 9),
)
```

Output keys:
- needs_attention
- changed_from_normal
- unresolved_items
- data_warnings

## Integration Points

Current integration:
- Today home sections are built via [services/today_home_service.py](services/today_home_service.py), which now delegates to centralized interpretation.

Ready-to-use integrations:
1. Employee Detail
- Use interpret_employee_detail_view_signals(action_rows=..., today=...)
- Suggested location: employee summary panel before full timeline evidence.

2. Team/Process
- Use interpret_team_process_view_signals(goal_status=..., today=...)
- Suggested location: top signal cards before any ranked table/list.

3. Import/Data Trust
- Use interpret_import_data_trust_view_signals(import_summary=..., goal_status=..., today=...)
- Suggested location: import summary warning/context cards.

## Determinism Notes

Deterministic by design:
- No randomization.
- Reference timestamps derive from the input date.
- Confidence outcomes come from explicit thresholds and missing-data ratios.

## Non-Prescriptive Notes

Interpretation language is observational:
- describes signal state and evidence context
- does not prescribe supervisor actions
- optional review areas are contextual, not directive
