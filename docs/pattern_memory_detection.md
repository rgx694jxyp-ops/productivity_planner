# Pattern Memory Detection

Last updated: 2026-04-09
Status: Deterministic recent-history pattern memory
Primary source: [services/signal_pattern_memory_service.py](services/signal_pattern_memory_service.py)
Integration source: [services/signal_interpretation_service.py](services/signal_interpretation_service.py)

## Goal

Surface simple repeated patterns over recent history without introducing forecasting complexity.

Supported pattern outputs:
- repeated decline
- recurring issue
- similar pattern observed multiple times

## Detection Logic

Pattern memory is deterministic and explainable.

Action-based detection:
- Input fields include `_repeat_signals`, `_is_repeat_issue`, `issue_type`, `baseline_uph`, `latest_uph`, and recent event dates.
- Repeated decline:
  - baseline and latest are present
  - latest is below baseline
  - repeat_count >= 2
- Recurring issue:
  - repeat_count >= 2 from explicit repeat signals or repeat issue type flags
- Similar pattern:
  - repeat evidence exists but decline pair is incomplete

Goal-row detection:
- Input fields include `trend`, `change_pct`, and optional `recent_trend_history` / `recent_goal_status_history`.
- Repeated decline:
  - trend is down
  - change_pct <= -5
  - repeated recent down/below-goal counts >= 2
- Similar pattern:
  - repeated trend/goal points >= 2, even if decline threshold is not met

Recent-window guardrail:
- Action pattern memory is ignored when the reference event falls outside the recent window (default 45 days).

## Examples

1. Repeated decline
- Signals: `coached 3x`, `2x no improvement`
- Baseline/latest: 52 UPH -> 46 UPH
- Output: `pattern_kind=repeated_decline`, `repeat_count=3`

2. Recurring issue
- Signals: `2 open actions`, `2x no improvement`
- Baseline/latest unavailable
- Output: `pattern_kind=recurring_issue`, `repeat_count=2`

3. Similar pattern observed
- Recent row history: trend values include multiple `down` points
- Current decline threshold not met
- Output: `pattern_kind=similar_pattern`, `repeat_count>=2`

## Integration Points

Pattern memory is integrated at interpretation time and carried to drill-down.

Interpreted signal integration:
- [services/signal_interpretation_service.py](services/signal_interpretation_service.py)
  - `interpret_below_expected_performance`
  - `interpret_changed_from_normal`
  - `interpret_repeated_decline`
  - `interpret_unresolved_issue`
  - `interpret_follow_up_due`

Card metadata fields:
- `pattern_detected`
- `pattern_kind`
- `repeat_count`
- `pattern_summary`
- `pattern_recent_window_days` (action-based signals)

Drill-down impact:
- Pattern metadata is included in interpreted card metadata and travels through traceability/session drill-down payloads.
