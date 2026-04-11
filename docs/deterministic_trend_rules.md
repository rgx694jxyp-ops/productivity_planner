# Deterministic Trend Rules

This app uses one simple ordered rule set to classify recent performance patterns.
The goal is to describe what the data shows, not to tell a manager what to do.

## States

- `stable`
- `below expected`
- `declining`
- `improving`
- `inconsistent`
- `insufficient data`

## Rule Order

The classifier evaluates rules in this order:

1. `insufficient data`
   If there are not enough comparable recent or prior days, the app does not force a stronger label.
2. `inconsistent`
   If recent day-to-day performance varies too widely, the app shows that the pattern is not steady yet.
3. `declining`
   If the recent average is materially below the prior comparable average, the app marks it as declining.
4. `improving`
   If the recent average is materially above the prior comparable average, the app marks it as improving.
5. `below expected`
   If performance is under the expected pace but not changing enough to count as improving or declining, the app marks it as below expected.
6. `stable`
   If none of the above apply, the app marks the pattern as stable.

## Thresholds

Current thresholds are intentionally simple and deterministic:

- minimum recent points: `2`
- minimum prior points: `2`
- material change threshold: `max(1.0 UPH, 3% of prior average)`
- inconsistency threshold: `max(8.0 UPH, 12% of recent average)` with at least `4` recent values

## Where It Is Used

These states feed:

- Today cards
- Employee detail summaries
- Team/process summaries
- healthy or nothing-changed states

## User-facing intent

Trend labels should stay plain and descriptive:

- `stable`: holding steady
- `below expected`: below expected pace
- `declining`: slipping from recent pace
- `improving`: moving up from recent pace
- `inconsistent`: moving around from day to day
- `insufficient data`: not enough recent history yet
