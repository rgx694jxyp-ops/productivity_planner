# Drill-Down Rules

## Progressive Disclosure Contract

1. Summary first
2. Expand for context
3. Drill down for evidence/source data

## Required Drill-Down Payload Context

When navigating from a signal:
- source_screen
- signal_type
- signal_id
- entity/process identifier
- compared-to window metadata (where available)

## Evidence Expectations

Drill-down should provide:
- included records
- excluded records with reason
- trend/time series context
- source import/upload references when available

## UI Constraints

- cards first at top-level screens
- raw tables only in drill-down/evidence sections
- clear empty/loading/error states for every major section

## Trust Constraints

- if evidence is sparse, show caveat plainly
- avoid strong claims from weak or incomplete data
