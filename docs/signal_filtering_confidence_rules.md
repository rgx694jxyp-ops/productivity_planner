# Signal Filtering And Confidence Rules

Last updated: 2026-04-09
Status: Deterministic rule reference
Source: [services/signal_quality_service.py](services/signal_quality_service.py)

## Goal

Reduce noisy insights while keeping strong, explainable signals visible.

## Confidence Levels

Signals continue to use three confidence levels:
- high
- medium
- low

Confidence is derived from existing interpretation inputs (sample size, expected minimum points, and completeness caveats).

## Deterministic Quality Scoring

Each signal gets a quality score from 0 to 100.

Base score:
- Start at 50.

Adjustments:
- Confidence level:
  - high: +30
  - medium: +10
  - low: -15
- Data completeness status:
  - complete: +15
  - partial: -10
  - incomplete: -25
- Sample size too small:
  - if sample_size < minimum_expected_points: -20
- Partial shift/row known:
  - partial_shift or partial_row metadata: -12
- Known anomalies:
  - anomaly_count > 0: subtract min(20, 5 * anomaly_count)
- Promotion for stronger repeated patterns:
  - repeated pattern + complete data: +15

Clamp:
- Score is clamped to [0, 100].

## Quality Tiers

Tier mapping:
- strong: score >= 70
- usable: 45 <= score < 70
- weak: score < 45

Filtering behavior:
- Default major insight sections suppress weak signals (score < 45).
- Data warning sections can keep weak signals for transparency.

Ranking behavior:
- Included signals are ranked by quality score descending.
- Stable tie-breaker: insight_id ascending.

## Where Applied

Primary application is in interpretation adapters:
- Today view sections
- Team/process interpreted signals
- Employee detail interpreted signals
- Import/data trust interpreted signals

This ensures top-level cards prioritize strong signals while preserving drill-down context for weaker/noisy signals where appropriate.

## UI Confidence Display

Confidence appears in these UI surfaces:
- Today insight cards: confidence line (level + basis)
  - [pages/today.py](pages/today.py)
- Low-confidence state panel when low-confidence cards exist
  - [pages/today.py](pages/today.py)
  - [ui/state_panels.py](ui/state_panels.py)
- Import trust summary status (valid/partial/low_confidence/invalid)
  - [pages/import_page.py](pages/import_page.py)

## Workload-Aware Interpretation Notes

Interpreted cards now add workload-volume context when goal-status rows include:
- Total Units
- Hours Worked
- Average UPH
- Target UPH (for normal-volume comparison)

How comparisons are framed:
- Same-workload baseline: expected units are computed as `Target UPH * Hours Worked`.
- If observed units are below that baseline, card copy clarifies lower processed volume at the current workload exposure.
- If observed units are above that baseline, card copy clarifies above-expected processed volume at the current workload exposure.
- If units/hours are missing, card copy explicitly states that comparison relies mostly on UPH trend context.

Example phrasing:
- "At this workload volume, processed volume is 60 unit(s) below the normal-volume expectation for 8.0 hour(s)."
- "Workload volume fields are incomplete, so this comparison relies mostly on UPH trend context."

Current limitations:
- Workload context is strongest for goal-status rows where units and hours are present.
- Action-based signals (for example, follow-up due, unresolved issue) often lack explicit units/hours and therefore rely on UPH pair or lifecycle timing context.
- The workload baseline uses target pace and same-hour exposure; it does not yet model item complexity mix or non-standard shift constraints.
